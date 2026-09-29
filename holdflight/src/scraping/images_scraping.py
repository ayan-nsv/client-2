# Placeholder file - Copy your holdflight/src/scraping/images_scraping.py content here
# Image scraping




import io
import time
import re
import requests
from PIL import Image
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import langdetect
from langdetect import detect_langs

# After this many images pass validation, stop calling get_image_info on the rest (large pages stay fast).
MAX_VALID_IMAGES_BEFORE_STOP = 20


def detect_website_language(url):
    """
    Detect the primary language of a website with enhanced detection
    
    Args:
        url: Website URL
        
    Returns:
        str: Two-letter language code (e.g., 'en', 'sv')
    """
    # Enhanced headers to mimic a real browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,sv;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'DNT': '1'
    }
    
    try:
        # First try with enhanced headers
        response = safe_get(requests, url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()
        
        # Check content type
        content_type = response.headers.get('content-type', '').lower()
        if 'text/html' not in content_type:
            print(f"⚠️ Unexpected content type: {content_type}")
            return 'en'  # Default to English
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Check HTML lang attribute first
        if soup.html and soup.html.get('lang'):
            lang = soup.html.get('lang').split('-')[0].lower()
            if len(lang) == 2:  # Valid language code
                print(f"🌐 Detected language from HTML lang: {lang}")
                return lang
        
        # If no lang attribute, try to detect from content
        text = ''
        # Get title
        if soup.title and soup.title.string:
            text += soup.title.string + ' '
        
        # Get meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            text += meta_desc.get('content') + ' '
        
        # Get main content (first 1000 chars for better detection)
        body = soup.find('body')
        if body:
            # Try to find main content area first
            main_content = body.find(['main', 'article', 'div'], class_=lambda x: x and any(cls in (x or '').lower() for cls in ['content', 'main', 'article']))
            content_source = main_content if main_content else body
            text += ' '.join(content_source.stripped_strings)[:1000]
        
        if text:
            # Clean up text (remove extra whitespace, special chars)
            text = ' '.join(text.split())
            detected = detect_langs(text)
            if detected:
                print(f"🌐 Detected language from content: {detected[0]}")
                return detected[0].lang
                
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Request error detecting language: {str(e)}")
    except Exception as e:
        print(f"⚠️ Error in language detection: {str(e)}")
    
    # As a last resort, check the domain for country code
    if '.se/' in url or '.se ' in url or url.endswith('.se'):
        print("🌐 Assuming Swedish based on .se domain")
        return 'sv'
        
    # Default to English if all else fails
    print("⚠️ Could not detect language, defaulting to English")
    return 'en'
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from urllib.parse import urljoin
from holdflight.src.utils.chrome_options import (
    add_chrome_no_sandbox_if_needed,
    get_required_chromedriver_path,
    safe_driver_get,
    safe_get,
)

def get_driver():
    options = Options()
    options.add_argument("--headless=new")
    add_chrome_no_sandbox_if_needed(options)
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    service = Service(executable_path=get_required_chromedriver_path())
    return webdriver.Chrome(service=service, options=options)

def fetch_images_with_selenium(url):
    print("🤖 Using Selenium (JS rendering)...")
    driver = get_driver()
    try:
        safe_driver_get(driver, url)
        # Wait for page to load completely
        time.sleep(5)  # Increased from 3 to 5 seconds
        
        # Scroll to the bottom of the page to trigger lazy loading
        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)  # Wait for content to load
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            
        # Wait a bit more after scrolling
        time.sleep(2)
        
        # Get all image elements
        soup = BeautifulSoup(driver.page_source, "html.parser")
        imgs = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if src:
                imgs.append(src)
        return imgs
    except Exception as e:
        print(f"⚠️ Selenium error: {str(e)}")
        return []
    finally:
        driver.quit()

