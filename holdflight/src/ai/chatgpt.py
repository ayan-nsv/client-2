# Placeholder file - Copy your holdflight/src/ai/chatgpt.py content here
# OpenAI/ChatGPT integration
from openai import OpenAI
from typing import List, Dict, Any
import base64
import mimetypes
import os
import requests
from requests.exceptions import RequestException
from dotenv import load_dotenv
from holdflight.src.utils.chrome_options import safe_get

# Load environment variables from .env file
load_dotenv()

# Import the image scraper
try:
    from tp import scrape_website_images
except ImportError:
    scrape_website_images = None

# English / common name → ISO 639-1 (must match keys in create_analysis_prompt language_names)
_LANGUAGE_ALIASES = {
    "german": "de",
    "deutsch": "de",
    "english": "en",
    "swedish": "sv",
    "svenska": "sv",
    "spanish": "es",
    "español": "es",
    "espanol": "es",
    "french": "fr",
    "français": "fr",
    "francais": "fr",
    "italian": "it",
    "italiano": "it",
    "portuguese": "pt",
    "português": "pt",
    "portugues": "pt",
    "dutch": "nl",
    "nederlands": "nl",
    "danish": "da",
    "dansk": "da",
    "norwegian": "no",
    "norsk": "no",
    "finnish": "fi",
    "suomi": "fi",
    "polish": "pl",
    "polski": "pl",
    "russian": "ru",
    "русский": "ru",
    "japanese": "ja",
    "chinese": "zh",
    "mandarin": "zh",
    "korean": "ko",
    "arabic": "ar",
    "hindi": "hi",
}


def _normalize_image_analysis_language(language: str) -> str:
    """
    Accepts the same input clients may send:
    - ISO 639-1 code: en, de, … (any case: EN → en)
    - Locale tag: en-US, de-DE, en_GB, … (primary subtag is used)
    - English full name: english, german, swedish, … (as in _LANGUAGE_ALIASES)
    """
    if not language or not str(language).strip():
        return "en"
    s = str(language).strip()
    if "_" in s and len(s) > 2:
        s = s.split("_", 1)[0]
    if "-" in s and len(s) > 2:
        s = s.split("-", 1)[0]
    s = s.lower()
    if len(s) == 2 and s.isalpha():
        return s
    return _LANGUAGE_ALIASES.get(s, s)


