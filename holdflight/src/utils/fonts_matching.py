# Placeholder file - Copy your holdflight/src/utils/fonts_matching.py content here



import os
import re
import requests
import json
from holdflight.src.utils.chrome_options import safe_get

def normalize_name(name: str) -> str:
    """Normalize font name for comparison."""
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def fetch_google_fonts(api_key: str, sort: str = "alpha") -> list:
    """Fetch Google Fonts list via Web Fonts Developer API."""
    if not api_key:
        raise ValueError("Google Fonts API key is required but not provided.")
    url = "https://www.googleapis.com/webfonts/v1/webfonts"
    params = {"key": api_key, "sort": sort}
    try:
        resp = safe_get(requests, url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])
    except requests.exceptions.RequestException as e:
        raise ValueError(f"Failed to fetch Google Fonts: {str(e)}")
    except Exception as e:
        raise ValueError(f"Error processing Google Fonts response: {str(e)}")

def match_scraped_fonts_regular_only(scraped_fonts: list, api_key: str) -> dict:
    """
    Match scraped fonts against Google Fonts.
    Returns only exact matches with regular variant and import URLs.
    Ignores fonts that are not found.
    """
    google_fonts = fetch_google_fonts(api_key)
    normalized_map = {normalize_name(f["family"]): f for f in google_fonts}

    results = {}
    for scraped in scraped_fonts:
        norm = normalize_name(scraped)
        font_data = normalized_map.get(norm)
        if font_data and "regular" in font_data.get("files", {}):
            family_name = font_data["family"].replace(" ", "+")
            import_url = f"https://fonts.googleapis.com/css2?family={family_name}&display=swap"
            results[scraped] = {
                "family": font_data["family"],
                "category": font_data["category"],
                "variant": "regular",
                "import_url": import_url
            }
    return results

if __name__ == "__main__":
    from scan import scrape_website_data
    
    # Load from environment variable only
    GOOGLE_API_KEY = os.environ.get('GOOGLE_FONTS_API_KEY')
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_FONTS_API_KEY environment variable is not set. Please set it in your .env file.")

    # Get website URL from user
    website_url = input("Enter website URL (e.g., example.com): ").strip()
    
    if not website_url:
        print("No URL provided!")
    else:
        print(f"\n🔍 Scraping fonts from {website_url}...")
        
        # Scrape website to get fonts
        scraping_result = scrape_website_data(website_url)
        
        if scraping_result and 'error' not in scraping_result:
            # Extract all fonts from the scraping result
            scraped_fonts = []
            
            # Add general fonts
            if 'fonts' in scraping_result and scraping_result['fonts']:
                scraped_fonts.extend(scraping_result['fonts'])
            
            # Add element-specific fonts
            if 'element_fonts' in scraping_result and scraping_result['element_fonts']:
                for element, fonts in scraping_result['element_fonts'].items():
                    if isinstance(fonts, list):
                        scraped_fonts.extend(fonts)
            
            # Remove duplicates while preserving order
            seen = set()
            scraped_fonts = [font for font in scraped_fonts if not (font in seen or seen.add(font))]
            
            if not scraped_fonts:
                print("❌ No fonts found on the website!")
            else:
                print(f"\n✅ Found {len(scraped_fonts)} font(s): {', '.join(scraped_fonts)}")
                print("\n🔄 Matching fonts with Google Fonts API...")
                
                # Match fonts with Google Fonts API
                results = match_scraped_fonts_regular_only(scraped_fonts, GOOGLE_API_KEY)
                
                if results:
                    print(f"\n✅ Matched {len(results)} font(s) with Google Fonts:")
                    print(json.dumps(results, indent=2, ensure_ascii=False))
                else:
                    print("\n❌ No matching Google Fonts found!")
        else:
            error_msg = scraping_result.get('error', 'Unknown error') if scraping_result else 'Failed to scrape website'
            print(f"❌ Error scraping website: {error_msg}")



