# Placeholder file - Copy your holdflight/src/image/colors_from_favicon.py content here
# LOGO COLORS SCRAPING  

import requests
import numpy as np
from PIL import Image
from io import BytesIO
from sklearn.cluster import KMeans
import webcolors
from urllib.parse import urlparse
import base64
import os
import time

from holdflight.src.utils.chrome_options import (
    add_chrome_no_sandbox_if_needed,
    get_required_chromedriver_path,
    safe_driver_get,
    safe_get,
)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "cross-site",
    "Cache-Control": "max-age=0"
}


# -------------------------------------------------
# Build CSS3 color map (NEW webcolors compatible)
# -------------------------------------------------
def build_css3_color_map():
    color_map = {}
    for name in webcolors.names("css3"):
        rgb = webcolors.name_to_rgb(name)
        color_map[name] = (rgb.red, rgb.green, rgb.blue)
    return color_map


CSS3_COLORS = build_css3_color_map()


# -------------------------------------------------
# Find closest color name
# -------------------------------------------------
def closest_color_name(rgb):
    min_distance = float("inf")
    closest_name = "unknown"

    for name, css_rgb in CSS3_COLORS.items():
        distance = sum((c1 - c2) ** 2 for c1, c2 in zip(rgb, css_rgb))
        if distance < min_distance:
            min_distance = distance
            closest_name = name

    return closest_name


# -------------------------------------------------
# Download image using Selenium (bypasses 403 errors)
# -------------------------------------------------
def download_image_with_selenium(logo_url):
    """Download image using Selenium to bypass 403 errors"""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    add_chrome_no_sandbox_if_needed(chrome_options)
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    chrome_options.add_argument('--log-level=3')
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    chrome_options.add_argument('--disable-gpu')
    
    driver = None
    try:
        service = Service(executable_path=get_required_chromedriver_path())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        safe_driver_get(driver, logo_url)
        time.sleep(3)
        
        try:
            image_base64 = driver.execute_script("""
                var img = document.querySelector('img');
                if (!img) {
                    var body = document.body;
                    var bgImage = window.getComputedStyle(body).backgroundImage;
                    if (bgImage && bgImage !== 'none') {
                        return null;
                    }
                    return null;
                }
                var canvas = document.createElement('canvas');
                var ctx = canvas.getContext('2d');
                canvas.width = img.naturalWidth || img.width;
                canvas.height = img.naturalHeight || img.height;
                ctx.drawImage(img, 0, 0);
                return canvas.toDataURL('image/png').substring(22);
            """)
            
            if image_base64:
                image_data = base64.b64decode(image_base64)
                return BytesIO(image_data)
        except:
            pass
        
        screenshot = driver.get_screenshot_as_png()
        return BytesIO(screenshot)
            
    except Exception as e:
        print(f"⚠️ Selenium download failed: {e}")
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass


# -------------------------------------------------
# Extract colors from image data (BytesIO or file-like object)
# -------------------------------------------------
def extract_colors_from_image_data(image_data, num_colors=5):
    """
    Extract dominant colors from image data (BytesIO or file-like object).
    
    Args:
        image_data: BytesIO object or file-like object containing image data
        num_colors: Number of colors to extract (default: 5)
    
    Returns:
        List of color dictionaries with 'rgb', 'hex', and 'name' keys
    """
    if not image_data:
        raise Exception("No image data provided")

    image = Image.open(image_data).convert("RGBA")
    pixels = np.array(image)

    # Filter out transparent pixels
    pixels = pixels[pixels[:, :, 3] > 50]

    # Filter out very dark and very light pixels
    pixels = pixels[
        ((pixels[:, 0] > 20) | (pixels[:, 1] > 20) | (pixels[:, 2] > 20)) &
        ((pixels[:, 0] < 245) | (pixels[:, 1] < 245) | (pixels[:, 2] < 245))
    ]

    pixels = pixels[:, :3]

    if len(pixels) < num_colors:
        print("⚠️ Not enough pixels for clustering")
        return []

    kmeans = KMeans(n_clusters=num_colors, random_state=42, n_init=10)
    kmeans.fit(pixels)

    colors = kmeans.cluster_centers_.astype(int)

    results = []
    for rgb in colors:
        rgb_tuple = tuple(int(x) for x in rgb)
        hex_color = "#{:02X}{:02X}{:02X}".format(*rgb_tuple)
        name = closest_color_name(rgb_tuple)

        results.append({
            "rgb": rgb_tuple,
            "hex": hex_color,
            "name": name
        })

    return results


# -------------------------------------------------
# Extract dominant logo colors from URL
# -------------------------------------------------
def extract_logo_colors(logo_url, num_colors=5):
    """
    Extract dominant colors from an image URL.
    
    Args:
        logo_url: URL of the image
        num_colors: Number of colors to extract (default: 5)
    
    Returns:
        List of color dictionaries with 'rgb', 'hex', and 'name' keys
    """
    image_data = None
    
    session = requests.Session()
    try:
        response = safe_get(session, logo_url, headers=HEADERS, timeout=10, allow_redirects=True)
        response.raise_for_status()
        image_data = BytesIO(response.content)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            try:
                parsed_url = urlparse(logo_url)
                domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
                headers_with_referer = HEADERS.copy()
                headers_with_referer["Referer"] = domain
                response = safe_get(session, logo_url, headers=headers_with_referer, timeout=10, allow_redirects=True)
                response.raise_for_status()
                image_data = BytesIO(response.content)
            except:
                print("⚠️ Requests failed with 403, trying Selenium...")
                image_data = download_image_with_selenium(logo_url)
                if not image_data:
                    raise Exception("Failed to download image with both requests and Selenium")
        else:
            raise
    except Exception as e:
        print(f"⚠️ Requests failed: {e}, trying Selenium...")
        image_data = download_image_with_selenium(logo_url)
        if not image_data:
            raise Exception(f"Failed to download image: {e}")

    if not image_data:
        raise Exception("Could not download image")

    return extract_colors_from_image_data(image_data, num_colors)
    
# -------------------------------------------------
# MAIN (for standalone execution)
# -------------------------------------------------
def logo_color_scraping_full_code():
    """Original function wrapper for backward compatibility"""
    if __name__ == "__main__":
        logo_url = input("Enter logo image URL: ").strip()
        colors = extract_logo_colors(logo_url)
        print("\n🎨 Detected Logo Colors:\n")
        for i, c in enumerate(colors, 1):
            print(f"{i}. {c['name']} | {c['hex']} | RGB{c['rgb']}")


if __name__ == "__main__":
    logo_url = input("Enter logo image URL: ").strip()
    colors = extract_logo_colors(logo_url)
    print("\n🎨 Detected Logo Colors:\n")
    for i, c in enumerate(colors, 1):
        print(f"{i}. {c['name']} | {c['hex']} | RGB{c['rgb']}")