def fetch_images_with_requests(url):
    print("📄 Using requests...")
    try:
        res = safe_get(requests, url, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        imgs = [img.get("src") or img.get("data-src") for img in soup.find_all("img") if img.get("src") or img.get("data-src")]
        return imgs
    except Exception:
        return []

def get_image_info(img_url, session=None):
    """
    Fetch image, get dimensions and format safely with proper headers and retry logic.
    
    Args:
        img_url: URL of the image to fetch
        session: Optional requests.Session for connection pooling
        
    Returns:
        Dict with image info or None if failed
    """
    # Create a session if one wasn't provided
    if session is None:
        session = requests.Session()
        close_session = True
    else:
        close_session = False
    
    # Enhanced headers to mimic a real browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Accept': 'image/webp,image/apng,image/avif,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'image',
        'Sec-Fetch-Mode': 'no-cors',
        'Sec-Fetch-Site': 'same-origin',
        'Pragma': 'no-cache',
        'Cache-Control': 'no-cache',
        'Referer': '/'.join(img_url.split('/')[:3]) + '/',
        'Sec-Ch-Ua': '"Google Chrome";v="119", "Chromium";v="119"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
    }
    
    # Configure retry strategy
    max_retries = 3
    retry_delay = 1  # Start with 1 second delay
    
    failure_info = None

    try:
        for attempt in range(max_retries):
            try:
                # Add a small delay between retries
                if attempt > 0:
                    time.sleep(retry_delay * (2 ** (attempt - 1)))  # Exponential backoff

                # Make the request
                resp = safe_get(
                    session,
                    img_url,
                    headers=headers,
                    timeout=10,
                    stream=True  # Stream the response to handle large files
                )

                # Check for rate limiting or server errors
                if resp.status_code == 429:  # Too Many Requests
                    retry_after = int(resp.headers.get('Retry-After', retry_delay * (2 ** attempt)))
                    time.sleep(retry_after)
                    continue

                resp.raise_for_status()  # Raise an exception for bad status codes

                # Read the image data
                img_data = resp.content
                if not img_data:
                    raise ValueError("Empty image data received")

                # Open and process the image
                img = Image.open(io.BytesIO(img_data))
                width, height = img.size

                return {
                    "width": width,
                    "height": height,
                    "format": img.format,
                    "size_kb": len(img_data) / 1024,
                    "status_code": resp.status_code,
                    "url": img_url,
                    "success": True
                }

            except requests.exceptions.RequestException as e:
                failure_info = {
                    "error": str(e),
                    "status_code": getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None,
                    "url": img_url,
                    "success": False
                }

                if attempt == max_retries - 1:  # Last attempt
                    print(f"❌ Failed to fetch image after {max_retries} attempts: {e}")
                continue

            except Exception as e:
                print(f"❌ Error processing image {img_url}: {str(e)}")
                failure_info = {
                    "error": str(e),
                    "url": img_url,
                    "success": False
                }
                return failure_info

    finally:
        if close_session:
            session.close()

    return failure_info


def is_valid_image(info, img_url=None):
    """Flexible image filtering logic."""
    if not info or not info.get("success", True):
        return False

    # ❌ Exclude images likely to be logos, icons, or favicons
    if img_url and any(x in img_url.lower() for x in ["logo", "logos", "icon", "favicon"]):
        return False

    w, h = info["width"], info["height"]
    ratio = w / h if h != 0 else 1

    # ✅ relaxed thresholds for dynamic images
    if w < 50 or h < 50:
        return False
    if ratio < 0.3 or ratio > 3.5:
        return False
    if info["size_kb"] < 5:
        return False
    if info["format"] not in ["JPEG", "PNG", "WEBP", "JPG"]:
        return False
    return True

