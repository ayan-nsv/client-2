# Placeholder file - Copy your holdflight/src/scraping/scan.py content here
# Website scanning
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import re
import json
import random
import time
import logging
from urllib.parse import unquote
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException
import atexit
import os
import cssutils
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import yake
from langdetect import detect, detect_langs
from typing import Any, Dict
from holdflight.src.scraping.address import AddressScraper
from holdflight.src.utils.chrome_options import (
    add_chrome_no_sandbox_if_needed,
    get_required_chromedriver_path,
    safe_driver_get,
    safe_get,
)

def extract_keywords(text, top_n=20):
    """Extract keywords from text using YAKE."""
    if not text or len(text.strip()) < 10:
        return []
    
    try:
        lang = detect_language(text)
        try:
            kw_extractor = yake.KeywordExtractor(lan=lang, n=2, top=top_n)
        except:
            kw_extractor = yake.KeywordExtractor(lan="en", n=2, top=top_n)
        
        keywords = kw_extractor.extract_keywords(text)
        return [kw for kw, score in keywords]
    except Exception as e:
        logging.warning(f"Keyword extraction failed: {e}")
        return []

def detect_language(text):
    """Detect language of text."""
    try:
        return detect(text)
    except Exception as e:
        logging.warning(f"Language detection failed: {e}")
        return "en"

def clean_text(soup):
    """Clean and extract relevant text from BeautifulSoup object."""
    if soup is None:
        return ""
    
    # Remove unwanted tags
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form", "aside"]):
        tag.extract()
    
    texts = []
    for tag in soup.find_all(["h1", "h2", "h3", "p", "span", "li"]):
        line = tag.get_text(" ", strip=True)
        if line and len(line.split()) > 2:
            texts.append(line)
    
    return " ".join(texts)

_address_cache: Dict[str, Any] = {}

