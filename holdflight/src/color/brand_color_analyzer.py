# Placeholder file - Copy your holdflight/src/color/brand_color_analyzer.py content here

import threading

# Safe print function that handles Unicode encoding errors
def safe_print(msg):
    """Print function that handles Unicode encoding errors on Windows"""
    try:
        print(msg)
    except UnicodeEncodeError:
        # Fallback for systems that can't handle Unicode
        print(msg.encode('ascii', 'replace').decode('ascii'))


# Load from package modules only.
try:
    from .colors import analyze_website_theme
except ImportError:
    from holdflight.src.color.colors import analyze_website_theme

try:
    from holdflight.src.image.colors_from_favicon import extract_logo_colors
except ImportError:
    def extract_logo_colors(url, num_colors=5):
        safe_print("extract_logo_colors unavailable - returning empty list")
        return []

WEBSITE_COLOR_SOURCE = "holdflight.src.color.colors"
LOGO_COLOR_SOURCE = "holdflight.src.image.colors_from_favicon"


def analyze_brand_colors(website_url, favicon_url):
    """
    Runs website color scraping and image (favicon/logo) color extraction SIMULTANEOUSLY
    Keeps both logics independent
    If favicon_url is provided, uses it; otherwise can use logo URL as fallback
    """
    website_data = None
    logo_colors = None
    website_error = None
    logo_error = None

    def scrape_website():
        nonlocal website_data, website_error
        try:
            print("\n🌐 Scraping website colors...\n")
            print(f"🔍 DEBUG scrape_website: Calling analyze_website_theme from {WEBSITE_COLOR_SOURCE}")
            print(f"🔍 DEBUG scrape_website: Function: {analyze_website_theme}")
            print(f"🔍 DEBUG scrape_website: URL: {website_url}")
            website_data = analyze_website_theme(website_url, max_colors=15)
            # DEBUG: Log what we got back
            if website_data:
                print(f"🔍 DEBUG scrape_website: Got website_data type: {type(website_data)}")
                if isinstance(website_data, dict):
                    print(f"🔍 DEBUG scrape_website: Keys: {list(website_data.keys())}")
                    if 'all_colors' in website_data:
                        print(f"🔍 DEBUG scrape_website: all_colors count: {len(website_data.get('all_colors', []))}")
                        print(f"🔍 DEBUG scrape_website: all_colors: {website_data.get('all_colors', [])}")
                    if 'top_colors' in website_data:
                        print(f"🔍 DEBUG scrape_website: top_colors count: {len(website_data.get('top_colors', []))}")
                        top_5 = website_data.get('top_colors', [])[:5]
                        print(f"🔍 DEBUG scrape_website: top_colors first 5: {[c.get('color', 'N/A') for c in top_5]}")
            else:
                print("🔍 DEBUG scrape_website: website_data is None or empty")
        except Exception as e:
            website_error = str(e)
            print(f"ERROR scraping website: {e}")
            import traceback
            traceback.print_exc()

    def scrape_favicon():
        nonlocal logo_colors, logo_error
        try:
            # Skip if favicon_url is empty or invalid
            if not favicon_url or not favicon_url.strip():
                print("\n⚠️ No image URL provided (favicon/logo), skipping image color extraction...\n")
                logo_colors = None
                return
            
            # Validate URL has a scheme
            if not favicon_url.startswith(('http://', 'https://')):
                print(f"\n⚠️ Invalid image URL format: {favicon_url}, skipping...\n")
                logo_colors = None
                return
            
            print("\n🎨 Scraping image colors (favicon/logo)...\n")
            print(f"🔍 DEBUG scrape_favicon: Calling extract_logo_colors from {LOGO_COLOR_SOURCE}")
            print(f"🔍 DEBUG scrape_favicon: Function: {extract_logo_colors}")
            print(f"🔍 DEBUG scrape_favicon: URL: {favicon_url}")
            logo_colors = extract_logo_colors(favicon_url, num_colors=5)
            # DEBUG: Log what we got back
            if logo_colors:
                print(f"🔍 DEBUG scrape_favicon: Got logo_colors count: {len(logo_colors)}")
                print(f"🔍 DEBUG scrape_favicon: logo_colors: {logo_colors}")
            else:
                print("🔍 DEBUG scrape_favicon: logo_colors is None or empty")
        except Exception as e:
            logo_error = str(e)
            print(f"ERROR scraping image colors: {e}")
            import traceback
            traceback.print_exc()

    # Run both scraping operations simultaneously
    thread1 = threading.Thread(target=scrape_website)
    thread2 = threading.Thread(target=scrape_favicon)

    thread1.start()
    thread2.start()

    thread1.join()
    thread2.join()

    return {
        "website_colors": website_data,
        "logo_colors": logo_colors,
        "website_error": website_error,
        "logo_error": logo_error
    }


def filter_high_weightage_colors(website_data, top_n=15):
    """
    Filter website colors to show only those with high weightage
    Returns top N colors by weight (default: top 15 to match max_colors)
    """
    if not website_data or not website_data.get('top_colors'):
        return []

    top_colors = website_data['top_colors']
    
    # Return top N colors by weight (already sorted by weight)
    # These are the highest weightage colors
    high_weight_colors = top_colors[:top_n]
    
    return high_weight_colors


