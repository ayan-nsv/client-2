# Placeholder file - Copy your holdflight/src/color/colors.py content here
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import re
import colorsys
import time
from collections import defaultdict
from holdflight.src.utils.chrome_options import (
    add_chrome_no_sandbox_if_needed,
    get_required_chromedriver_path,
    safe_driver_get,
)


def analyze_website_theme(url, timeout=20, max_colors=15):
    """
    Analyze website colors using Selenium with visual weight calculation
    """
    # Setup Chrome options
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    add_chrome_no_sandbox_if_needed(chrome_options)
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--force-device-scale-factor=1')  # Ensure consistent scaling
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    chrome_options.add_argument('--log-level=3')
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    chrome_options.page_load_strategy = 'eager'      
    # Ensure consistent color rendering
    chrome_options.add_argument('--disable-color-correct-rendering')  # Disable color correction
    chrome_options.add_argument('--disable-features=ColorCorrectRendering')  # Additional color correction disable
    # Force English language to ensure consistent content (prevents Swedish/other language versions)
    # This ensures both local and live environments get the same language version of websites
    chrome_options.add_argument('--lang=en-US')
    chrome_options.add_experimental_option('prefs', {
        'intl.accept_languages': 'en-US,en'
    })
    
    # Additional Chrome options for cloud/Docker environments
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--disable-software-rasterizer')
    chrome_options.add_argument('--disable-extensions')
    
    # Set Chrome binary location if in deployment environment
    import os
    chrome_bin = os.environ.get('CHROME_BIN')
    if chrome_bin and os.path.exists(chrome_bin):
        chrome_options.binary_location = chrome_bin
        print(f"Using Chrome binary at: {chrome_bin}")

    driver = None
    try:
        system_chromedriver = get_required_chromedriver_path()
        print(f"Using configured ChromeDriver at: {system_chromedriver}")
        service = Service(executable_path=system_chromedriver)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(timeout)
        try:
            safe_driver_get(driver, url)
        except TimeoutException as exc:
            print(f"WARNING: page load timed out ({exc}), continuing with partial DOM")
        
        # Wait for page to be fully loaded and rendered
        # Use WebDriverWait for more reliable waiting instead of fixed sleep
        try:
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
        except:
            pass
        
        # Set Accept-Language header via JavaScript to ensure English content
        try:
            driver.execute_script("""
                // Override navigator.language to ensure English
                Object.defineProperty(navigator, 'language', {
                    get: function() { return 'en-US'; }
                });
                Object.defineProperty(navigator, 'languages', {
                    get: function() { return ['en-US', 'en']; }
                });
            """)
        except:
            pass
        
        # Additional wait for dynamic content and CSS to fully render
        time.sleep(3)  # Reduced from 5, but still allow CSS animations/transitions
        
        # Scroll page to trigger lazy-loaded content
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
        except:
            pass
        
        print(f"✓ Successfully loaded page: {url}")
        color_weights = extract_colors_with_weight(driver)

        if not color_weights:
            print("WARNING: No color weights extracted from page")
            return None

        print(f"✓ Extracted {len(color_weights)} color entries")
        # DEBUG: Log first few raw color entries
        if color_weights and len(color_weights) > 0:
            print(f"🔍 DEBUG: First 5 raw color entries:")
            for i, entry in enumerate(color_weights[:5], 1):
                print(f"🔍 DEBUG:   {i}. {entry.get('color', 'N/A')} - weight: {entry.get('weight', 0):.2f}")
        
        theme_data = process_weighted_colors(color_weights, max_colors)
        
        if theme_data and theme_data.get('all_colors'):
            print(f"✓ Successfully processed {len(theme_data['all_colors'])} final colors")
            print(f"🔍 DEBUG: Final all_colors: {theme_data.get('all_colors', [])}")
        else:
            print("🔍 DEBUG: theme_data is None or missing all_colors")
        
        return theme_data
    except Exception as e:
        import traceback
        print(f"ERROR in analyze_website_theme: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

def extract_colors_with_weight(driver):
    """
    Extract colors with their visual weight (area * opacity * importance)
    """

    color_extraction_script = """
    const colorWeights = new Map();

    // Get viewport dimensions
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const viewportArea = viewportWidth * viewportHeight;

    // Get all elements and convert to array for deterministic processing
    const elements = Array.from(document.querySelectorAll('*'));

    elements.forEach(el => {
        const rect = el.getBoundingClientRect();

        // Skip invisible elements
        if (rect.width === 0 || rect.height === 0) return;

        // Calculate visible area
        const visibleWidth = Math.min(rect.right, viewportWidth) - Math.max(rect.left, 0);
        const visibleHeight = Math.min(rect.bottom, viewportHeight) - Math.max(rect.top, 0);

        if (visibleWidth <= 0 || visibleHeight <= 0) return;

        const elementArea = visibleWidth * visibleHeight;
        const styles = window.getComputedStyle(el);

        // Get opacity
        const opacity = parseFloat(styles.opacity) || 1;

        // Calculate importance based on element type and position
        let importance = 1;

        // Headers and important elements get higher weight
        const tagName = el.tagName.toLowerCase();
        if (['h1', 'h2', 'h3'].includes(tagName)) importance = 3;
        if (['button', 'a'].includes(tagName)) importance = 2.5;
        if (el.classList.contains('hero') || el.classList.contains('header')) importance = 2;

        // Elements in viewport get higher priority
        const inViewport = rect.top < viewportHeight && rect.bottom > 0;
        if (inViewport) importance *= 1.5;

        // Process background color
        const bgColor = styles.backgroundColor;
        if (bgColor && 
            bgColor !== 'rgba(0, 0, 0, 0)' && 
            bgColor !== 'transparent') {

            const weight = elementArea * opacity * importance;
            const current = colorWeights.get(bgColor) || 0;
            colorWeights.set(bgColor, current + weight);
        }

        // Process text color (with slightly less weight)
        const textColor = styles.color;
        if (textColor && 
            textColor !== 'rgba(0, 0, 0, 0)' && 
            textColor !== 'transparent') {

            const weight = (elementArea * 0.3) * opacity * importance;
            const current = colorWeights.get(textColor) || 0;
            colorWeights.set(textColor, current + weight);
        }

        // Process border colors (if visible)
        const borderWidth = parseFloat(styles.borderWidth) || 0;
        if (borderWidth > 0) {
            const borderColor = styles.borderColor;
            if (borderColor && borderColor !== 'rgba(0, 0, 0, 0)') {
                const borderArea = (rect.width + rect.height) * borderWidth * 2;
                const weight = borderArea * opacity * importance;
                const current = colorWeights.get(borderColor) || 0;
                colorWeights.set(borderColor, current + weight);
            }
        }
    });

    // Convert to array, sort by color for deterministic processing, then normalize weights
    const colorEntries = Array.from(colorWeights.entries());
    // Sort by color string first to ensure deterministic order
    colorEntries.sort((a, b) => a[0].localeCompare(b[0]));
    
    const maxWeight = Math.max(...colorEntries.map(([_, weight]) => weight));

    return colorEntries.map(([color, weight]) => ({
        color: color,
        weight: weight,
        normalizedWeight: (weight / maxWeight) * 100
    }));
    """

    try:
        color_data = driver.execute_script(color_extraction_script)
        color_data.sort(key=lambda x: x['weight'], reverse=True)
        return color_data
    except:
        return []

def rgb_to_hex(rgb_string):
    """Convert rgb/rgba string to hex with normalization to reduce Chrome version differences"""
    match = re.search(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', rgb_string)
    if match:
        r, g, b = map(int, match.groups())
        # Normalize to reduce minor variations between Chrome versions
        # Round to nearest 3 to merge very similar colors (e.g., 253->252, 254->255)
        r = normalize_rgb_value(r)
        g = normalize_rgb_value(g)
        b = normalize_rgb_value(b)
        # Clamp to valid range
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        return f"#{r:02x}{g:02x}{b:02x}"
    return None

def hex_to_rgb(hex_color):
    """Convert hex to RGB tuple"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def color_distance(color1, color2):
    """Calculate perceptual distance between two colors"""
    r1, g1, b1 = hex_to_rgb(color1)
    r2, g2, b2 = hex_to_rgb(color2)

    # Weighted Euclidean distance (closer to human perception)
    rmean = (r1 + r2) / 2
    r = r1 - r2
    g = g1 - g2
    b = b1 - b2

    return ((2 + rmean/256) * r**2 + 4 * g**2 + (2 + (255-rmean)/256) * b**2) ** 0.5

def normalize_rgb_value(value):
    """Normalize RGB value to reduce minor variations between Chrome versions"""
    # Round to nearest 3 to reduce noise (e.g., 253->252, 254->255, 127->126)
    # This helps merge colors that are essentially the same but reported differently
    return round(value / 3) * 3

def merge_similar_colors(color_data, threshold=40):
    """Merge similar colors, keeping the one with highest weight"""
    if not color_data:
        return []

    print(f"🔍 DEBUG merge_similar_colors: Input count: {len(color_data)}, threshold: {threshold}")
    merged = []
    used_indices = set()

    for i, item in enumerate(color_data):
        if i in used_indices:
            continue

        hex_color = rgb_to_hex(item['color'])
        if not hex_color:
            continue

        # Find all similar colors
        similar_weight = item['weight']
        merged_count = 1

        for j in range(i + 1, len(color_data)):
            if j in used_indices:
                continue

            other_hex = rgb_to_hex(color_data[j]['color'])
            if not other_hex:
                continue

            distance = color_distance(hex_color, other_hex)
            if distance < threshold:
                similar_weight += color_data[j]['weight']
                used_indices.add(j)
                merged_count += 1

        merged.append({
            'color': hex_color,
            'weight': similar_weight
        })
        used_indices.add(i)
        if merged_count > 1:
            print(f"🔍 DEBUG merge_similar_colors: Merged {merged_count} colors into {hex_color}")

    print(f"🔍 DEBUG merge_similar_colors: Output count: {len(merged)}")
    return merged

def categorize_color(hex_color):
    """Categorize a color based on HSV values"""
    r, g, b = hex_to_rgb(hex_color)
    h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)

    # Check if it's grayscale
    if s < 0.15:
        if v > 0.85:
            return 'light-neutral'
        elif v < 0.25:
            return 'dark-neutral'
        else:
            return 'neutral'

    # Bright, saturated colors (accent/brand colors)
    if s > 0.5 and v > 0.5:
        return 'accent'

    # Medium saturation (primary colors)
    if s > 0.25:
        return 'primary'

    return 'secondary'

def get_color_name(hex_color):
    """Get a human-readable color name"""
    r, g, b = hex_to_rgb(hex_color)
    h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
    h = h * 360

    if s < 0.15:
        if v > 0.9:
            return "White"
        elif v < 0.2:
            return "Black"
        elif v > 0.6:
            return "Light Gray"
        else:
            return "Dark Gray"

    # Color hues
    if h < 15 or h >= 345:
        return "Red"
    elif h < 45:
        return "Orange"
    elif h < 75:
        return "Yellow"
    elif h < 165:
        return "Green"
    elif h < 255:
        return "Blue"
    elif h < 285:
        return "Purple"
    else:
        return "Pink"

def process_weighted_colors(color_data, max_colors=15):
    """Process weighted colors and return top colors by visual impact"""

    # Merge similar colors
    merged = merge_similar_colors(color_data, threshold=35)

    # Sort by weight
    merged.sort(key=lambda x: x['weight'], reverse=True)

    # Separate white/black from other colors
    colored = []
    white_black = []

    for item in merged:
        color = item['color'].lower()
        if color in ['#000000', '#ffffff']:
            white_black.append(item)
        else:
            colored.append(item)

    # Only include white/black if they're truly dominant (top weighted among all colors)
    include_wb = False
    if merged and merged[0]['color'].lower() in ['#000000', '#ffffff']:
        include_wb = True

    # Get top colored colors first
    if include_wb:
        top_colors = colored[:max_colors-len(white_black)] + white_black
    else:
        top_colors = colored[:max_colors]

    # Normalize weights for display
    if top_colors:
        max_weight = top_colors[0]['weight']
        for item in top_colors:
            item['percentage'] = (item['weight'] / max_weight) * 100

    # Categorize
    categorized = {
        'accent': [],
        'primary': [],
        'secondary': [],
        'neutral': [],
        'light-neutral': [],
        'dark-neutral': []
    }

    for item in top_colors:
        category = categorize_color(item['color'])
        categorized[category].append(item)

    all_colors = [item['color'] for item in top_colors]

    return {
        'top_colors': top_colors,
        'colors_by_category': categorized,
        'all_colors': all_colors
    }


def _dedupe_ordered_font_names(names):
    seen = set()
    out = []
    for n in names:
        if not n:
            continue
        s = str(n).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _extract_font_families_from_driver(driver):
    """
    Computed font stacks from the live DOM (headings, body text, links).
    Returns general_fonts (deduped list) and element_fonts (tag -> list).
    """
    general_script = """
    function firstFamily(ff) {
        if (!ff) return null;
        return ff.replace(/['"]/g, '').split(',')[0].trim();
    }
    var general = new Set();
    var elements = document.querySelectorAll(
        'h1, h2, h3, h4, h5, h6, p, a, button, li, span, div'
    );
    for (var i = 0; i < Math.min(elements.length, 400); i++) {
        try {
            var f = firstFamily(window.getComputedStyle(elements[i]).fontFamily);
            if (f && f !== 'inherit' && f.length < 120) general.add(f);
        } catch (e) {}
    }
    return Array.from(general).slice(0, 24);
    """
    element_script = """
    var elementFonts = {};
    var elementSelectors = {
        'h1': 'h1', 'h2': 'h2', 'h3': 'h3', 'h4': 'h4',
        'h5': 'h5', 'h6': 'h6', 'paragraph': 'p'
    };
    function cleanFontFamily(fontFamily) {
        if (!fontFamily) return null;
        return fontFamily.replace(/['"]/g, '').split(',')[0].trim();
    }
    Object.keys(elementSelectors).forEach(function(elementName) {
        var selector = elementSelectors[elementName];
        var nodes = document.querySelectorAll(selector);
        var fonts = new Set();
        for (var i = 0; i < Math.min(nodes.length, 12); i++) {
            try {
                var cleaned = cleanFontFamily(window.getComputedStyle(nodes[i]).fontFamily);
                if (cleaned && cleaned !== 'inherit') fonts.add(cleaned);
            } catch (e) {}
        }
        if (fonts.size > 0) {
            elementFonts[elementName] = Array.from(fonts);
        }
    });
    return elementFonts;
    """
    try:
        raw_general = driver.execute_script(general_script) or []
    except Exception:
        raw_general = []
    try:
        element_fonts = driver.execute_script(element_script) or {}
    except Exception:
        element_fonts = {}
    if not isinstance(element_fonts, dict):
        element_fonts = {}

    stacked = []
    stacked.extend(raw_general if isinstance(raw_general, list) else [])
    for v in element_fonts.values():
        if isinstance(v, list):
            stacked.extend(v)

    general_fonts = _dedupe_ordered_font_names(stacked)[:18]
    return {"general_fonts": general_fonts, "element_fonts": element_fonts}


def analyze_website_theme_and_fonts(url, timeout=25, max_colors=15):
    """
    One headless Chrome session: weighted viewport colors + computed font families.
    Intended for lightweight brand hints (e.g. text placement). Does not load logos,
    favicons, or run GPT — much faster than full WebsiteAnalyzer.analyze_website.
    """
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    add_chrome_no_sandbox_if_needed(chrome_options)
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--force-device-scale-factor=1')
    chrome_options.add_argument(
        'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    chrome_options.add_argument('--log-level=3')
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    chrome_options.page_load_strategy = 'eager'
    chrome_options.add_argument('--disable-color-correct-rendering')
    chrome_options.add_argument('--disable-features=ColorCorrectRendering')
    chrome_options.add_argument('--lang=en-US')
    chrome_options.add_experimental_option('prefs', {'intl.accept_languages': 'en-US,en'})
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--disable-software-rasterizer')
    chrome_options.add_argument('--disable-extensions')

    import os
    chrome_bin = os.environ.get('CHROME_BIN')
    if chrome_bin and os.path.exists(chrome_bin):
        chrome_options.binary_location = chrome_bin
        print(f"Using Chrome binary at: {chrome_bin}")

    driver = None
    try:
        system_chromedriver = get_required_chromedriver_path()
        print(f"Using configured ChromeDriver at: {system_chromedriver}")
        service = Service(executable_path=system_chromedriver)
        driver = webdriver.Chrome(service=service, options=chrome_options)

        driver.set_page_load_timeout(timeout)
        try:
            safe_driver_get(driver, url)
        except TimeoutException as exc:
            print(f"WARNING: page load timed out ({exc}), continuing with partial DOM")

        try:
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
        except Exception:
            pass

        try:
            driver.execute_script("""
                Object.defineProperty(navigator, 'language', { get: function() { return 'en-US'; } });
                Object.defineProperty(navigator, 'languages', { get: function() { return ['en-US', 'en']; } });
            """)
        except Exception:
            pass

        time.sleep(2)
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)
        except Exception:
            pass

        print(f"✓ Loaded page for theme + fonts (single session): {url}")
        color_weights = extract_colors_with_weight(driver)
        theme_data = None
        if color_weights:
            theme_data = process_weighted_colors(color_weights, max_colors)
        else:
            print("WARNING: No color weights from page")

        font_payload = _extract_font_families_from_driver(driver)

        return {
            'theme_data': theme_data,
            'general_fonts': font_payload.get('general_fonts') or [],
            'element_fonts': font_payload.get('element_fonts') or {},
        }
    except Exception as e:
        import traceback
        print(f"ERROR in analyze_website_theme_and_fonts: {e}")
        print(traceback.format_exc())
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def print_theme_colors(theme_data):
    """Print only hex codes"""
    if not theme_data:
        return

    colors = theme_data.get('all_colors', [])
    if not colors and 'top_colors' in theme_data:
        colors = [item['color'] for item in theme_data['top_colors']]

    if not colors:
        return

    for color in colors:
        print(color.upper())

def main():
    """
    Main function
    
    NOTE: This only extracts WEBSITE colors.
    The live API uses website_analyzer.py → brand_color_analyzer.py which combines:
    - Website colors (from this file/C1.PY)
    - Favicon/logo colors (from C2.PY)
    
    To match live API results, use website_analyzer.py or brand_color_analyzer.py instead.
    """
    import sys

    if len(sys.argv) > 1:
        url = sys.argv[1]
        max_colors = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    else:
        url = input("Enter website URL: ").strip()
        max_colors = 15

    if not url:
        return

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    print("⚠️ NOTE: This only extracts website colors.")
    print("   Live API combines website + favicon/logo colors.")
    print("   For matching results, use: python test_colors_local.py <url>\n")

    theme_data = analyze_website_theme(url, max_colors=max_colors)

    if theme_data:
        print_theme_colors(theme_data)
    else:
        print("ERROR: Failed to extract colors")

if __name__ == "__main__":
    main()





