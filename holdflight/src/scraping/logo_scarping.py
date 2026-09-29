# Placeholder file - Copy your holdflight/src/scraping/logo_scarping.py content here
# Logo extraction

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
from holdflight.src.utils.chrome_options import safe_get

def is_likely_logo(src, alt="", class_names="", id_name=""):
    """Check if an image is likely a logo based on various attributes"""
    logo_indicators = ["logo", "brand", "logotyp", "site-logo", "header-logo", "company-logo", "brand-logo"]
    
    # EXPANDED NOISE WORDS - This is the key fix
    noise_words = [
        "banner", "ad", "advertisement", "promo", "promotional",
        "icon-", "social", "avatar", "profile", "user-", "author",
        "thumb", "thumbnail", "preview", "featured", "gallery",
        "slider", "slide", "carousel", "hero-image", "background",
        "product", "catalog", "item-", "post-", "article-",
        "widget", "sidebar", "footer-icon", "payment", "badge",
        "certificate", "award", "partner", "sponsor", "client",
        "flag", "country", "language", "search-icon", "menu-icon",
        "arrow", "chevron", "caret", "hamburger", "close-icon",
        "play-button", "video-", "youtube", "facebook", "twitter",
        "instagram", "linkedin", "pinterest", "whatsapp", "email-icon",
        "cart", "basket", "shop-", "store-", "ecommerce"
    ]
    
    combined = f"{src} {alt} {class_names} {id_name}".lower()
    
    # FILTER OUT NOISE FIRST (stronger check)
    if any(noise in combined for noise in noise_words):
        return False
    
    # Check for common non-logo patterns in URLs
    if any(pattern in src.lower() for pattern in [
        '/uploads/', '/content/', '/media/posts/', '/blog/',
        '/products/', '/items/', '/gallery/', '/slider/',
        '/icons/social', '/images/icons', 'icon-pack'
    ]):
        return False
    
    # REQUIRE logo indicators to be present (stricter)
    if any(indicator in combined for indicator in logo_indicators):
        return True
    
    # Additional: Check if it's in a logo-like position (header, nav, logo class)
    position_indicators = ["header", "nav", "top-bar", "branding"]
    if any(pos in combined for pos in position_indicators):
        return True
    
    return False

def has_logo_in_url(url):
    """Check if URL contains 'logo' or 'logos' keyword"""
    url_lower = url.lower()
    return 'logo' in url_lower or 'logos' in url_lower

def prioritize_logos(logos_list):
    """
    Sort logos to prioritize those with 'logo/logos' in URL
    Returns: (priority_logos, other_logos)
    """
    priority = []
    others = []
    
    for logo in logos_list:
        if has_logo_in_url(logo):
            priority.append(logo)
        else:
            others.append(logo)
    
    return priority, others

def get_all_images_from_element(element, url):
    """Extract all images from an element including srcset and data attributes"""
    images = set()
    valid_formats = [".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"]
    
    if not element:
        return images
    
    # Find all img tags
    imgs = element.find_all('img')
    for img in imgs:
        # Try multiple src attributes
        src = (img.get('src') or 
               img.get('data-src') or 
               img.get('data-lazy-src') or 
               img.get('data-original') or
               img.get('data-lazy'))
        
        alt = img.get('alt', '')
        class_names = ' '.join(img.get('class', []))
        id_name = img.get('id', '')
        
        if src:
            # Make sure it's a valid image format
            if any(fmt in src.lower() for fmt in valid_formats):
                full_url = urljoin(url, src)
                images.add((full_url, f"img[alt='{alt[:30]}']", class_names, id_name))
        
        # Check srcset
        srcset = img.get('srcset')
        if srcset:
            # Parse srcset (format: "url 1x, url 2x")
            urls = re.findall(r'(\S+\.\w+)', srcset)
            for srcset_url in urls:
                if any(fmt in srcset_url.lower() for fmt in valid_formats):
                    full_url = urljoin(url, srcset_url)
                    images.add((full_url, f"img[srcset][alt='{alt[:30]}']", class_names, id_name))
    
    # Find SVG elements
    svgs = element.find_all('svg')
    for svg in svgs:
        # Check if SVG has xlink:href or href attributes
        use_tags = svg.find_all('use')
        for use in use_tags:
            href = use.get('xlink:href') or use.get('href')
            if href and any(fmt in href.lower() for fmt in valid_formats):
                full_url = urljoin(url, href)
                images.add((full_url, "svg>use", "", ""))
    
    # Check for background images in style attributes
    elements_with_style = element.find_all(style=True)
    for el in elements_with_style:
        style = el.get('style', '')
        matches = re.findall(r'url\(["\']?([^"\'()]+)["\']?\)', style)
        for match in matches:
            if any(fmt in match.lower() for fmt in valid_formats):
                full_url = urljoin(url, match)
                class_names = ' '.join(el.get('class', []))
                images.add((full_url, "background-image", class_names, ""))
    
    # Check for <a> tags with image-like hrefs (sometimes logos are linked)
    links = element.find_all('a', href=True)
    for link in links:
        href = link.get('href', '')
        if any(fmt in href.lower() for fmt in valid_formats):
            full_url = urljoin(url, href)
            class_names = ' '.join(link.get('class', []))
            images.add((full_url, "a[href]", class_names, ""))
    
    return images