def combine_colors(logo_colors, website_colors):
    """
    Combine favicon colors and high weightage website colors into one list
    Returns a unified list with all colors
    Prioritizes favicon/logo colors, then adds website colors
    """
    print(f"\n🔍 DEBUG combine_colors: Input - logo_colors: {logo_colors}, website_colors type: {type(website_colors)}")
    combined = []
    seen_hex = set()  # Track colors to avoid duplicates
    
    # Add all favicon/logo colors first (these are brand colors, so prioritize them)
    if logo_colors:
        print(f"🔍 DEBUG combine_colors: Adding {len(logo_colors)} logo colors")
        for c in logo_colors:
            hex_color = c.get('hex', '').upper()
            if hex_color and hex_color not in seen_hex:
                combined.append({
                    "source": "favicon",
                    "hex": hex_color,
                    "name": c.get('name', 'Unknown'),
                    "rgb": c.get('rgb', [0, 0, 0])
                })
                seen_hex.add(hex_color)
                print(f"🔍 DEBUG combine_colors: Added logo color: {hex_color}")
    else:
        print("🔍 DEBUG combine_colors: No logo_colors provided")
    
    # Add high weightage website colors (avoid duplicates)
    if website_colors:
        # Try to get all_colors first (more complete), fallback to filtered top colors
        if isinstance(website_colors, dict) and website_colors.get('all_colors'):
            # Use all_colors if available (up to 15 colors)
            all_colors_list = website_colors.get('all_colors', [])
            print(f"🔍 DEBUG combine_colors: Using all_colors, found {len(all_colors_list)} colors")
            for color_hex in all_colors_list[:15]:  # Limit to 15 to avoid too many
                hex_color = str(color_hex).upper().strip()
                if hex_color and hex_color not in seen_hex:
                    combined.append({
                        "source": "website",
                        "hex": hex_color,
                        "weight": 0,
                        "percentage": 0
                    })
                    seen_hex.add(hex_color)
                    print(f"🔍 DEBUG combine_colors: Added website color (all_colors): {hex_color}")
        else:
            # Fallback to filtered high weightage colors
            print(f"🔍 DEBUG combine_colors: Using top_colors fallback")
            high_weight_colors = filter_high_weightage_colors(website_colors, top_n=15)
            print(f"🔍 DEBUG combine_colors: Filtered to {len(high_weight_colors)} high weight colors")
            for c in high_weight_colors:
                hex_color = c.get('color', '').upper()
                if hex_color and hex_color not in seen_hex:
                    combined.append({
                        "source": "website",
                        "hex": hex_color,
                        "weight": c.get('weight', 0),
                        "percentage": c.get('percentage', 0)
                    })
                    seen_hex.add(hex_color)
                    print(f"🔍 DEBUG combine_colors: Added website color (top_colors): {hex_color}")
    else:
        print("🔍 DEBUG combine_colors: No website_colors provided")
    
    print(f"🔍 DEBUG combine_colors: Final combined count: {len(combined)}")
    print(f"🔍 DEBUG combine_colors: Final combined colors: {[c.get('hex', 'N/A') for c in combined]}")
    return combined


def print_results(result):
    print("\n" + "=" * 60)
    print("🎨 COMBINED BRAND COLORS")
    print("=" * 60)
    print("(All Favicon Colors + High Weightage Website Colors)")
    print("=" * 60)
    
    # Combine colors
    combined_colors = combine_colors(
        result.get("logo_colors"),
        result.get("website_colors")
    )
    
    if not combined_colors:
        print("No colors found.")
        if result.get("logo_error"):
            print(f"❌ Favicon Error: {result['logo_error']}")
        if result.get("website_error"):
            print(f"❌ Website Error: {result['website_error']}")
        return
    
    # Display combined colors
    for i, color in enumerate(combined_colors, 1):
        if color["source"] == "favicon":
            # Logo color format
            rgb_str = f"RGB({color['rgb'][0]}, {color['rgb'][1]}, {color['rgb'][2]})"
            print(f"{i}. [{color['source'].upper()}] {color['name']} | {color['hex']} | {rgb_str}")
        else:
            # Website color format
            print(
                f"{i}. [{color['source'].upper()}] {color['hex']} | "
                f"Weight={color.get('weight', 0):.2f} | "
                f"{color.get('percentage', 0):.1f}%"
            )
    
    # Summary
    favicon_count = sum(1 for c in combined_colors if c["source"] == "favicon")
    website_count = sum(1 for c in combined_colors if c["source"] == "website")
    print("\n" + "-" * 60)
    print(f"Summary: {favicon_count} favicon color(s) + {website_count} high weightage website color(s) = {len(combined_colors)} total")


if __name__ == "__main__":
    website_url = input("Enter website URL: ").strip()
    favicon_url = input("Enter favicon image URL: ").strip()

    if not website_url.startswith(("http://", "https://")):
        website_url = "https://" + website_url

    results = analyze_brand_colors(website_url, favicon_url)
    print_results(results)




