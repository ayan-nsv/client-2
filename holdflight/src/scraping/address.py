# Placeholder file - Copy your holdflight/src/scraping/address.py content here
# Address extraction

"""
improved_footer_address_scraper.py
Selenium-powered footer address scraper with JSON-LD, map-link extraction,
improved footer discovery, and international-friendly address detection.

Requirements:
    pip install selenium beautifulsoup4 requests

Usage:
    from improved_footer_address_scraper import AddressScraper
    
    scraper = AddressScraper(headless=True)
    result = scraper.scrape_address("https://example.com")
    scraper.close()
    
    # Or use as context manager:
    with AddressScraper() as scraper:
        result = scraper.scrape_address("https://example.com")
"""

import os
import re
import json
import time
from urllib.parse import urljoin, urlparse
import requests

from bs4 import BeautifulSoup

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.common.exceptions import WebDriverException, TimeoutException
from holdflight.src.utils.chrome_options import (
    add_chrome_no_sandbox_if_needed,
    get_required_chromedriver_path,
    safe_driver_get,
    safe_get,
)


class AddressScraper:
    """
    Complete address scraper class with all functionality encapsulated.
    Can be used standalone or as a context manager.
    """
    
    # Configuration constants
    HEADLESS = True
    WAIT_SHORT = 1.0
    WAIT_LONG = 2.0
    PAGE_LOAD_TIMEOUT = 20
    SCROLL_PAUSE = 0.6
    MAX_SCROLL_STEPS = 30
    
    # Address patterns and keywords
    ADDRESS_PATTERNS = [
        r'\d+\s+[A-Za-z0-9\.\- ]+\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Plaza|Square|Sq|Terrace|Terr)\b.*',
        r'[A-Za-zÀ-ÖØ-öø-ÿ\-\s]+(?:\s|,)\s*\d+[A-Za-z0-9\/\-]*[,]*\s*\d{2,5}\s*[A-Za-zÀ-ÖØ-öø-ÿ]*',
        r'\b\d{3}\s?\d{0,4}\b\s*[A-Za-zÀ-ÖØ-öø-ÿ\-\s]+\b',
        r'\b(P\.?O\.?\s?Box|Postfach|PO Box|PB|P\.Box)\b[\s:\-]?\d+',
        r'[A-Za-zÀ-ÖØ-öø-ÿ\-\s]+\s+\d{1,5}[A-Za-z\-]?\s*,\s*[A-Za-zÀ-ÖØ-öø-ÿ\-\s]+\b',
        r'\b-?\d{1,3}\.\d+,\s*-?\d{1,3}\.\d+\b'
    ]
    
    ADDRESS_KEYWORDS = [
        'address','adresse','dirección','endereço','endereco','indirizzo','地址','地址：','kontakt','kontor',
        'besöksadress','postal','postcode','zip','postnummer','postbox','p.o.','po box','street','st','straat',
        'gata','väg','vägen','väg','platz','straße','straße','via','boulevard','avenue','avenida','cidade','city','county',
        'state','region','república','country'
    ]
    
    def __init__(self, headless=None):
        """Initialize the scraper with a webdriver instance."""
        if headless is None:
            headless = self.HEADLESS
        self.headless = headless
        self.driver = self._make_driver()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
    
    def _make_driver(self):
        """Create and configure the webdriver."""
        opts = Options()
        if self.headless:
            opts.add_argument("--headless=new")
        add_chrome_no_sandbox_if_needed(opts)
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1600,1200")
        opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        chrome_binary = os.environ.get("CHROME_BIN")
        if chrome_binary:
            opts.binary_location = chrome_binary
        
        try:
            service = ChromeService(executable_path=get_required_chromedriver_path())
            driver = webdriver.Chrome(service=service, options=opts)
            driver.set_page_load_timeout(self.PAGE_LOAD_TIMEOUT)
            return driver
        except WebDriverException as e:
            raise RuntimeError("Failed to create webdriver. Make sure Chrome is installed.") from e
    
    def _safe_get(self, url):
        """Load page with retries; returns page source or None."""
        try:
            safe_driver_get(self.driver, url)
        except TimeoutException:
            pass
        except Exception as e:
            print(f"Error loading {url}: {e}")
            return None

        last_height = self.driver.execute_script("return document.body.scrollHeight")
        steps = 0
        while steps < self.MAX_SCROLL_STEPS:
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(self.SCROLL_PAUSE)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            steps += 1

        time.sleep(self.WAIT_SHORT)
        return self.driver.page_source
    
    def _extract_json_ld_addresses(self, soup):
        """Extract structured addresses from application/ld+json blocks."""
        results = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                raw = script.string
                if not raw:
                    continue
                data = json.loads(raw.strip())
            except Exception:
                try:
                    json_text = re.search(r'\{.*\}', script.string, flags=re.S)
                    if json_text:
                        data = json.loads(json_text.group(0))
                    else:
                        continue
                except Exception:
                    continue

            def gather(obj):
                if not obj:
                    return
                if isinstance(obj, dict):
                    if 'postalAddress' in obj and isinstance(obj['postalAddress'], dict):
                        results.append(obj['postalAddress'])
                    if 'address' in obj:
                        results.append(obj['address'])
                    if all(k in obj for k in ('streetAddress','postalCode','addressLocality')):
                        results.append({
                            'streetAddress': obj.get('streetAddress'),
                            'postalCode': obj.get('postalCode'),
                            'addressLocality': obj.get('addressLocality'),
                            'addressCountry': obj.get('addressCountry')
                        })
                    for v in obj.values():
                        gather(v)
                elif isinstance(obj, list):
                    for item in obj:
                        gather(item)

            gather(data)
        
        normalized = []
        for r in results:
            if isinstance(r, dict):
                parts = []
                for key in ('streetAddress','postOfficeBoxNumber','postalCode','addressLocality','addressRegion','addressCountry'):
                    val = r.get(key) if isinstance(r.get(key), str) else None
                    if val:
                        parts.append(val.strip())
                if parts:
                    normalized.append(", ".join(parts))
                else:
                    values = [str(v).strip() for v in r.values() if isinstance(v, str) and v.strip()]
                    if values:
                        normalized.append(", ".join(values))
            elif isinstance(r, str):
                normalized.append(r.strip())
        return list(dict.fromkeys(normalized))
    
    def _find_footer_candidates(self, soup):
        """Return a list of BeautifulSoup elements that are good footer candidates."""
        candidates = []
        
        for tag in soup.find_all('footer'):
            candidates.append(tag)

        for tag in soup.find_all(attrs={"role": "contentinfo"}):
            candidates.append(tag)

        footer_like = re.compile(r'(footer|site-footer|main-footer|footer-area|bottom|page-footer|colophon)', re.I)
        for tag in soup.find_all(True, {"id": footer_like}):
            candidates.append(tag)
        for tag in soup.find_all(True, {"class": footer_like}):
            candidates.append(tag)

        body = soup.body
        if body:
            children = [c for c in body.find_all(recursive=False) if getattr(c, 'name', None)]
            tail = children[-6:] if children else []
            for t in tail:
                candidates.append(t)

        seen = set()
        filtered = []
        for c in candidates:
            if c in seen:
                continue
            filtered.append(c)
            seen.add(c)
        return filtered
    
    def _find_map_links(self, soup, base_url):
        """Find map links in the page."""
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if any(domain in href for domain in ['google.com/maps', 'goo.gl/maps', 'bing.com/maps', 'maps.apple.com', 'openstreetmap.org', 'maps.google']):
                links.append(urljoin(base_url, href))
        
        for iframe in soup.find_all('iframe', src=True):
            src = iframe['src']
            if 'google.com/maps' in src or 'maps.google' in src or 'openstreetmap.org' in src:
                links.append(urljoin(base_url, src))
        return list(dict.fromkeys(links))
    
    def _extract_text_blocks_from_element(self, elem):
        """Extract lines of text from a BeautifulSoup element."""
        text = elem.get_text(separator="\n", strip=True)
        text = re.sub(r'\t+', ' ', text)
        text = re.sub(r'\r', '\n', text)
        text = re.sub(r'\n\s*\n+', '\n', text)
        lines = [l.strip() for l in text.splitlines() if l.strip() != ""]
        
        merged = []
        buffer = []
        for line in lines:
            buffer.append(line)
            if re.match(r'^(contact|phone|tel|opening|hours|email|follow|social)', line.strip(), re.I):
                if buffer:
                    merged.append("\n".join(buffer).strip())
                    buffer = []
            else:
                if len(buffer) > 6:
                    merged.append("\n".join(buffer).strip())
                    buffer = []
        if buffer:
            merged.append("\n".join(buffer).strip())
        return merged
    
    def _block_looks_like_address(self, block):
        """Check if a text block looks like an address."""
        b = block.lower()
        if any(keyword in b for keyword in self.ADDRESS_KEYWORDS) and re.search(r'\d', block):
            return True
        
        for patt in self.ADDRESS_PATTERNS:
            if re.search(patt, block, re.I):
                return True
        
        if re.search(r'\b\d{3}\s?\d{0,4}\b', block) and re.search(r'[A-Za-zÀ-ÖØ-öø-ÿ]', block):
            return True
        
        if re.search(r'\d', block) and any(k in b for k in ['city','town','street','st','gata','väg','straße','via','addr']):
            return True
        return False
    
    def _validate_candidate(self, block):
        """Loose validation: allow a broad set of possible address shapes."""
        text = block.strip()
        if len(text) < 6:
            return False
        
        if len(text.split()) < 2:
            return False
        
        if not (re.search(r'\d', text) or re.search(r'\b(P\.?O\.?\s?Box|Postfach|PO Box|POB)\b', text, re.I) or re.search(r'-?\d+\.\d+,\s*-?\d+\.\d+', text)):
            if not any(k in text.lower() for k in self.ADDRESS_KEYWORDS):
                return False
        
        if len(text) > 400:
            return False
        return True
    
    def _score_address(self, block):
        """Score heuristics to choose the best candidate among many."""
        score = 0
        text = block.lower()
        
        for k in self.ADDRESS_KEYWORDS:
            if k in text:
                score += 2
        
        if re.search(r'\b\d{3}\s?\d{0,4}\b', text):
            score += 3
        if re.search(r'\d', text):
            score += 1
        
        if text.count(',') >= 1:
            score += 1
        
        if re.search(r'\b(street|road|avenue|gata|väg|platz|via|straße|indirizzo)\b', text):
            score += 1
        return score
    
    def is_valid_url(self, url):
        """Check if URL is valid."""
        try:
            parsed = urlparse(url)
            return bool(parsed.scheme and parsed.netloc)
        except:
            return False
    
    def _find_contact_page(self, base_url, soup):
        """Search anchor text & hrefs for contact/about/location keywords."""
        contact_keywords = ['contact','kontakt','about','om','contact-us','kontakta','kontakt','location','locations','address','kontaktuppgifter','adress','kontakt']
        for a in soup.find_all('a', href=True):
            txt = (a.get_text() or "").lower()
            href = a['href'].lower()
            if any(k in txt for k in contact_keywords) or any(k in href for k in contact_keywords):
                try:
                    candidate = urljoin(base_url, a['href'])
                    if self.is_valid_url(candidate):
                        return candidate
                except Exception:
                    continue
        return None
    
    def scrape_address(self, url):
        """
        Main method to scrape address from a given URL.
        
        Args:
            url (str): The URL to scrape
            
        Returns:
            dict: Result dictionary with address or error information
        """
        print(f"\nScraping: {url}")
        page_source = self._safe_get(url)
        if not page_source:
            return {"error": "Failed to fetch page"}

        soup = BeautifulSoup(page_source, 'html.parser')

        # 1) Try JSON-LD first (structured data)
        json_addresses = self._extract_json_ld_addresses(soup)
        if json_addresses:
            for addr in json_addresses:
                if self._validate_candidate(addr):
                    return {"address": addr, "source": "json-ld", "candidates": json_addresses}

        # 2) Gather footer candidates
        footer_elems = self._find_footer_candidates(soup)
        all_candidates = []

        footer_text = ""
        map_links = []
        for fe in footer_elems:
            footer_text += "\n---FOOTER-ELEM-START---\n" + (fe.get_text(separator="\n", strip=True) or "")
            footer_text += "\n---FOOTER-ELEM-END---\n"
            map_links.extend(self._find_map_links(fe, url))
            blocks = self._extract_text_blocks_from_element(fe)
            for b in blocks:
                if self._block_looks_like_address(b) or any(k in b.lower() for k in self.ADDRESS_KEYWORDS):
                    all_candidates.append({"block": b, "source": "footer"})
        map_links = list(dict.fromkeys(map_links))

        # 3) If no footer found or candidates empty, scan entire page
        if not all_candidates:
            page_blocks = self._extract_text_blocks_from_element(soup)
            for b in page_blocks:
                if self._block_looks_like_address(b):
                    all_candidates.append({"block": b, "source": "entire_page"})

        # 4) Evaluate map links
        map_extracts = []
        for ml in map_links:
            try:
                resp = safe_get(requests, ml, timeout=6, headers={"User-Agent":"Mozilla/5.0"})
                if resp.status_code == 200:
                    m_soup = BeautifulSoup(resp.text, 'html.parser')
                    title = (m_soup.title.string or "").strip() if m_soup.title else ""
                    if title:
                        map_extracts.append(title)
                    meta_desc = m_soup.find('meta', {"property": "og:description"})
                    if meta_desc and meta_desc.get('content'):
                        map_extracts.append(meta_desc.get('content').strip())
            except Exception:
                continue
        
        for me in map_extracts:
            if self._validate_candidate(me):
                all_candidates.append({"block": me, "source": "map_link"})

        # 5) Score & pick best
        scored = []
        for c in all_candidates:
            block = c['block']
            if not self._validate_candidate(block):
                continue
            s = self._score_address(block)
            scored.append((s, block, c['source']))
        scored.sort(reverse=True, key=lambda x: x[0])

        if scored:
            best = scored[0]
            return {"address": best[1], "score": best[0], "source": best[2], "footer_preview": footer_text[:1000]}
        
        # 6) fallback: contact page
        contact_url = self._find_contact_page(url, soup)
        if contact_url and contact_url != url:
            print(f"📞 Trying contact page: {contact_url}")
            contact_html = self._safe_get(contact_url)
            if contact_html:
                contact_soup = BeautifulSoup(contact_html, 'html.parser')
                contact_json_addresses = self._extract_json_ld_addresses(contact_soup)
                if contact_json_addresses:
                    for addr in contact_json_addresses:
                        if self._validate_candidate(addr):
                            return {"address": addr, "source": "contact-json-ld"}
                
                contact_blocks = self._extract_text_blocks_from_element(contact_soup)
                contact_candidates = []
                for b in contact_blocks:
                    if self._block_looks_like_address(b):
                        contact_candidates.append(b)
                
                scored_contact = []
                for b in contact_candidates:
                    if not self._validate_candidate(b):
                        continue
                    scored_contact.append((self._score_address(b), b))
                scored_contact.sort(reverse=True, key=lambda x: x[0])
                if scored_contact:
                    return {"address": scored_contact[0][1], "score": scored_contact[0][0], "source": "contact_page"}
        
        # 7) nothing found
        return {"error": "No valid address found", "footer_preview": footer_text[:1000], "map_links": map_links}
    
    def close(self):
        """Close the webdriver."""
        try:
            self.driver.quit()
        except Exception:
            pass