class ImageAnalyzer:
    """Analyzes images using OpenAI's gpt-4o-mini model with vision capabilities"""
    def __init__(self):
        """Initialize the ImageAnalyzer with OpenAI API key from environment variable"""
        # Try holdflight-specific key first, then fall back to general key
        self.api_key = os.environ.get('HOLDFLIGHT_OPENAI_API_KEY') or os.environ.get('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("HOLDFLIGHT_OPENAI_API_KEY or OPENAI_API_KEY environment variable is not set. Please set it in your .env file.")
        
        base_url = os.getenv("OPENAI_API_URL") or os.getenv("OPENAI_BASE_URL")
        if base_url:
            self.client = OpenAI(api_key=self.api_key, base_url=base_url)
        else:
            self.client = OpenAI(api_key=self.api_key)
    
    def create_analysis_prompt(self, language: str = 'en') -> str:
        """
        Create the structured prompt for image analysis
        
        Args:
            language: ISO 639-1 code (e.g. en, de), locale tag (e.g. en-US, en_GB), or
                English name (e.g. english, german). All are case-insensitive.

        Returns:
            str: The formatted prompt for ChatGPT
        """
        code = _normalize_image_analysis_language(language)
        # Language mapping (keys are ISO 639-1)
        language_names = {
            'en': 'English',
            'sv': 'Swedish',
            'de': 'German',
            'es': 'Spanish',
            'fr': 'French',
            'it': 'Italian',
            'pt': 'Portuguese',
            'nl': 'Dutch',
            'da': 'Danish',
            'no': 'Norwegian',
            'fi': 'Finnish',
            'pl': 'Polish',
            'ru': 'Russian',
            'ja': 'Japanese',
            'zh': 'Chinese',
            'ko': 'Korean',
            'ar': 'Arabic',
            'hi': 'Hindi' 
        }
        language_name = language_names.get(code)
        if language_name is None:
            # Unknown ISO code or free-text label: use a readable name for the model
            if len(code) == 2 and code.isalpha():
                language_name = f"the language for ISO code {code}"
            else:
                language_name = code.replace("_", " ").title()
        
        prompt = f"""You are a professional image analysis expert. Your task is to analyze website images for brand and design purposes.

CRITICAL LANGUAGE REQUIREMENT:
- The website you're analyzing is in {language_name} (language code: {code})
- You MUST provide your ENTIRE analysis in {language_name}
- ALL section headings, descriptions, keywords, and analysis MUST be in {language_name}
- DO NOT write in English or any other language - ONLY use {language_name}
- This is mandatory - the entire output must match the website's language

TASK: Analyze the provided images from a business website. These are professional images used for marketing and branding purposes. Analyze their visual style, composition, and design elements to help understand the brand's visual identity and create similar imagery.

Please analyze these images and provide a detailed breakdown using the following structure (ALL IN {language_name.upper()}):

**Image Types & Animation**
- CRITICAL: Identify the specific image type category. This is ESSENTIAL for accurate image generation. Determine if the images are:
  * 2D illustrations (flat illustrations, digital illustrations, hand-drawn style, cartoon style, etc.)
  * Photographs (real photography, stock photos, lifestyle photography, product photography, etc.)
  * 3D renders (3D graphics, CGI, computer-generated imagery, rendered models, etc.)
  * Vector art (vector graphics, SVG-style illustrations, geometric illustrations, etc.)
  * Mixed media (combinations of the above)
  * Other specific types (watercolor, oil painting, sketch, etc.)
- Identify if there are any animated images, GIFs, or special image types (e.g., static photos, animated graphics, motion graphics, cinemagraphs)
- Mention if images appear to have movement, animation, or dynamic elements
- Note any patterns in image format usage (e.g., predominantly static images, mix of static and animated, etc.)
- Be very specific about the image type - this information will be used to generate similar images, so accuracy is crucial.
- If all images are of the same type (e.g., all 2D illustrations), emphasize this clearly and consistently.

**Theme / Atmosphere**
- Describe the overall theme and atmosphere (e.g., fusion of elements, emotional tone)
- What feeling should the space evoke? (exclusive, modern, clean, inviting, etc.)
- Is it personal, joyful, human-centered, sterile, or intimidating?

**Environment / Setting**
- Type of space (e.g., boutique fitness studio, spa, office, etc.)
- Interior design details: colors, materials, furniture
- Lighting fixtures and natural light
- Decor elements and styling details
- Overall mood and comparison to similar spaces

**Subjects / People**
- Demographics and characteristics of people shown
- Facial expressions and emotions displayed
- Clothing, uniforms, or specific attire
- Activities and poses captured

**Technology Elements**
- Any tech equipment visible (machines, devices, sensors, cables)
- Screens, tablets, or digital displays
- How technology contrasts or integrates with the environment
- Modern vs. traditional elements

**Lighting & Color Tone**
- Quality of lighting (warm, natural, soft, harsh, neon, etc.)
- Light sources (ceiling lamps, daylight, wall lighting)
- Color palette (neutral tones, accent colors)
- Surface qualities (reflective, matte, polished)

**Composition & Style**
- Camera angles and shot types (close-ups, over-the-shoulder, wide shots)
- Use of reflections, mirrors, or depth
- Human interaction and positioning
- Balance between different elements

**Keywords for AI Image Generation**
- Provide a comprehensive comma-separated list of keywords that capture all visual elements, mood, style, and atmosphere for AI image generation tools like Midjourney, DALL-E, or Stable Diffusion.
- CRITICAL: The FIRST keyword(s) should ALWAYS specify the image type (e.g., "2D illustration", "photograph", "3D render", "vector art") to ensure the image generator creates the correct type of image.
- Include keywords for animation type if applicable (e.g., "animated", "gif-style", "motion graphics", "static photography")
- Follow with style, mood, colors, composition, and other visual elements.

IMPORTANT REMINDERS:
- Write your ENTIRE response in {language_name} - including ALL headings, descriptions, keywords, and analysis
- Be specific, descriptive, and focus on visual elements that would help an AI recreate similar imagery
- CRITICAL: Always identify the specific image type category (2D illustration, photograph, 3D render, etc.) - this is essential for the image generator to create the correct type of image
- Pay special attention to identifying any animated or GIF images
- Remember: NO ENGLISH OR OTHER LANGUAGES - ONLY {language_name}"""
        
        return prompt
    
    def _download_image_as_data_uri(self, url: str) -> str:
        """
        Download an image and convert it to a data URI string so the OpenAI API
        does not need to fetch the remote URL directly (avoids timeout issues).
        """

        try:
            response = safe_get(requests, url, timeout=15)
            response.raise_for_status()
        except RequestException as exc:
            raise ValueError(f"Failed to download image {url}: {exc}") from exc

        content_type = response.headers.get('Content-Type')
        if not content_type or content_type == 'application/octet-stream':
            guessed_type, _ = mimetypes.guess_type(url)
            content_type = guessed_type or 'image/jpeg'

        # OpenAI currently supports images up to ~20MB. Guard against very large files.
        max_bytes = 20 * 1024 * 1024
        if len(response.content) > max_bytes:
            raise ValueError(
                f"Image {url} is too large ({len(response.content)} bytes). "
                "Maximum supported size is 20MB."
            )

        encoded = base64.b64encode(response.content).decode('utf-8')
        return f"data:{content_type};base64,{encoded}"

    def analyze_images(self, image_urls: List[str], custom_prompt: str = None, language: str = 'en') -> Dict[str, Any]:
        """
        Analyze multiple images using GPT-4o-mini (vision-enabled model)
        
        Args:
            image_urls: List of image URLs to analyze
            custom_prompt: Optional custom prompt. If None, uses the default structured prompt
            language: ISO code (e.g. en, de), locale (en-US, en_GB), or English name (english, german)
            
        Returns:
            Dict containing the analysis results
        """
        if not image_urls:
            raise ValueError("At least one image URL is required")
        
        # Use the custom prompt if provided, otherwise use the default one with language support
        prompt = custom_prompt if custom_prompt else self.create_analysis_prompt(language=language)
        
        # Build the messages content
        content = [{"type": "text", "text": prompt}]
        
        # Add all images to the content (convert to data URIs to avoid remote fetch timeouts)
        download_errors = []
        for url in image_urls:
            # Check if URL is already a data URI (starts with "data:")
            if isinstance(url, str) and url.startswith("data:"):
                # Already a data URI, use it directly
                image_reference = url
            else:
                # Regular URL, download and convert to data URI
                try:
                    data_uri = self._download_image_as_data_uri(url)
                    image_reference = data_uri
                except ValueError as exc:
                    download_errors.append(str(exc))
                    # Fallback to original URL if download fails; API might still succeed
                    image_reference = url

            content.append({
                "type": "image_url",
                "image_url": {
                    "url": image_reference,
                    "detail": "low"  # Use low detail for cost efficiency
                }
            })
        
        try:
            # Make the API call with a system message to clarify the task
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",  # Using gpt-4o-mini for cost efficiency
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional image analysis expert. You analyze business website images for brand identity, design style, and visual composition. You provide detailed, structured analysis of images for legitimate business and design purposes."
                    },
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                max_tokens=2000,
                temperature=0.7
            )
            
            # Extract the response
            analysis = response.choices[0].message.content
            
            result = {
                "success": True,
                "analysis": analysis,
                "image_count": len(image_urls),
                "model_used": response.model,
                "tokens_used": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }

            if download_errors:
                result["warnings"] = download_errors

            return result
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "image_count": len(image_urls)
            }
    
    def analyze_and_save(self, image_urls: List[str], output_file: str = "image_analysis.txt", custom_prompt: str = None) -> Dict[str, Any]:
        """
        Analyze images and save the results to a file
        
        Args:
            image_urls: List of image URLs to analyze
            output_file: Path to save the analysis results
            custom_prompt: Optional custom prompt
            
        Returns:
            Dict containing the analysis results
        """
        result = self.analyze_images(image_urls, custom_prompt)
        
        if result["success"]:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("IMAGE ANALYSIS RESULTS\n")
                f.write("=" * 80 + "\n\n")
                f.write(f"Analyzed {result['image_count']} image(s)\n")
                f.write(f"Model: {result['model_used']}\n")
                f.write(f"Tokens used: {result['tokens_used']['total_tokens']}\n\n")
                f.write("=" * 80 + "\n")
                f.write("ANALYSIS\n")
                f.write("=" * 80 + "\n\n")
                f.write(result['analysis'])
                f.write("\n\n" + "=" * 80 + "\n")
                f.write("IMAGE URLS ANALYZED\n")
                f.write("=" * 80 + "\n")
                for i, url in enumerate(image_urls, 1):
                    f.write(f"{i}. {url}\n")
            
            print(f"✓ Analysis saved to: {output_file}")
        else:
            print(f"✗ Analysis failed: {result['error']}")
        
        return result
    
    def analyze_from_tp_output(self, scraped_images: List, output_file: str = "image_analysis.txt", 
                                max_images: int = 10, custom_prompt: str = None) -> Dict[str, Any]:
        """
        Analyze images from tp.py scraper output
        
        Args:
            scraped_images: List from tp.py scrape_all_images()
                           Can be list of strings (URLs) or list of dicts with 'url' key
            output_file: Path to save the analysis results
            max_images: Maximum number of images to analyze (default: 10, to control API costs)
            custom_prompt: Optional custom prompt
            
        Returns:
            Dict containing the analysis results
        """
        if not scraped_images:
            return {
                "success": False,
                "error": "No images provided from scraper",
                "image_count": 0
            }
        
        # Handle both old format (dicts) and new format (strings)
        # Extract URLs from tp.py output format
        if scraped_images and isinstance(scraped_images[0], dict):
            # Old format: list of dicts with 'url' key
            image_urls = [img['url'] for img in scraped_images if img.get('url')]
        else:
            # New format: list of URL strings
            image_urls = [img for img in scraped_images if isinstance(img, str)]
        
        # Filter out small icons, favicons, SVGs, etc. that are usually not useful for style analysis
        filtered_urls = []
        
        # OpenAI Vision API supported formats only
        supported_formats = ['.png', '.jpg', '.jpeg', '.gif', '.webp']
        
        for img in scraped_images:
            # Handle both string URLs and dict format
            if isinstance(img, str):
                url = img
            elif isinstance(img, dict):
                # Old format: skip certain types
                skip_types = ['favicon', 'apple-touch-icon']
                if img.get('type') in skip_types or not img.get('url'):
                    continue
                url = img['url']
            else:
                continue
            
            # Check if URL has a supported image format
            has_supported_format = any(url.lower().endswith(fmt) or fmt in url.lower() for fmt in supported_formats)
            
            # Skip SVG files (not supported by OpenAI)
            if '.svg' in url.lower():
                continue
            
            # Skip protected/authenticated URLs (OpenAI can't access these)
            protected_patterns = [
                'GoogleAccessId=',           # Google Cloud Storage signed URLs
                'Signature=',                # AWS S3 presigned URLs / GCS signed URLs
                'X-Amz-Signature=',          # AWS S3 signature
                'AWSAccessKeyId=',           # AWS credentials
                '?token=',                   # Generic auth tokens
                '&token=',                   # Generic auth tokens
            ]
            if any(pattern in url for pattern in protected_patterns):
                continue
            
            # Skip logos, icons, and very small images (check URL patterns for size)
            skip_keywords = ['icon', 'favicon', 'logo', 'avatar', '/w_25,', '/w_29,', '/w_34,', '/w_50,', '/w_58,', '/w_68,', '/w_112,']
            if any(skip in url.lower() for skip in skip_keywords):
                continue
            
            # Only add if supported format
            if has_supported_format:
                filtered_urls.append(url)
        
        # Use filtered URLs if we have any, otherwise use all
        final_urls = filtered_urls[:max_images] if filtered_urls else image_urls[:max_images]
        
        if not final_urls:
            return {
                "success": False,
                "error": "No suitable images found after filtering. Possible reasons: (1) Only logos/icons found, (2) Images protected by authentication, (3) No photos/lifestyle images. For meaningful analysis, the website needs publicly accessible photos or lifestyle images.",
                "image_count": 0,
                "scraped_count": len(scraped_images),
                "suggestion": "Try a website with publicly accessible photos, product images, or lifestyle imagery (not behind authentication)."
            }
        
        # Show filtering results
        filtered_count = len(scraped_images) - len(filtered_urls)
        if filtered_count > 0:
            print(f"🔍 Filtered out {filtered_count} images (SVGs, icons, unsupported formats)")
        
        print(f"📊 Analyzing {len(final_urls)} images (out of {len(scraped_images)} scraped)")
        print(f"   Supported formats: PNG, JPG, GIF, WEBP")
        print(f"   Using GPT-4o-mini model\n")
        
        # Analyze the images
        return self.analyze_and_save(final_urls, output_file, custom_prompt)
    
    def analyze_from_url(self, website_url: str, output_file: str = "image_analysis.txt", 
                         max_images: int = 10, custom_prompt: str = None) -> Dict[str, Any]:
        """
        Scrape images from a URL using tp.py and analyze them
        Args:
            website_url: URL of the website to scrape
            output_file: Path to save the analysis results
            max_images: Maximum number of images to analyze
            custom_prompt: Optional custom prompt
            
        Returns:
            Dict containing the analysis results
        """
        if scrape_website_images is None:
            return {
                "success": False,
                "error": "tp.py module not found. Make sure tp.py is in the same directory.",
                "image_count": 0
            }
        
        print(f"🌐 Scraping images from: {website_url}\n")
        scraped_images = scrape_website_images(website_url)
        
        if not scraped_images:
            return {
                "success": False,
                "error": "No images found on the website",
                "image_count": 0
            }
        
        print(f"\n{'='*80}\n")
        return self.analyze_from_tp_output(scraped_images, output_file, max_images, custom_prompt)