def scrape_logo(url, return_all=False):
    """
    Scrape logo images from a website.
    Priority: navbar > header > logo-specific > footer > meta tags
    URLs with 'logo/logos' keyword are prioritized in results
    
    Args:
        url: Website URL to scrape
        return_all: If True, returns list of all found logos; if False, returns single best logo (default)
    
    Returns:
        If return_all=True: List of logo URLs (up to 5)
        If return_all=False: Single best logo URL or empty string
    """
    logos = []
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        print(f"🌐 Fetching: {url}")
        response = safe_get(requests, url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()
        
        print("✅ Page loaded successfully\n")
        
        # --- PRIORITY 1: NAVBAR ---
        soup = BeautifulSoup(response.content, 'html.parser')
        print("🔍 [1] Searching NAVBAR...")
        nav_selectors = [
            'nav', '.nav', '.navbar', '.navigation', '#nav', '#navbar',
            '[class*="nav"]', '[class*="menu"]', 'header nav', '.header-nav',
            '.top-nav', '.main-nav', '[role="navigation"]'
        ]
        
        for selector in nav_selectors:
            navs = soup.select(selector)
            for nav in navs:
                images = get_all_images_from_element(nav, url)
                for img_url, tag_type, classes, img_id in images:
                    # APPLY FILTERING HERE (KEY FIX)
                    if is_likely_logo(img_url, "", classes, img_id):
                        logos.append(img_url)
                        priority_marker = "⭐" if has_logo_in_url(img_url) else "  "
                        print(f"   {priority_marker} ✓ Found: {img_url}")
                        print(f"      Type: {tag_type}, Classes: {classes[:50]}")
        
        if logos:
            priority, others = prioritize_logos(logos)
            sorted_logos = priority + others  # Priority logos first
            print(f"\n✅ Found {len(sorted_logos)} logo(s) in NAVBAR!")
            print(f"   ({len(priority)} with 'logo' in URL ⭐)\n")
            result_logos = sorted_logos[:5] if len(sorted_logos) >= 5 else sorted_logos
            if return_all:
                return result_logos
            else:
                return result_logos[0] if result_logos else ''
        
        # --- PRIORITY 2: HEADER ---
        print("🔍 [2] Searching HEADER...")
        header_selectors = [
            'header', '.header', '.site-header', '.page-header',
            '#header', '[class*="header"]', '.top-header', '.masthead'
        ]
        
        for selector in header_selectors:
            headers_found = soup.select(selector)
            for header in headers_found:
                images = get_all_images_from_element(header, url)
                for img_url, tag_type, classes, img_id in images:
                    # APPLY FILTERING HERE TOO
                    if is_likely_logo(img_url, "", classes, img_id):
                        logos.append(img_url)
                        priority_marker = "⭐" if has_logo_in_url(img_url) else "  "
                        print(f"   {priority_marker} ✓ Found: {img_url}")
                        print(f"      Type: {tag_type}, Classes: {classes[:50]}")
        
        if logos:
            priority, others = prioritize_logos(logos)
            sorted_logos = priority + others
            print(f"\n✅ Found {len(sorted_logos)} logo(s) in HEADER!")
            print(f"   ({len(priority)} with 'logo' in URL ⭐)\n")
            result_logos = sorted_logos[:5] if len(sorted_logos) >= 5 else sorted_logos
            if return_all:
                return result_logos
            else:
                return result_logos[0] if result_logos else ''
        
        # --- PRIORITY 3: LOGO-SPECIFIC CLASSES/IDS ---
        print("🔍 [3] Searching for LOGO-SPECIFIC elements...")
        logo_selectors = [
            '.logo', '#logo', '[class*="logo"]', '[id*="logo"]',
            '.brand', '#brand', '[class*="brand"]', '.site-logo',
            'a.logo', 'div.logo', 'span.logo', '.company-logo'
        ]
        
        for selector in logo_selectors:
            elements = soup.select(selector)
            for element in elements:
                images = get_all_images_from_element(element, url)
                for img_url, tag_type, classes, img_id in images:
                    # More lenient here since it's already logo-specific
                    if not any(noise in img_url.lower() for noise in ["icon", "social", "banner"]):
                        logos.append(img_url)
                        priority_marker = "⭐" if has_logo_in_url(img_url) else "  "
                        print(f"   {priority_marker} ✓ Found: {img_url}")
                        print(f"      Type: {tag_type}, Classes: {classes[:50]}")
        
        if logos:
            priority, others = prioritize_logos(logos)
            sorted_logos = priority + others
            print(f"\n✅ Found {len(sorted_logos)} logo(s) with logo-specific selectors!")
            print(f"   ({len(priority)} with 'logo' in URL ⭐)\n")
            result_logos = sorted_logos[:5] if len(sorted_logos) >= 5 else sorted_logos
            if return_all:
                return result_logos
            else:
                return result_logos[0] if result_logos else ''
        
        # --- PRIORITY 4: FOOTER ---
        print("🔍 [4] Searching FOOTER...")
        footer_selectors = [
            'footer', '.footer', '.site-footer', '#footer', '[class*="footer"]'
        ]
        
        for selector in footer_selectors:
            footers = soup.select(selector)
            for footer in footers:
                images = get_all_images_from_element(footer, url)
                for img_url, tag_type, classes, img_id in images:
                    if is_likely_logo(img_url, "", classes, img_id):
                        logos.append(img_url)
                        priority_marker = "⭐" if has_logo_in_url(img_url) else "  "
                        print(f"   {priority_marker} ✓ Found: {img_url}")
        
        if logos:
            priority, others = prioritize_logos(logos)
            sorted_logos = priority + others
            print(f"\n✅ Found {len(sorted_logos)} logo(s) in FOOTER!")
            print(f"   ({len(priority)} with 'logo' in URL ⭐)\n")
            result_logos = sorted_logos[:5] if len(sorted_logos) >= 5 else sorted_logos
            if return_all:
                return result_logos
            else:
                return result_logos[0] if result_logos else ''
        
        # --- PRIORITY 5: META TAGS ---
        print("🔍 [5] Checking META TAGS...")
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            img_url = urljoin(url, og_image.get('content'))
            if is_likely_logo(img_url, "", "", ""):
                logos.append(img_url)
                priority_marker = "⭐" if has_logo_in_url(img_url) else "  "
                print(f"   {priority_marker} ✓ Found OG image: {img_url}")
        
        # Apple touch icons (usually good logo candidates)
        apple_icons = soup.find_all('link', rel=lambda x: x and 'apple-touch-icon' in str(x).lower())
        for icon in apple_icons:
            href = icon.get('href')
            if href:
                img_url = urljoin(url, href)
                logos.append(img_url)
                priority_marker = "⭐" if has_logo_in_url(img_url) else "  "
                print(f"   {priority_marker} ✓ Found apple-touch-icon: {img_url}")
        
        if logos:
            priority, others = prioritize_logos(logos)
            sorted_logos = priority + others
            print(f"\n✅ Found {len(sorted_logos)} logo(s) in META TAGS!")
            print(f"   ({len(priority)} with 'logo' in URL ⭐)\n")
            result_logos = sorted_logos[:5] if len(sorted_logos) >= 5 else sorted_logos
            if return_all:
                return result_logos
            else:
                return result_logos[0] if result_logos else ''
        
        # --- PRIORITY 6: FAVICON FALLBACK ---
        print("🔍 [6] Checking FAVICON...")
        favicon = soup.find('link', rel=lambda x: x and 'icon' in str(x).lower())
        if favicon and favicon.get('href'):
            img_url = urljoin(url, favicon.get('href'))
            logos.append(img_url)
            priority_marker = "⭐" if has_logo_in_url(img_url) else "  "
            print(f"   {priority_marker} ✓ Found favicon: {img_url}")
            unique_logos = list(set(logos))
            result_logos = unique_logos[:5] if len(unique_logos) >= 5 else unique_logos
            if return_all:
                return result_logos
            else:
                return result_logos[0] if result_logos else ''
        
        # Final sorting with deduplication
        unique_logos = list(set(logos))
        priority, others = prioritize_logos(unique_logos)
        sorted_logos = priority + others if logos else []
        
        # Return based on return_all parameter
        if return_all:
            # Return up to 5 logos for GPT selection
            return sorted_logos[:5] if sorted_logos else []
        else:
            # Return single best logo (original behavior)
            return sorted_logos[0] if sorted_logos else ''
        
    except requests.RequestException as e:
        print(f"\n❌ Network Error: {e}")
        return [] if return_all else ''
    except Exception as e:
        print(f"\n❌ Parsing Error: {e}")
        import traceback
        traceback.print_exc()
        return [] if return_all else ''


if __name__ == "__main__":
    url = input("🔗 Enter website URL: ").strip()
    
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    result = scrape_logo(url)
    
    print("\n" + "="*60)
    if result:
            print(f"✅ FOUND {len(result)} LOGO(S):\n")
            for i, logo in enumerate(result, 1):
                marker = "⭐" if has_logo_in_url(logo) else "  "
                print(f"   {marker} {i}. {logo}")
            
            # Summary
            priority_count = sum(1 for logo in result if has_logo_in_url(logo))
            if priority_count > 0:
                print(f"\n   ⭐ = Contains 'logo/logos' in URL ({priority_count} prioritized)")
    else:
        print("⚠️ NO LOGOS FOUND")
    print("="*60)