# ----------------------------
# Main execution with user input
# ----------------------------
if __name__ == "__main__":
    scraper = AddressScraper(headless=True)
    try:
        print("=" * 60)
        print("Address Scraper - Enter URLs to scrape")
        print("=" * 60)
        print("\nEnter website URLs (one per line)")
        print("Enter 'done' or press Ctrl+C when finished\n")
        
        while True:
            try:
                url = input("Enter URL: ").strip()
                
                if url.lower() == 'done':
                    break
                
                if not url:
                    continue
                
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url
                
                if not scraper.is_valid_url(url):
                    print("Invalid URL format. Please try again.\n")
                    continue
                
                res = scraper.scrape_address(url)
                
                if "address" in res:
                    print(f"Found: {res['address']}")
                    print(f"   Source: {res.get('source')}, Score: {res.get('score')}\n")
                else:
                    print(f"No address found for {url}")
                    if res.get("footer_preview"):
                        preview = res["footer_preview"]
                        print("Footer preview (first 400 chars):")
                        print(preview[:400] + ("..." if len(preview) > 400 else ""))
                    if res.get("map_links"):
                        print("Map links found:", res["map_links"])
                    print()
                
                time.sleep(1.2)
                
            except KeyboardInterrupt:
                print("\n\nExiting...")
                break
            except Exception as e:
                print(f"Error processing URL: {e}\n")
                
    finally:
        scraper.close()
        print("\nScraper closed. Goodbye!")