def main():
    """
    Example usage of the ImageAnalyzer
    
    Three ways to use this:
    1. Directly with a website URL (scrapes and analyzes)
    2. With image data from tp.py
    3. Directly with image URLs
    """
    
    try:
        analyzer = ImageAnalyzer()
        
        # METHOD 1: Directly from website URL (easiest)
        print("=" * 80)
        print("IMAGE ANALYZER - GPT-4o-mini")
        print("=" * 80)
        print("\nChoose an option:")
        print("1. Scrape and analyze a website URL")
        print("2. Analyze specific image URLs")
        print("3. Exit")
        
        choice = input("\nEnter your choice (1-3): ").strip()
        
        if choice == "1":
            # Scrape from URL and analyze
            website_url = input("\n🔗 Enter website URL: ").strip()
            
            if not website_url.startswith(('http://', 'https://')):
                website_url = 'https://' + website_url
            
            max_imgs = input("📊 Max images to analyze (default 10, max 20): ").strip()
            max_imgs = int(max_imgs) if max_imgs.isdigit() else 10
            max_imgs = min(max_imgs, 20)  # Cap at 20 to control costs
            
            print("\n" + "=" * 80)
            result = analyzer.analyze_from_url(
                website_url=website_url,
                output_file="image_analysis.txt",
                max_images=max_imgs
            )
            
        elif choice == "2":
            # Manual URL input
            print("\n📸 Enter image URLs (one per line, empty line to finish):")
            image_urls = []
            while True:
                url = input().strip()
                if not url:
                    break
                image_urls.append(url)
            
            if not image_urls:
                print("❌ No URLs provided")
                return
            
            print(f"\nAnalyzing {len(image_urls)} image(s)...")
            print("This may take a moment...\n")
            
            result = analyzer.analyze_and_save(
                image_urls=image_urls,
                output_file="image_analysis.txt"
            )
        else:
            print("👋 Goodbye!")
            return

        # Show results
        if result.get("success"):
            print("\n" + "=" * 80)
            print("✅ ANALYSIS COMPLETE")
            print("=" * 80)
            print(f"\n📊 Statistics:")
            print(f"   - Images analyzed: {result['image_count']}")
            print(f"   - Model used: {result['model_used']}")
            print(f"   - Tokens used: {result['tokens_used']['total_tokens']}")
            print(f"\n📄 Full analysis saved to: image_analysis.txt")
            print("\n" + "=" * 80)
            print("ANALYSIS PREVIEW (first 800 chars):")
            print("=" * 80)
            preview = result['analysis'][:800]
            print(preview + "..." if len(result['analysis']) > 800 else preview)
            print("\n" + "=" * 80)
        else:
            print(f"\n❌ Analysis failed: {result.get('error')}")
        
    except ValueError as e:
        print(f"\n❌ Error: {e}")
        print("\n⚠️ To use this script, set your OpenAI API key:")
        print("   Windows PowerShell: $env:OPENAI_API_KEY='your-key-here'")
        print("   Command Prompt: set OPENAI_API_KEY=your-key-here")
        print("   Linux/Mac: export OPENAI_API_KEY='your-key-here'")
        print("\n   Or pass it directly in the code:")
        print("   analyzer = ImageAnalyzer(api_key='your-key-here')")
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user. Goodbye!")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

