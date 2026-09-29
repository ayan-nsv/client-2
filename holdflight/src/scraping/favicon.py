# Placeholder file - Copy your holdflight/src/scraping/favicon.py content here
# Favicon extraction
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import urllib.parse
from holdflight.src.utils.chrome_options import safe_get

def get_clean_domain(url):
    """Extract clean domain from URL"""
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.replace('www.', '')
    return domain.split(':')[0]

def scrape_favicon(url):
    """
    Main function to scrape favicon from a website.
    
    Args:
        url (str): The website URL to scrape
        
    Returns:
        str or None: Favicon URL if found, None otherwise
    """
    favicon = None
    
    try:
        # Add https:// if not present
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        print(f"🌐 Fetching: {url}")
        response = safe_get(requests, url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        print("✅ Page loaded successfully\n")
        
        # --- SCRAPE FAVICON ---
        print("🔍 Searching for FAVICON...")
        
        favicons = []
        
        # Look for favicon in link tags
        favicon_selectors = [
            {'rel': 'icon'},
            {'rel': 'shortcut icon'},
            {'rel': 'apple-touch-icon'},
            {'rel': 'apple-touch-icon-precomposed'}
        ]
        
        for selector in favicon_selectors:
            links = soup.find_all('link', selector)
            for link in links:
                href = link.get('href')
                if href:
                    full_url = urljoin(url, href)
                    favicons.append(full_url)
        
        # Try common favicon paths
        if not favicons:
            domain = get_clean_domain(url)
            parsed = urlparse(url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            
            common_paths = [
                f"{base}/favicon.ico",
                f"{base}/favicon.png",
                f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
            ]
            favicons.extend(common_paths)
        
        favicon = favicons[0] if favicons else None
        
        if not favicon:
            domain = get_clean_domain(url)
            favicon = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
        
        print(f"   ✅ FAVICON: {favicon}")
        
        return favicon
        
    except requests.RequestException as e:
        print(f"\n❌ Network Error: {e}")
        return favicon
    except Exception as e:
        print(f"\n❌ Parsing Error: {e}")
        import traceback
        traceback.print_exc()
        return favicon


if __name__ == "__main__":
    print("="*70)
    print("🌟 FAVICON SCRAPER")
    print("="*70)
    
    url = input("\n🔗 Enter website URL: ").strip()
    
    print("\n" + "="*70)
    favicon = scrape_favicon(url)
    
    print("\n" + "="*70)
    print("✅ FINAL RESULT")
    print("="*70)
    print(f"\n🌟 FAVICON: {favicon or 'Not found'}")
    print("\n" + "="*70)