def scrape_website_images(url):
    print(f"🌐 Fetching images from: {url}\n")
    
    # Detect website language first
    print("🌍 Detecting website language...")
    language = detect_website_language(url)
    print(f"✅ Detected language: {language}")
    
    try:
        # First try with requests (faster if it works)
        print("📄 Attempting to fetch images with requests...")
        imgs = fetch_images_with_requests(url)
        used_selenium = False
        
        # If no images found, try with Selenium (slower but handles JavaScript)
        if not imgs:
            print("⚠️ No images found with requests — retrying with Selenium...")
            imgs = fetch_images_with_selenium(url)
            used_selenium = True
        
        if not imgs:
            print("❌ No images found with either method")
            return {
                'images': [],
                'language': language
            }
            
        # Process the image URLs
        processed_imgs = []
        for img in imgs:
            if not img:
                continue
            try:
                # Clean up whitespace and handle relative URLs
                if isinstance(img, str):
                    img = re.sub(r"\s+", "", img)

                if not img.startswith(('http://', 'https://')):
                    img = urljoin(url, img)

                processed_imgs.append(img)
            except Exception as e:
                print(f"⚠️ Error processing image URL {img}: {str(e)}")
        
        # Deduplicate while preserving order
        unique_imgs = []
        seen = set()
        for img in processed_imgs:
            if img not in seen:
                seen.add(img)
                unique_imgs.append(img)
        
        print(f"🔍 Found {len(unique_imgs)} unique image URLs before filtering.")

        # Filter valid images
        valid_imgs = []
        for img_url in unique_imgs:
            try:
                info = get_image_info(img_url)
                if info and is_valid_image(info, img_url):
                    print(f"✅ Kept: {img_url}  ({info['width']}x{info['height']} | {int(info['size_kb'])}KB | {info['format']})")
                    valid_imgs.append(img_url)
                    if len(valid_imgs) >= MAX_VALID_IMAGES_BEFORE_STOP:
                        print(
                            f"\n📌 Reached {MAX_VALID_IMAGES_BEFORE_STOP} kept images; "
                            "skipping remaining URL checks for speed."
                        )
                        break
                else:
                    print(f"❌ Filtered out: {img_url}")
            except Exception as e:
                print(f"⚠️ Error checking image {img_url}: {str(e)}")

        # If we used requests and got 0 valid images, try Selenium as fallback
        # This helps with JavaScript-heavy sites that load images dynamically
        if not used_selenium and len(valid_imgs) == 0 and len(unique_imgs) > 0:
            print(f"\n⚠️ Requests found {len(unique_imgs)} images but all were filtered out.")
            print("🔄 Retrying with Selenium to find JavaScript-loaded images...")
            selenium_imgs = fetch_images_with_selenium(url)
            
            if selenium_imgs:
                # Process Selenium images
                selenium_processed = []
                for img in selenium_imgs:
                    if not img:
                        continue
                    try:
                        if isinstance(img, str):
                            img = re.sub(r"\s+", "", img)
                        if not img.startswith(('http://', 'https://')):
                            img = urljoin(url, img)
                        selenium_processed.append(img)
                    except Exception as e:
                        print(f"⚠️ Error processing Selenium image URL {img}: {str(e)}")
                
                # Deduplicate Selenium images
                selenium_unique = []
                selenium_seen = set()
                for img in selenium_processed:
                    if img not in selenium_seen:
                        selenium_seen.add(img)
                        selenium_unique.append(img)
                
                print(f"🔍 Selenium found {len(selenium_unique)} unique image URLs.")
                
                # Filter Selenium images
                for img_url in selenium_unique:
                    try:
                        info = get_image_info(img_url)
                        if info and is_valid_image(info, img_url):
                            print(f"✅ Kept (Selenium): {img_url}  ({info['width']}x{info['height']} | {int(info['size_kb'])}KB | {info['format']})")
                            valid_imgs.append(img_url)
                            if len(valid_imgs) >= MAX_VALID_IMAGES_BEFORE_STOP:
                                print(
                                    f"\n📌 Reached {MAX_VALID_IMAGES_BEFORE_STOP} kept images (Selenium); "
                                    "skipping remaining URL checks for speed."
                                )
                                break
                        else:
                            print(f"❌ Filtered out (Selenium): {img_url}")
                    except Exception as e:
                        print(f"⚠️ Error checking Selenium image {img_url}: {str(e)}")

        print(f"\n✅ Final content images (logos/icons excluded): {len(valid_imgs)}\n{'='*80}")
        return {
            'images': valid_imgs,
            'language': language
        }
        
    except Exception as e:
        print(f"❌ Error in scrape_website_images: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'images': [],
            'language': language if 'language' in locals() else 'en'
        }

if __name__ == "__main__":
    website = input("🔗 Enter website URL: ").strip()
    result = scrape_website_images(website)

    if not result['images']:
        print("⚠️ No valid content images found.")
    else:
        print(f"\n🖼️ Final image URLs (Language: {result['language']}):")
        for img in result['images']:
            print(img)