# USAGE EXAMPLES FOR INTEGRATION:
def example_integration_with_tp():
    """
    Example showing how to integrate with tp.py scraper
    """
    from tp import scrape_website_images
    
    # Step 1: Scrape images using tp.py
    website_url = "https://example.com"
    scraped_images = scrape_website_images(website_url)
    
    # Step 2: Analyze with ChatGPT
    analyzer = ImageAnalyzer()
    result = analyzer.analyze_from_tp_output(
        scraped_images=scraped_images,
        output_file="analysis_output.txt",
        max_images=10
    )
    return result

def example_direct_url_analysis():
    """
    Example showing direct URL analysis
    """
    analyzer = ImageAnalyzer()
    
    # Option 1: From website (scrapes + analyzes in one go)
    result = analyzer.analyze_from_url(
        website_url="https://example.com",
        output_file="analysis.txt",
        max_images=10
    )
    
    return result

def example_manual_urls():
    """
    Example showing manual URL list analysis
    """
    analyzer = ImageAnalyzer()
    
    urls = [
        "https://example.com/image1.jpg",
        "https://example.com/image2.jpg",
    ]
    
    result = analyzer.analyze_and_save(
        image_urls=urls,
        output_file="analysis.txt"
    )
    
    return result

if __name__ == "__main__":
    main()