class ImprovedAddressScraper:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    
    def get_page(self, url):
        """Get page content with error handling"""
        try:
            response = safe_get(self.session, url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    def clean_text(self, text):
        """Clean and normalize text"""
        if not text:
            return ""
        # Remove extra whitespace but preserve line breaks for address formatting
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n', text)  # Remove empty lines
        return text.strip()
    
    def extract_footer_sections(self, soup):
        """Extract footer content and break into logical sections"""
        footer_text = ""
        
        # Get footer elements
        footer_selectors = [
            'footer', '.footer', '#footer', '.site-footer', '#site-footer',
            '.main-footer', '.footer-content', '.footer-bottom', '.footer-info',
            '[class*="footer"]', '[id*="footer"]'
        ]
        
        for selector in footer_selectors:
            elements = soup.select(selector)
            for element in elements:
                footer_text += "\n---SECTION---\n" + element.get_text(separator="\n", strip=True)
        
        # Also get address-specific elements from entire page
        address_selectors = [
            '[class*="address"]', '[class*="contact"]', '[class*="location"]',
            '[class*="headquarter"]', '[class*="office"]', '.contact-info',
            '.company-address', '.office-location', '.physical-address',
            '[itemprop="address"]', '.adr', '.street-address'
        ]
        
        for selector in address_selectors:
            elements = soup.select(selector)
            for element in elements:
                footer_text += "\n---ADDRESS-SECTION---\n" + element.get_text(separator="\n", strip=True)
        
        return footer_text
    
    def extract_address_blocks(self, text):
        """Extract logical blocks of text that might contain addresses"""
        lines = text.split('\n')
        blocks = []
        current_block = []
        
        for line in lines:
            line = self.clean_text(line)
            if not line:
                continue
                
            # Start new block for section markers or obvious new sections
            if line.startswith('---') or len(line) < 5:
                if current_block:
                    blocks.append('\n'.join(current_block))
                    current_block = []
                continue
            
            # If line looks like it starts a new section (short line, keywords)
            section_keywords = ['office', 'location', 'address', 'contact', 'headquarters', 'visit us', 'besöksadress', 'besök', 'adress']
            if (len(line) < 30 and any(keyword in line.lower() for keyword in section_keywords)) or len(current_block) > 10:
                if current_block:
                    blocks.append('\n'.join(current_block))
                current_block = [line]
            else:
                current_block.append(line)
        
        if current_block:
            blocks.append('\n'.join(current_block))
        
        return blocks
    
    def validate_address(self, address):
        """Validate if text looks like a real address"""
        address = self.clean_text(address)
        
        # Basic length checks
        if len(address) < 10 or len(address) > 200:
            return False
        
        # Should contain some numbers (usually street numbers or postal codes)
        if not re.search(r'\d', address):
            return False
        
        # Swedish postal code pattern (5 digits)
        if re.search(r'\b\d{3}\s?\d{2}\b', address):
            return True
        
        # Should contain some geographic indicators
        geographic_indicators = [
            'street', 'st', 'avenue', 'ave', 'road', 'rd', 'boulevard', 'blvd',
            'lane', 'ln', 'drive', 'dr', 'court', 'ct', 'parkway', 'pkwy',
            'city', 'town', 'state', 'province', 'country', 'zip', 'postal',
            'gata', 'väg', 'platz', 'straße', 'vägen', 'gränd'  # International terms
        ]
        
        if any(indicator in address.lower() for indicator in geographic_indicators):
            return True
        
        # Swedish address pattern: Streetname Number, PostalCode City
        if re.search(r'[A-Za-zåäöÅÄÖ]+\s+\d+,\s*\d{3}\s?\d{2}\s+[A-Za-zåäöÅÄÖ]+', address, re.IGNORECASE):
            return True
        
        # Simple pattern with comma separation
        if re.search(r'.+,\s*.+', address) and len(address) > 15:
            return True
        
        return False
    
    def find_best_address(self, text_blocks):
        """Find the best address candidate from text blocks"""
        address_patterns = [
            # Swedish format: Streetname Number, PostalCode City
            r'[A-Za-zåäöÅÄÖ\s]+\d+,\s*\d{3}\s?\d{2}\s+[A-Za-zåäöÅÄÖ\s]+',
            # International address format: Street, City, PostalCode Country
            r'\d+[\w\s\.\-]+,?\s*[\w\s\.\-]+,\s*\d{3,10}\s+[\w\s\.\-]+',
            # US/Canada format: 123 Main St, City, State ZIP
            r'\d+\s+[\w\s\.\-]+?(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr)[\s,]*[\w\s\.\-]+?[,\s]*[A-Z]{2}\s+\d{5}',
            # European format: Street, PostalCode City, Country
            r'[\w\s\.\-]+,\s*\d{3,10}\s+[\w\s\.\-]+',
            # Simple format with postal code
            r'[\w\s\.\-]+,\s*[\w\s\.\-]+?\s+\d{3,10}',
        ]
        
        best_candidate = None
        best_score = 0
        
        for block in text_blocks:
            block = self.clean_text(block)
            
            # Skip blocks that are too short or too long
            if len(block) < 10 or len(block) > 200:
                continue
            
            # Score based on address patterns
            pattern_score = 0
            for pattern in address_patterns:
                if re.search(pattern, block, re.IGNORECASE):
                    pattern_score += 2
            
            # Score based on address keywords (including Swedish)
            address_keywords = [
                'office', 'location', 'address', 'headquarters', 'visit us', 'find us',
                'besöksadress', 'adress', 'besök', 'kontor', 'lokal'
            ]
            keyword_score = sum(1 for keyword in address_keywords if keyword in block.lower())
            
            # Score based on structure
            structure_score = 0
            if 15 <= len(block) <= 150:
                structure_score += 1
            if block.count(',') >= 1:
                structure_score += 1
            if re.search(r'\d', block):
                structure_score += 1
            if re.search(r'\b\d{3}\s?\d{2}\b', block):  # Swedish postal code
                structure_score += 2
            
            total_score = pattern_score + keyword_score + structure_score
            
            if total_score > best_score and self.validate_address(block):
                best_score = total_score
                best_candidate = block
        
        return best_candidate
    
    def scrape_address(self, url):
        """Main function to scrape address"""
        print(f"\nScraping: {url}")
        
        # Get main page
        html = self.get_page(url)
        if not html:
            return {"error": "Failed to fetch page"}
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # First, try to find address using more specific selectors
        specific_address = self.extract_specific_address(soup)
        if specific_address:
            return {
                "address": specific_address,
                "source": "specific_selectors"
            }
        
        # Extract footer content
        footer_text = self.extract_footer_sections(soup)
        text_blocks = self.extract_address_blocks(footer_text)
        
        # Try to find best address in footer
        footer_address = self.find_best_address(text_blocks)
        if footer_address:
            return {
                "address": footer_address,
            }
        
        # If not found in footer, try entire page
        entire_page_text = soup.get_text(separator="\n", strip=True)
        entire_blocks = self.extract_address_blocks(entire_page_text)
        page_address = self.find_best_address(entire_blocks)
        
        if page_address:
            return {
                "address": page_address,
                "source": "entire_page"
            }
        
        # Try contact page as last resort
        contact_url = self.find_contact_page(url, soup)
        if contact_url and contact_url != url:
            print(f"📞 Trying contact page: {contact_url}")
            contact_html = self.get_page(contact_url)
            if contact_html:
                contact_soup = BeautifulSoup(contact_html, 'html.parser')
                contact_text = contact_soup.get_text(separator="\n", strip=True)
                contact_blocks = self.extract_address_blocks(contact_text)
                contact_address = self.find_best_address(contact_blocks)
                
                if contact_address:
                    return {
                        "address": contact_address,
                        "source": "contact_page"
                    }
        
        return {"error": "No valid address found"}
    
    def extract_specific_address(self, soup):
        """Try to extract address using more specific methods"""
        # Look for common address patterns in text
        address_patterns = [
            r'[A-Za-zåäöÅÄÖ\s]+\d+,\s*\d{3}\s?\d{2}\s+[A-Za-zåäöÅÄÖ\s]+',
            r'\d+\s+[A-Za-zåäöÅÄÖ\s]+,\s*\d{3}\s?\d{2}\s+[A-Za-zåäöÅÄÖ\s]+',
        ]
        
        text = soup.get_text()
        for pattern in address_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if self.validate_address(match):
                    return match
        
        return None
    
    def find_contact_page(self, base_url, soup):
        """Find contact page URL"""
        contact_keywords = ['contact', 'about', 'location', 'address', 'headquarters', 'kontakt', 'besök']
        
        for link in soup.find_all('a', href=True):
            link_text = link.get_text().lower()
            for keyword in contact_keywords:
                if keyword in link_text:
                    full_url = urljoin(base_url, link['href'])
                    if self.is_valid_url(full_url):
                        return full_url
        return None
    
    def is_valid_url(self, url):
        """Check if URL is valid"""
        try:
            result = urlparse(url)
            return bool(result.netloc and result.scheme)
        except:
            return False


def _address_cache_key(url: str) -> str:
    if not url:
        return ""
    return url.strip().rstrip('/')


def _address_result_to_string(address_result) -> str:
    if not address_result:
        return ""
    if isinstance(address_result, dict):
        primary = address_result.get('address')
        if primary:
            return str(primary).strip()
        candidates = address_result.get('candidates')
        if isinstance(candidates, list):
            for candidate in candidates:
                if candidate:
                    return str(candidate).strip()
        footer_preview = address_result.get('footer_preview')
        if isinstance(footer_preview, str) and footer_preview.strip():
            return footer_preview.strip().split('\n')[0]
        return ""
    if isinstance(address_result, str):
        return address_result.strip()
    return ""


def fetch_address_with_fallback(url: str):
    """Fetch address using Selenium scraper with fallback to legacy scraper."""
    cache_key = _address_cache_key(url)
    if cache_key and cache_key in _address_cache:
        return _address_cache[cache_key]

    selenium_scraper = None
    try:
        selenium_scraper = AddressScraper(headless=True)
        selenium_result = selenium_scraper.scrape_address(url)
        if selenium_result and isinstance(selenium_result, dict):
            if selenium_result.get('address'):
                if cache_key:
                    _address_cache[cache_key] = selenium_result
                return selenium_result
    except Exception as e:
        logging.warning(f"Selenium address scraping failed for {url}: {e}")
    finally:
        if selenium_scraper:
            try:
                selenium_scraper.close()
            except Exception:
                pass

    fallback_result = None
    try:
        fallback_scraper = ImprovedAddressScraper()
        fallback_result = fallback_scraper.scrape_address(url)
    except Exception as e:
        logging.warning(f"Fallback address scraping failed for {url}: {e}")
        fallback_result = {"error": f"Address scraping failed: {e}"}

    if cache_key:
        _address_cache[cache_key] = fallback_result
    return fallback_result

def cleanup_driver(driver):
    """Ensure WebDriver is properly closed"""
    try:
        if driver:
            driver.quit()
    except Exception as e:
        print(f"Error during WebDriver cleanup: {e}")

def get_webdriver():
    """Create and configure WebDriver with memory optimizations"""
    options = Options()
    options.add_argument('--headless')
    add_chrome_no_sandbox_if_needed(options)
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    
    # Memory optimizations
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--disable-notifications')
    options.add_argument('--disable-infobars')
    options.add_argument('--disable-browser-side-navigation')
    options.add_argument('--disable-features=VizDisplayCompositor')
    
    service = Service(executable_path=get_required_chromedriver_path())
    driver = webdriver.Chrome(service=service, options=options)
    atexit.register(cleanup_driver, driver)  # Ensure cleanup on exit
    return driver

def scrape_website_data(website_url=None):
    """
    Enhanced scraping function with anti-bot protection mechanisms and keyword extraction.
    If website_url is None, it will prompt for input.
    Returns the scraping result.
    """
    logger = logging.getLogger(__name__)
    cssutils.log.setLevel(logging.CRITICAL)  # Suppress cssutils warnings

    # Verbosity toggle via env
    _verbose = os.environ.get('SCRAPER_VERBOSE', '1').lower() not in ('0','false','no')
    
    # Simple mode toggle
    _simple_mode = os.environ.get('SCRAPER_SIMPLE', '0').lower() in ('1','true','yes')
    
    driver = None

    def get_random_user_agent():
        """Get a random realistic user agent"""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ]
        return random.choice(user_agents)

    def create_stealth_session():
        """Create a requests session with anti-bot protection"""
        session = requests.Session()
        
        # Set random user agent
        session.headers.update({
            'User-Agent': get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        })
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["HEAD", "GET", "OPTIONS"]),
            backoff_factor=1
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session


    def setup_stealth_driver():
        """Initialize and return a configured Selenium WebDriver with anti-bot measures"""
        options = webdriver.ChromeOptions()
        
        # Basic options
        options.add_argument('--headless=new')
        add_chrome_no_sandbox_if_needed(options)
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-software-rasterizer')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-browser-side-navigation')
        options.add_argument('--disable-infobars')
        options.add_argument('--disable-notifications')
        options.add_argument('--disable-popup-blocking')
        options.add_argument('--mute-audio')
        options.add_argument('--no-default-browser-check')
        options.add_argument('--no-first-run')
        options.add_argument('--safebrowsing-disable-auto-update')
        options.add_argument('--safebrowsing-disable-download-protection')
        options.add_argument('--start-maximized')
        options.add_argument(f'--user-agent={get_random_user_agent()}')
        
        # Set preferences
        prefs = {
            "intl.accept_languages": "en-US,en",
            "profile.default_content_setting_values": {
                "notifications": 2,
                "geolocation": 2,
                "media_stream": 2,
                "location": 2
            }
        }
        options.add_experimental_option("prefs", prefs)
        
        # Set Chrome binary location (same as colors.py)
        chrome_bin = os.environ.get('CHROME_BIN') or os.environ.get('CHROMIUM_BIN')
        if chrome_bin and os.path.exists(chrome_bin):
            options.binary_location = chrome_bin
            logger.info(f"Using Chrome binary from env: {chrome_bin}")
        else:
            # Try default Chrome locations
            default_chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]
            for chrome_path in default_chrome_paths:
                if os.path.exists(chrome_path):
                    options.binary_location = chrome_path
                    logger.info(f"Using Chrome binary: {chrome_path}")
                    break
        
        try:
            system_chromedriver = get_required_chromedriver_path()
            logger.info(f"Using configured ChromeDriver at: {system_chromedriver}")
            service = Service(executable_path=system_chromedriver)
            driver = webdriver.Chrome(service=service, options=options)
            
            # Execute stealth scripts
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})")
            driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']})")
            
            driver.set_page_load_timeout(30)
            driver.implicitly_wait(10)
            return driver
            
        except WebDriverException as e:
            logger.error(f"Failed to initialize WebDriver: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error initializing WebDriver: {str(e)}")
            return None

    def detect_anti_bot_measures(soup, response):
        """Detect common anti-bot protection measures"""
        indicators = {
            'cloudflare': False,
            'captcha': False,
            'blocked': False,
            'rate_limited': False,
            'javascript_required': False
        }
        
        # Check for Cloudflare
        if 'cloudflare' in response.text.lower() or 'checking your browser' in response.text.lower():
            indicators['cloudflare'] = True
        
        # Check for CAPTCHA
        captcha_keywords = ['captcha', 'recaptcha', 'verify you are human', 'robot check']
        if any(keyword in response.text.lower() for keyword in captcha_keywords):
            indicators['captcha'] = True
        
        # Check for blocking
        block_keywords = ['access denied', 'blocked', 'forbidden', 'not available in your region']
        if any(keyword in response.text.lower() for keyword in block_keywords):
            indicators['blocked'] = True
        
        # Check for rate limiting
        if response.status_code == 429 or 'rate limit' in response.text.lower():
            indicators['rate_limited'] = True
        
        # Check for JavaScript requirement
        if soup.find('noscript') or len(soup.find_all('script')) > 10:
            indicators['javascript_required'] = True
        
        return indicators   

    def is_js_rendered(soup):
        """Enhanced check if page appears to be JavaScript-rendered"""
        indicators = [
            len(soup.find_all('script')) > 5,
            bool(soup.find('noscript')),
            not soup.find('body') or not soup.find('body').text.strip(),
            bool(soup.find('meta', attrs={'name': 'generator', 'content': re.compile(r'react|angular|vue|next', re.I)})),
            bool(soup.find('div', {'id': 'root'})),
            bool(soup.find('div', {'id': 'app'})),
            bool(soup.find('div', {'ng-app': True})),
        ]
        return any(indicators)

    def get_title(soup):
        title = soup.title.string if soup.title else None
        if not title or title.strip() == '':
            og_title = soup.find('meta', property='og:title')
            if og_title and og_title.get('content', '').strip():
                return og_title['content'].strip()
            twitter_title = soup.find('meta', attrs={'name': 'twitter:title'})
            if twitter_title and twitter_title.get('content', '').strip():
                return twitter_title['content'].strip()
            return 'No title found'
        return title.strip()

    def get_meta_description(soup):
        meta = soup.find('meta', attrs={'name': 'description'})
        if meta and meta.get('content', '').strip():
            return meta['content'].strip()

        og_desc = soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content', '').strip():
            return og_desc['content'].strip()

        twitter_desc = soup.find('meta', attrs={'name': 'twitter:description'})
        if twitter_desc and twitter_desc.get('content', '').strip():
            return twitter_desc['content'].strip()

        paragraphs = [p.get_text().strip() for p in soup.find_all('p')]
        for p in paragraphs:
            if 50 < len(p) < 300:
                return p

        return 'No meta description found'

    # Color extraction functionality removed as requested

    # ----------------------------------------
    # WIX DETECTION AND FONT EXTRACTION
    # ----------------------------------------
    def is_wix_website(driver):
        """Detect if the website is built with Wix"""
        try:
            # Check for Wix-specific indicators
            wix_indicators = [
                "wix.com",
                "wixstatic.com",
                "static.parastorage.com",
                "wix-code",
                "wix-code-sdk",
                "wix-site-sdk"
            ]
            
            # Check page source
            page_source = driver.page_source.lower()
            for indicator in wix_indicators:
                if indicator in page_source:
                    return True
            
            # Check for Wix-specific meta tags or scripts
            wix_check_script = """
            // Check for Wix-specific global variables
            if (typeof window.wixBiSession !== 'undefined' || 
                typeof window.wixCode !== 'undefined' ||
                typeof window.wixSite !== 'undefined') {
                return true;
            }
            
            // Check for Wix-specific class names
            if (document.querySelector('[class*="wix"], [id*="wix"]')) {
                return true;
            }
            
            // Check for Wix scripts
            const scripts = Array.from(document.querySelectorAll('script[src]'));
            for (const script of scripts) {
                if (script.src.includes('wix') || script.src.includes('parastorage')) {
                    return true;
                }
            }
            
            return false;
            """
            return driver.execute_script(wix_check_script) or False
        except Exception:
            return False

    def extract_real_font_from_alias(font_family):
        """
        Extract real font name from Wix alias
        Example:
        wf_xxxx_orig_comfortaa_bold  -> Comfortaa
        wf_xxxx_orig-lato-regular    -> Lato
        """
        font_family = font_family.lower()
        match = re.search(r'orig[_-]([a-z0-9]+)', font_family)
        if match:
            return match.group(1).replace("-", " ").title()
        return None

    def detect_wix_fonts(driver):
        """Wix-specific font detection logic from fonts_test.py"""
        try:
            # Allow Wix hydration + font loading
            time.sleep(2)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
            
            script = r"""
            const elements = document.querySelectorAll(
                'h1,h2,h3,h4,h5,h6,p,span,div,button,a'
            );
            
            const fonts = new Set();
            
            elements.forEach(el => {
                if (!el.textContent || el.textContent.trim().length < 3) return;
                
                const cs = window.getComputedStyle(el);
                if (!cs || !cs.fontFamily) return;
                
                fonts.add(cs.fontFamily);
            });
            
            return Array.from(fonts);
            """
            font_families = driver.execute_script(script)
            
            real_fonts = set()
            if font_families:
                for family in font_families:
                    # Split fallback stack
                    for f in family.split(","):
                        f = f.strip().replace('"', '').replace("'", "")
                        real = extract_real_font_from_alias(f)
                        if real:
                            real_fonts.add(real)
            
            return sorted(list(real_fonts)) if real_fonts else []
        except Exception as e:
            print(f"Error in detect_wix_fonts: {e}")
            return []

    def extract_wix_element_fonts(driver):
        """Extract element-specific fonts using Wix logic"""
        try:
            wix_fonts = detect_wix_fonts(driver)
            if not wix_fonts:
                return {}
            
            # Convert Wix font list to element-specific format
            # Since Wix logic doesn't distinguish by element, we'll assign to common elements
            element_fonts = {}
            for font in wix_fonts:
                # Assign to headings and paragraphs
                if 'h1' not in element_fonts:
                    element_fonts['h1'] = []
                if 'paragraph' not in element_fonts:
                    element_fonts['paragraph'] = []
                element_fonts['h1'].append(font)
                element_fonts['paragraph'].append(font)
            
            return element_fonts
        except Exception as e:
            print(f"Error in extract_wix_element_fonts: {e}")
            return {}

    def extract_element_specific_fonts(driver):
        """Extract fonts for headings and paragraphs with enhanced error handling"""
        try:
            # First, check if we can execute JavaScript
            try:
                test_js = driver.execute_script('return typeof document !== "undefined";')
                if not test_js:
                    return {}
            except Exception:
                return {}
                
            # Check if it's a Wix website
            if is_wix_website(driver):
                # Try Wix-specific font extraction
                wix_fonts = extract_wix_element_fonts(driver)
                # If Wix logic found fonts, return them
                if wix_fonts:
                    return wix_fonts
                # If no fonts found with Wix logic, fall back to old logic
                print("No fonts found with Wix logic, falling back to standard extraction")
            
            # Standard font extraction (old logic)
            font_script = """
            var elementFonts = {};
            
            // Define only headings and paragraphs
            var elementSelectors = {
                'h1': 'h1',
                'h2': 'h2', 
                'h3': 'h3',
                'h4': 'h4',
                'h5': 'h5',
                'h6': 'h6',
                'paragraph': 'p'
            };
            
            // Function to clean font family name
            function cleanFontFamily(fontFamily) {
                if (!fontFamily) {
                    return null;
                }
                // Remove quotes and get first font in the stack
                return fontFamily.replace(/['"]/g, '').split(',')[0].trim();
            }
            
            // Get fonts for each element type
            Object.keys(elementSelectors).forEach(function(elementName) {
                var selector = elementSelectors[elementName];
                var elements = document.querySelectorAll(selector);
                var fonts = new Set();
                
                // Get computed styles for each element of this type
                for (var i = 0; i < Math.min(elements.length, 12); i++) {
                    try {
                        var element = elements[i];
                        var styles = window.getComputedStyle(element);
                        var fontFamily = styles.fontFamily;
                        var cleanedFont = cleanFontFamily(fontFamily);
                        if (cleanedFont && cleanedFont !== 'inherit') {
                            fonts.add(cleanedFont);
                        }
                    } catch (e) {
                        // Silently handle errors
                    }
                }
                
                // Convert Set to Array and store only if fonts found
                if (fonts.size > 0) {
                    elementFonts[elementName] = Array.from(fonts);
                }
            });
            
            return elementFonts;
            """
            
            # Execute the script
            try:
                element_fonts = driver.execute_script(font_script)
                
                if not element_fonts:
                    return {}
                return element_fonts
                
            except Exception as script_error:
                # Try fallback method if the main one fails
                try:
                    return extract_fonts_fallback(driver)
                except Exception:
                    return {}
            
        except Exception as e:
            print(f"Error in extract_element_specific_fonts: {str(e)}")
            import traceback
            print("Stack trace:", traceback.format_exc())
            return {}

    def extract_fonts_fallback(driver):
        """Fallback font detection method using a different approach"""
        try:
            # Try to get all computed styles
            fonts_script = """
            var elements = document.querySelectorAll('h1, h2, h3, h4, h5, h6, p');
            var fontMap = {
                'h1': new Set(),
                'h2': new Set(),
                'h3': new Set(),
                'h4': new Set(),
                'h5': new Set(),
                'h6': new Set(),
                'p': new Set()
            };
            
            elements.forEach(el => {
                var tag = el.tagName.toLowerCase();
                if (tag in fontMap) {
                    var font = window.getComputedStyle(el).fontFamily;
                    if (font && font !== 'inherit') {
                        var cleanFont = font.replace(/['"]/g, '').split(',')[0].trim();
                        if (cleanFont) {
                            fontMap[tag].add(cleanFont);
                        }
                    }
                }
            });
            
            // Convert Sets to Arrays
            var result = {};
            for (var tag in fontMap) {
                if (fontMap[tag].size > 0) {
                    result[tag] = Array.from(fontMap[tag]);
                }
            }
            return result;
            """
            
            return driver.execute_script(fonts_script) or {}
        except Exception as e:
            print(f"Fallback font detection failed: {e}")
            return {}

    def extract_fonts(driver):
        """Extract primary font families used on the page (backward compatibility)"""
        try:
            # Check if it's a Wix website
            if is_wix_website(driver):
                # Try Wix-specific font extraction
                wix_fonts = detect_wix_fonts(driver)
                # If Wix logic found fonts, return them
                if wix_fonts:
                    return wix_fonts
                # If no fonts found with Wix logic, fall back to old logic
                print("No fonts found with Wix logic, falling back to standard extraction")
            
            # Standard font extraction (old logic)
            font_script = """
var fonts = new Set();
var elements = document.querySelectorAll('h1, h2, h3, h4, h5, h6, p, span, div, a');
elements.forEach(el => {
    var styles = window.getComputedStyle(el);
    fonts.add(styles.fontFamily);
});
return Array.from(fonts).slice(0, 10);
"""
            raw_fonts = driver.execute_script(font_script)
            return clean_font_families(raw_fonts)
        except Exception as e:
            print(f"Error extracting fonts: {e}")
            return []

    def clean_font_families(fonts):
        """Clean and deduplicate font family names"""
        cleaned_fonts = []
        for font in fonts:
            font = font.replace('"', '').replace("'", '')
            first_font = font.split(',')[0].strip()
            if first_font and first_font not in cleaned_fonts:
                cleaned_fonts.append(first_font)
        return cleaned_fonts[:5]

    def get_clean_text(soup):
        if soup is None:
            return ""
            
        try:
            # Create a copy to avoid modifying the original
            soup = BeautifulSoup(str(soup), 'html.parser')
            
            # Remove non-content elements
            for element in soup(['script', 'style', 'nav', 'footer', 'header',
                             'iframe', 'noscript', 'svg', 'form', 'button']):
                if element:
                    element.decompose()
            # Remove cookie / consent banners
            cookie_keywords = ['cookie', 'gdpr', 'consent', 'privacy', 'tracking']
            for div in soup.find_all(True):  # search all tags
                try:
                    id_class = ' '.join([
                        div.get('id') or '',
                        ' '.join(div.get('class') or [])
                    ]).lower()
                    if any(kw in id_class for kw in cookie_keywords):
                        div.decompose()
                except Exception as e:
                    continue

            # Clean text
            text = re.sub(r'\s+', ' ', soup.get_text(separator=' ', strip=True))
            return text[:10000] if text else ""
            
        except Exception as e:
            logger.warning(f"Error in get_clean_text: {e}")
            return ""

    def extract_page_info(soup, base_url, status_code, anti_bot_indicators=None, driver=None):
        # Extract element-specific fonts if driver is available
        element_fonts = {}
        general_fonts = []
        
        if driver:
            element_fonts = extract_element_specific_fonts(driver)
            general_fonts = extract_fonts(driver)  # Keep for backward compatibility
        
        # Extract clean text for keyword extraction
        clean_text_content = clean_text(soup)
        
        # Extract keywords
        keywords = extract_keywords(clean_text_content)
        
        # Create address scraper instance and try to extract address
        address_result = fetch_address_with_fallback(base_url)
        address_text = _address_result_to_string(address_result)
        
        return {
            'url': base_url,
            'status_code': status_code,
            'title': get_title(soup),
            'meta_description': get_meta_description(soup),
            'theme_colors': {'all_colors': []},  # Color extraction disabled
            'fonts': general_fonts,  # General fonts (backward compatibility)
            'element_fonts': element_fonts,  # New element-specific fonts
            'text_content': get_clean_text(soup),
            'keywords': keywords,  # Extracted keywords
            'address': address_text,
            'address_details': address_result,
            'anti_bot_indicators': anti_bot_indicators or {}
        }

    def normalize_url_with_path(url):
        """
        Normalize URL while preserving the path (e.g., country-specific paths like /se, /no, /dk).
        Returns a tuple of (base_url_with_path, url_candidates)
        """
        input_url = url.strip()
        
        # Ensure scheme exists
        if not re.match(r'^https?://', input_url, re.IGNORECASE):
            input_url = 'https://' + input_url
        
        # Parse the URL to extract components
        parsed = urlparse(input_url)
        host = parsed.netloc
        path = parsed.path
        query = parsed.query
        fragment = parsed.fragment
        
        # Build the path string (preserve query and fragment if they exist)
        full_path = path
        if query:
            full_path += f"?{query}"
        if fragment:
            full_path += f"#{fragment}"
        
        # Handle www prefix
        naked = host[4:] if host.lower().startswith('www.') else host
        
        # Generate URL candidates with different scheme/www combinations
        # while preserving the path
        candidates = []
        for scheme in ('https', 'http'):
            for h in (naked, f"www.{naked}"):
                candidate = f"{scheme}://{h}{full_path}"
                candidates.append(candidate)
        
        # Remove duplicates while preserving order
        seen = set()
        candidates = [c for c in candidates if not (c in seen or seen.add(c))]
        
        return candidates

    def scrape_main_page_enhanced(url):
        """Enhanced main page scraping with multiple fallback strategies"""
        try:
            # Generate URL candidates that preserve the path
            candidates = normalize_url_with_path(url)

            last_error = None
            for candidate in candidates:
                try:
                    parsed_url = urlparse(candidate)
                    # Preserve the full path in base_url
                    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
                    if parsed_url.query:
                        base_url += f"?{parsed_url.query}"
                    # Silently attempt to scrape

                    try:
                        # Prefer a normal HTTP fetch. It is faster, avoids
                        # ChromeDriver downloads, and is enough for many sites.
                        session = create_stealth_session()
                        response = safe_get(session, base_url, timeout=15)
                        if 'text/html' not in response.headers.get('content-type', '').lower():
                            raise Exception('Non-HTML content')
                        soup = BeautifulSoup(response.text, 'html.parser')
                        anti_bot_indicators = detect_anti_bot_measures(soup, response)
                        if response.status_code >= 400:
                            if response.status_code in (401, 403, 429):
                                page = extract_page_info(
                                    soup,
                                    base_url,
                                    response.status_code,
                                    anti_bot_indicators,
                                )
                                page['scrape_warning'] = (
                                    f"Website returned HTTP {response.status_code}; "
                                    "partial anti-bot/blocked page data returned."
                                )
                                return page
                            response.raise_for_status()
                        page = extract_page_info(soup, base_url, response.status_code, anti_bot_indicators)
                        return page
                    except Exception as e:
                        if _simple_mode:
                            print(f"   Simple Mode failed: {str(e)}")
                            if os.environ.get('SCRAPER_SIMPLE_STRICT', '0') in ('1','true','yes'):
                                raise

                    # Strategy 3: Selenium
                    try:
                        try:
                            get_required_chromedriver_path()
                        except Exception as driver_config_error:
                            last_error = f"Selenium unavailable: {driver_config_error}"
                            continue

                        # Add small delay and retry logic
                        driver = None
                        max_retries = 2
                        for attempt in range(max_retries):
                            try:
                                driver = setup_stealth_driver()
                                if driver:
                                    break
                            except Exception as e:
                                if attempt < max_retries - 1:
                                    time.sleep(2)
                                else:
                                    raise
                        
                        if driver:
                            safe_driver_get(driver, base_url)
                            WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located((By.TAG_NAME, "body"))
                            )
                            soup = BeautifulSoup(driver.page_source, 'html.parser')
                            
                            # Extract both element-specific and general fonts
                            element_fonts = extract_element_specific_fonts(driver)
                            general_fonts = extract_fonts(driver)

                            # Extract clean text for keyword extraction
                            clean_text_content = clean_text(soup)
                            keywords = extract_keywords(clean_text_content)

                            # Create address scraper instance and try to extract address
                            address_result = fetch_address_with_fallback(base_url)
                            address_text = _address_result_to_string(address_result)

                            # Color extraction functionality removed as requested
                            theme_data = None
                            page = {
                                'url': base_url,
                                'status_code': 200,
                                'title': get_title(soup),
                                'meta_description': get_meta_description(soup),
                                'theme_colors': {
                                    'all_colors': []
                                },
                                'fonts': general_fonts,  # General fonts (backward compatibility)
                                'element_fonts': element_fonts,  # New element-specific fonts
                                'text_content': get_clean_text(soup),
                                'keywords': keywords,  # Extracted keywords
                                'address': address_text,
                                'address_details': address_result,
                                'anti_bot_indicators': {'javascript_required': True}
                            }

                            driver.quit()
                            return page
                        else:
                            raise Exception('Failed to initialize WebDriver')
                    except Exception as e:
                        if driver:
                            try:
                                driver.quit()
                            except:
                                pass
                        pass  # Selenium failed

                    last_error = 'All strategies failed for ' + base_url
                except Exception as e:
                    last_error = str(e)
                    continue

            raise Exception(last_error or 'All scraping strategies failed')

        except Exception as e:
            return {'error': str(e)}

    def print_results(result):
        # Silent processing - no verbose output
        pass

    # Main execution logic
    try:
        if website_url is None:
            website_url = input("Enter website URL (e.g., example.com): ").strip()
        
        if not website_url:
            return None

        else:
            result = scrape_main_page_enhanced(website_url)
            return result
    except KeyboardInterrupt:
        return None
    except Exception as e:
        return None

# Keep the original scrape_main_page function for backward compatibility
def scrape_main_page(url):
    """Backward compatibility function that calls the main scraping function"""
    return scrape_website_data(url)

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        url = sys.argv[1].strip()
    else:
        url = input("Enter website URL (e.g., example.com): ").strip()
    
    result = scrape_website_data(url)
    
    # Clean up the result to only include the necessary data
    if result and 'address' in result and 'address' in result['address']:
        result['address'] = result['address']['address']
    
    # Print the result as JSON
    if result:
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))



