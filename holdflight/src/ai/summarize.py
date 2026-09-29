# Placeholder file - Copy your holdflight/src/ai/summarize.py content here
# AI summarization
import os
import re
import logging
from typing import Dict, Any, List, Optional
import json 
import signal
from functools import wraps
from openai import OpenAI
from dotenv import load_dotenv
import threading

logger = logging.getLogger(__name__)

try:
    from langdetect import detect, detect_langs
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False
    logger.warning("langdetect not available - language detection will rely on GPT only")

load_dotenv()

class TimeoutError(Exception):
    """Custom timeout exception"""
    pass

def timeout_handler(timeout_duration):
    """Decorator to add timeout to functions using threading (works on Windows)"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            import threading
            result = [TimeoutError(f"Function call exceeded {timeout_duration} seconds")]
            
            def target():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    result[0] = e
            
            thread = threading.Thread(target=target)
            thread.daemon = True
            thread.start()
            thread.join(timeout_duration)
            
            if thread.is_alive():
                logger.error(f"Function {func.__name__} timed out after {timeout_duration} seconds")
                raise TimeoutError(f"Function call exceeded {timeout_duration} seconds")
            
            if isinstance(result[0], Exception):
                raise result[0]
            
            return result[0]
        return wrapper
    return decorator

class _ClientHolder:
    @property
    def api_key(self) -> str:
        _, api_key = _get_cached_openai_client()
        return api_key

def _get_openai_client():
    # Get API key from environment variable - try holdflight-specific key first, then fall back to general key
    api_key = os.environ.get('HOLDFLIGHT_OPENAI_API_KEY') or os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("HOLDFLIGHT_OPENAI_API_KEY or OPENAI_API_KEY environment variable is not set. Please set it in your .env file.")
    
    # Initialize OpenAI client with minimal configuration
    base_url = os.getenv("OPENAI_API_URL") or os.getenv("OPENAI_BASE_URL")
    if base_url:
        client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
    else:
        client = OpenAI(
            api_key=api_key
        )
    return client, api_key

_client_obj = None
_api_key = None
_client_lock = threading.Lock()
client = _ClientHolder()


def _get_cached_openai_client():
    global _client_obj, _api_key
    if _client_obj is not None and _api_key is not None:
        return _client_obj, _api_key
    with _client_lock:
        if _client_obj is None or _api_key is None:
            _client_obj, _api_key = _get_openai_client()
    return _client_obj, _api_key

def _coalesce_list(items, max_items):
    if not items:
        return ""
    cleaned = []
    for item in items[:max_items]:
        s = str(item).strip().replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
        # Remove excessive whitespace
        s = re.sub(r'\s+', ' ', s)
        # Limit each item to 200 characters to prevent excessive data
        if len(s) > 200:
            s = s[:197] + "..."
        if s:
            cleaned.append(s)
    return ", ".join(cleaned)

def _clean_list(items, max_items) -> List[str]:
    if not items:
        return []

    cleaned: List[str] = []
    for item in items[:max_items]:
        s = str(item).strip().replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')

        s = re.sub(r'\s+', ' ', s)
        if len(s) > 200:
            s = s[:197] + "..."
        if s:
            cleaned.append(s)
    return cleaned


def _is_valid_font(font_name: str) -> bool:
    """
    Check if a font name is valid and not random scraped text.
    
    Args:
        font_name: Font name to validate
        
    Returns:
        True if font appears to be valid, False otherwise
    """
    if not font_name or not isinstance(font_name, str):
        return False
    
    font = font_name.strip().lower()
    
    # Remove quotes and normalize
    font = font.replace('"', '').replace("'", '').strip()
    
    # Skip empty or very short strings
    if len(font) < 2:
        return False
    
    # Skip strings that are too long (likely not font names)
    if len(font) > 50:
        return False
    
    # Basic font family keywords that indicate valid fonts
    font_keywords = ['sans', 'serif', 'mono', 'script', 'display', 'text', 'gothic', 'ui']
    
    # Check for font families (e.g., "Arial, sans-serif")
    if ',' in font:
        font_parts = [f.strip() for f in font.split(',')]
        # If any part contains font keywords, it's likely valid
        if any(keyword in part for part in font_parts for keyword in font_keywords):
            return True
    
    import re
    
    # Skip obvious non-font patterns
    if re.search(r'https?://|@|\d{4,}|[{}()\[\]<>]', font):
        return False
    
    # Accept if it looks like a reasonable font name (letters, spaces, hyphens)
    if re.match(r'^[a-z\s\-]{2,30}$', font) and re.search(r'[a-z]', font):
        return True
    
    return False


def _validate_and_clean_fonts(fonts: List[str]) -> List[str]:
    """
    Validate and clean a list of fonts, removing invalid ones.
    
    Args:
        fonts: List of font names to validate
        
    Returns:
        List of valid font names
    """
    if not fonts:
        return []
    
    valid_fonts = []
    seen = set()
    
    for font in fonts:
        if not font:
            continue
            
        # Clean the font name
        cleaned_font = str(font).strip()
        
        # Skip duplicates (case-insensitive)
        font_lower = cleaned_font.lower()
        if font_lower in seen:
            continue
            
        # Validate font
        if _is_valid_font(cleaned_font):
            valid_fonts.append(cleaned_font)
            seen.add(font_lower)
    
    return valid_fonts


def _clean_body_text(text: str, max_length: int = 5000) -> str:
    """
    Aggressively clean body text to prevent hanging issues.
    
    Args:
        text: Raw text content from website
        max_length: Maximum character length (default 5000, increased for more detailed summaries)
        
    Returns:
        Cleaned and truncated text
    """
    if not text:
        return ""
    
    # Remove excessive whitespace and special characters
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)  # Remove control characters
    
    # Remove common noise patterns
    text = re.sub(r'(cookie|Cookie|COOKIE)s?\s+(policy|notice|consent|banner)[^.]{0,200}', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(javascript|JavaScript|JAVASCRIPT)[^.]{0,100}', '', text)
    text = re.sub(r'(\w)\1{4,}', r'\1\1\1', text)  # Remove repeated characters (more than 4 times)
    
    # Remove UI/navigation instructions and accessibility content
    text = re.sub(r'(press|click|tap|use|hit)\s+(the\s+)?(space\s*bar|arrow\s+keys?|enter|return|tab|escape|esc|shift|ctrl|alt|command|delete|backspace)[^.!?]{0,100}[.!?]?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(press|click|tap)\s+(space|enter|return|tab|escape|esc)[^.!?]{0,50}(again|to\s+\w+)[^.!?]{0,50}[.!?]?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(move|drag|drop|select|choose)\s+(the\s+)?item[^.!?]{0,100}[.!?]?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(keyboard|mouse|touchscreen|swipe|scroll)\s+(navigation|shortcut|control|instruction)[^.!?]{0,100}[.!?]?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(skip\s+to|jump\s+to)\s+(content|navigation|main)[^.!?]{0,50}[.!?]?', '', text, flags=re.IGNORECASE)
    
    # Remove URLs
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    
    # Remove email addresses
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', text)
    
    # Clean up again after removals
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Truncate to max_length, trying to break at sentence boundary
    if len(text) > max_length:
        text = text[:max_length]
        # Try to find last sentence boundary
        last_period = text.rfind('.')
        last_exclamation = text.rfind('!')
        last_question = text.rfind('?')
        last_boundary = max(last_period, last_exclamation, last_question)
        
        if last_boundary > max_length * 0.7:  # If we find a boundary in last 30%, use it
            text = text[:last_boundary + 1]
        else:
            text = text + "..."
    
    return text


@timeout_handler(90)  # 90 second timeout for the entire function
def _make_openai_api_call(client, model: str, prompt: str, company: str) -> str:
    """
    Make OpenAI API call with proper timeout handling.
    This function is wrapped with timeout_handler to prevent indefinite hanging.
    """
    logging.info(f"Making OpenAI API call for company: {company}")
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a data extraction expert. Return ONLY valid JSON, no additional text."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=2500,
            timeout=45  # HTTP timeout
        )
        logging.info(f"OpenAI API call completed successfully for company: {company}")
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"OpenAI API call failed: {e}")
        raise

def _validate_address_with_gpt_sync(address_text: str) -> bool:
    """
    Synchronous address validation function (internal use).
    Validate if the scraped text is a valid address using ChatGPT.
    
    Args:
        address_text: The text scraped as a potential address
        
    Returns:
        True if the text is a valid address, False otherwise
    """
    if not address_text or len(address_text.strip()) < 5:
        return False
    
    try:
        validation_prompt = f"""You are an address validation expert. Your task is to determine if the provided text is a valid physical address (postal address, business address, or location address).

A valid address should contain:
- Street name/number OR building name
- City/town/locality name
- Postal/ZIP code (optional but preferred)
- Country or region (optional but preferred)
- OR recognizable address components like "Street", "Avenue", "Road", etc. with location identifiers

Invalid examples (NOT addresses):
- Phone numbers, email addresses, or contact information alone
- Website URLs or links
- General text, descriptions, or sentences
- Navigation instructions or directions
- Social media handles or usernames
- Product names, company names, or business descriptions without location
- Random text that happens to contain numbers and words

Text to validate: "{address_text}"

Return ONLY a JSON object in this exact format:
{{
    "is_valid_address": true or false,
    "reason": "Brief explanation (one sentence)"
}}"""
        
        openai_client, _ = _get_cached_openai_client()
        response = openai_client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {"role": "system", "content": "You are an address validation expert. Return ONLY valid JSON, no additional text."},
                {"role": "user", "content": validation_prompt}
            ],
            temperature=0.3,
            max_tokens=150,
            timeout=20
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Extract JSON from response
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            json_str = response_text
        
        result = json.loads(json_str)
        is_valid = result.get("is_valid_address", False)
        
        if is_valid:
            logging.info(f"✅ Address validated: {address_text[:50]}...")
        else:
            reason = result.get("reason", "Unknown reason")
            logging.info(f"❌ Address invalid: {address_text[:50]}... Reason: {reason}")
        
        return bool(is_valid)
        
    except TimeoutError:
        logging.warning(f"Address validation timed out for: {address_text[:50]}...")
        # On timeout, be conservative and return False
        return False
    except Exception as e:
        logging.error(f"Error validating address '{address_text[:50]}...': {e}")
        # On error, be conservative and return False
        return False

def _validate_address_with_gpt_async(address_text: str, result_container: List[Optional[bool]]) -> None:
    """
    Asynchronous address validation function that runs in a separate thread.
    Stores result in result_container[0].
    
    Args:
        address_text: The text scraped as a potential address
        result_container: List to store the result (will be set to True/False when done)
    """
    try:
        result = _validate_address_with_gpt_sync(address_text)
        result_container[0] = result
    except Exception as e:
        logging.error(f"Error in async address validation: {e}")
        result_container[0] = False

def extract_products_with_gpt(data: Dict[str, Any], company_name: str, logo_urls: List[str] = None, website_url: str = '') -> Dict[str, Any]:
    """
    Extract product information from scraped website data using GPT, including product categories and best logo selection.
    
    Args:
        data: Scraped website data dictionary
        company_name: Name of the company
        logo_urls: Optional list of logo URLs to select from
        website_url: The website URL being analyzed
        
    Returns:
        Dictionary containing 'product' (main product), 'products' (list of all products),
        'product_categories' (dictionary of categories with their products), and 'selected_logo' (best logo URL)
    """
    try:
        # Extract text content from data
        text_content = data.get('text_content', '')
        if isinstance(text_content, dict):
            text_content = ' '.join(f"{k}: {v}" for k, v in text_content.items() if v)
        text_content = str(text_content or '')
        
        # Get body text and other relevant fields
        raw_body_text = data.get('body_text') or text_content or ''
        if isinstance(raw_body_text, dict):
            raw_body_text = ' '.join(f"{k}: {v}" for k, v in raw_body_text.items() if v)
        raw_body_text = str(raw_body_text).strip()
        
        # Clean and prepare the text
        body_text = _clean_body_text(raw_body_text, max_length=6000)
        
        # Get title and meta description
        title = data.get('title', '') or ''
        if not isinstance(title, str):
            title = str(title)
        title = title.strip()
        
        meta_desc = data.get('meta_description', '') or ''
        if not isinstance(meta_desc, str):
            meta_desc = str(meta_desc)
        meta_desc = meta_desc.strip()
        
        # Check if we have enough content
        total_text = (body_text + ' ' + title + ' ' + meta_desc).strip()
        if len(total_text) < 50:
            logging.warning(f"Insufficient text content for product extraction for {company_name}")
            return {
                'product': '',
                'products': [],
                'product_categories': {},
                'selected_logo': ''
            }
        
        # Prepare logo selection section if logos provided
        logo_section = ""
        if logo_urls and len(logo_urls) > 0:
            logo_list = "\n".join([f"   {i+1}. {url}" for i, url in enumerate(logo_urls)])
            logo_section = f"""
            
5. SELECT THE BEST LOGO from the following URLs:
{logo_list}

Logo Selection Criteria:
- URL contains "logo" or "brand" keyword (highest priority)
- File format preference: SVG > PNG > JPG/JPEG
- URL path suggests it's the main/official logo (e.g., in header, main logo folder)
- Avoid social media icons, favicons, or small icons
- Prefer URLs that look professional and official
"""
        
        # Create the prompt for product extraction with categories and logo selection
        prompt = f"""You are a product identification and logo selection expert. Analyze the provided website content and extract product/service information{"and select the best logo" if logo_urls else ""}.

CRITICAL LANGUAGE REQUIREMENT: 
- FIRST: Carefully detect the primary language of the website content by analyzing the text provided below
- THEN: Extract ALL products, categories, and main product in the EXACT SAME LANGUAGE as the detected website language
- Examples: If English detected → extract in English. If Swedish detected → extract in Swedish. If German detected → extract in German. If Spanish detected → extract in Spanish.
- Use the EXACT product names as they appear on the website in their original language
- DO NOT translate product names or categories to a different language

IMPORTANT: Focus on identifying the main product categories and their specific product offerings.

Company: {company_name}
Website: {website_url}
Title: {title or 'N/A'}
Meta Description: {meta_desc or 'N/A'}

Website Content:
{body_text or 'N/A'}

TASKS:
1. Identify the MAIN product or service (single most important offering) - MUST be in the EXACT SAME LANGUAGE as the detected website language
2. Identify all PRODUCT CATEGORIES (e.g., if English: 'Earbuds', 'Speakers'; if Spanish: 'Auriculares', 'Altavoces') - MUST be in the EXACT SAME LANGUAGE as the detected website language
3. For EACH category, list specific products/variants - MUST be in the EXACT SAME LANGUAGE as the detected website language
4. Include a general 'products' list with all products (flattened) - MUST be in the EXACT SAME LANGUAGE as the detected website language{logo_section}

RETURN ONLY VALID JSON in this exact format:
{{
    "detected_language": "Language code of the detected website language (e.g., 'en', 'es', 'sv', 'de', etc.)",
    "product": "Main Product/Service Name (MUST be in the EXACT SAME LANGUAGE as detected_language)",
    "products": ["Product 1", "Product 2", ... (ALL MUST be in the EXACT SAME LANGUAGE as detected_language)],
    "product_categories": {{
        "Category 1": ["Product A", "Product B", ...],
        "Category 2": ["Product C", "Product D", ...]
    }}{f',{chr(10)}    "selected_logo_number": <number from 1 to {len(logo_urls)}>' if logo_urls else ''}
}}

PRODUCT EXTRACTION RULES:
- CRITICAL: Extract ALL product names and categories in the EXACT SAME LANGUAGE as the detected website language (specified in detected_language field)
- Use the EXACT product names as they appear on the website in their original language
- DO NOT translate any product names or categories to a different language
- Use specific product names, not generic descriptions
- Include product variants/models/series (e.g., if English: "boAt Airdopes 161", "boAt Rockerz 255 Pro+")
- Group related products under appropriate categories (category names MUST also be in the detected website's language)
- Include at least 3-5 main categories if possible
- Each category should have multiple products
- The 'products' list should contain ALL products from all categories (flattened)
- Remove any duplicate products
- Sort products alphabetically within each category
- If you can't determine categories, use generic ones in the detected website's language (e.g., if English detected: 'Audio', 'Wearables'; if Spanish detected: 'Audio', 'Accesorios'; if Swedish detected: 'Ljud', 'Bärbara enheter')
- Only include products that are clearly mentioned in the content
{f'{chr(10)}LOGO SELECTION RULES:{chr(10)}- Return "selected_logo_number" as the number (1-{len(logo_urls)}) of the best logo{chr(10)}- If no logo is suitable, return 0' if logo_urls else ''}
"""
        
        model = 'gpt-4o-mini'
        
        logging.info(f"Calling OpenAI API for product extraction: {company_name}")
        if logo_urls and len(logo_urls) > 0:
            print(f"🔍 Extracting products, categories and selecting best logo ({len(logo_urls)} options) for {company_name}...")
        else:
            print(f"🔍 Extracting products and categories for {company_name}...")
        
        try:
            # Make the API call with timeout
            openai_client, _ = _get_cached_openai_client()
            response_text = _make_openai_api_call(openai_client, model, prompt, company_name)
            print(f"✅ Product extraction completed")
            
            # Parse the JSON response
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = response_text
            
            # Clean up JSON formatting
            json_str = re.sub(r'\s+', ' ', json_str)
            
            result_json = json.loads(json_str)
            
            product = result_json.get('product', '')
            products = result_json.get('products', [])
            product_categories = result_json.get('product_categories', {})
            selected_logo_number = result_json.get('selected_logo_number', 0)
            detected_language = result_json.get('detected_language', 'unknown')
            
            # Log the detected language for products
            logging.info(f"🌐 Detected language for product extraction ({company_name}): {detected_language}")
            print(f"🌐 Product extraction language: {detected_language}")
            
            # Validate and clean the results
            if not isinstance(products, list):
                products = []
            if not isinstance(product_categories, dict):
                product_categories = {}
            if not isinstance(product, str):
                product = str(product) if product else ''
            
            # Ensure all products are strings and clean them
            products = [str(p).strip() for p in products if p and str(p).strip()]
            products = list(dict.fromkeys(products))  # Remove duplicates while preserving order
            
            # Clean product categories
            cleaned_categories = {}
            for category, items in product_categories.items():
                if not category or not items or not isinstance(items, list):
                    continue
                cleaned_items = [str(i).strip() for i in items if i and str(i).strip()]
                if cleaned_items:  # Only include non-empty categories
                    cleaned_categories[str(category).strip()] = list(dict.fromkeys(cleaned_items))
            
            # Process logo selection
            selected_logo = ''
            if logo_urls and len(logo_urls) > 0:
                try:
                    logo_num = int(selected_logo_number)
                    if logo_num > 0 and logo_num <= len(logo_urls):
                        selected_logo = logo_urls[logo_num - 1]
                        logging.info(f"GPT selected logo #{logo_num}: {selected_logo}")
                        print(f"✅ Selected logo #{logo_num}")
                    else:
                        # Fallback to first logo if invalid selection
                        selected_logo = logo_urls[0] if logo_urls else ''
                        logging.warning(f"Invalid logo selection ({logo_num}), using first logo")
                        print(f"⚠️ Using first logo as fallback")
                except (ValueError, TypeError):
                    selected_logo = logo_urls[0] if logo_urls else ''
                    logging.warning(f"Could not parse logo selection, using first logo")
            
            logging.info(f"Extracted {len(products)} products across {len(cleaned_categories)} categories for {company_name}")
            
            return {
                'product': product,
                'products': products,
                'product_categories': cleaned_categories,
                'selected_logo': selected_logo
            }
            
        except TimeoutError as te:
            logging.error(f"Product extraction timed out for {company_name}: {te}")
            print(f"⏱️ Product extraction timed out")
            return {
                'product': '',
                'products': [],
                'product_categories': {},
                'selected_logo': logo_urls[0] if logo_urls else ''
            }
        except json.JSONDecodeError as jde:
            logging.error(f"Failed to parse product JSON for {company_name}: {jde}")
            print(f"❌ Failed to parse product information")
            return {
                'product': '',
                'products': [],
                'product_categories': {},
                'selected_logo': logo_urls[0] if logo_urls else ''
            }
        except Exception as e:
            logging.error(f"Error during product extraction for {company_name}: {e}")
            print(f"❌ Error extracting products: {str(e)[:100]}")
            return {
                'product': '',
                'products': [],
                'product_categories': {},
                'selected_logo': logo_urls[0] if logo_urls else ''
            }
            
    except Exception as e:
        logging.error(f"Error in extract_products_with_gpt: {e}")
        return {
            'product': '',
            'products': [],
            'product_categories': {},
            'selected_logo': logo_urls[0] if logo_urls else ''
        }


def summarize_data_with_gpt3(data: Dict[str, Any], company_name: str) -> Dict[str, Any]:
    """Create a structured website summary from scraped website data with a single API call."""
    try:
        # Validate input data
        if not data or not isinstance(data, dict):
            logging.error("Invalid data provided to summarize_data_with_gpt3")
            return {
                'success': False,
                'company_name': company_name,
                'industry': 'Unknown',
                'theme_colors': [''],
                'fonts_typography': [''],
                'formatted_fonts': {
                    'general': [''],
                    'by_element': {}
                },
                'company_info': '❌ No valid data available for analysis',
                'keywords': [],
                'address': '',
                'target_group': '',
                'logo_url': '',
                'product': '',
                'products': []
            }
        
        # Use user-provided company name (required parameter)
        company = company_name
        
        # Extract text content - handle string format directly
        text_content = data.get('text_content', '')
        if isinstance(text_content, dict):
            text_content = ' '.join(f"{k}: {v}" for k, v in text_content.items() if v)
        text_content = str(text_content or '')
        
        title = data.get('title', '') or ''
        if not isinstance(title, str):
            title = str(title)
        title = title.strip()
        
        meta_desc = data.get('meta_description', '') or ''
        if not isinstance(meta_desc, str):
            meta_desc = str(meta_desc)
        meta_desc = meta_desc.strip()
        
        # Check if we have any meaningful text content
        total_text = (text_content + ' ' + title + ' ' + meta_desc).strip()
        if len(total_text) < 50:
            logging.warning(f"Very little text content found for {company_name} (only {len(total_text)} chars)")
            print(f"⚠️ Warning: Limited text content found. Analysis may be incomplete.")
        
        # Get raw address if present - handle dict/str safely
        raw_address = (
            data.get('address')
            or data.get('company_address')
            or data.get('address_details')
            or ""
        )
        if isinstance(raw_address, dict):
            # If address is a dict, try to stringify it meaningfully
            raw_address = ', '.join(f"{v}" for v in raw_address.values() if v)
        raw_address = str(raw_address).strip()
        
        # Start address validation in parallel (non-blocking) if address is present
        address_validation_result = [None]  # Container for async result
        address_validation_thread = None
        if raw_address:
            print(f"🔍 Validating scraped address (running in parallel)...")
            address_validation_thread = threading.Thread(
                target=_validate_address_with_gpt_async,
                args=(raw_address, address_validation_result),
                daemon=True
            )
            address_validation_thread.start()
        
        # Extract keywords from scraped data
        scraped_keywords = data.get('keywords', []) or []
        if isinstance(scraped_keywords, dict):
            # If keywords is a dict, extract values
            scraped_keywords = list(scraped_keywords.values()) if scraped_keywords else []
        if not isinstance(scraped_keywords, list):
            scraped_keywords = [str(scraped_keywords)]
        
        if scraped_keywords and isinstance(scraped_keywords, list):
            keywords_text = ", ".join(str(k) for k in scraped_keywords[:15] if k)
        else:
            keywords_text = "None"
        
        # Extract theme colors - handle the new nested structure
        colors: List[str] = []
        theme_colors_obj = data.get('theme_colors') or {}
        
        if isinstance(theme_colors_obj, dict):
            # Handle new format: {"all_colors": [...]}
            if 'all_colors' in theme_colors_obj:
                all_colors = theme_colors_obj['all_colors']
                if isinstance(all_colors, list):
                    colors.extend([str(c).strip() for c in all_colors[:6] if c])
            # Also handle old format for backward compatibility
            if theme_colors_obj.get('theme_color'):
                colors.append(str(theme_colors_obj['theme_color']).strip())
            if isinstance(theme_colors_obj.get('primary_colors'), list):
                colors.extend([str(c).strip() for c in theme_colors_obj['primary_colors'][:6] if c])
            if isinstance(theme_colors_obj.get('most_frequent_colors'), list):
                colors.extend([str(c).strip() for c in theme_colors_obj['most_frequent_colors'][:6] if c])
        elif isinstance(theme_colors_obj, list):
            # Direct list format
            colors.extend([str(c).strip() for c in theme_colors_obj[:6] if c])

        if not colors:
            # Fallback to other possible color fields
            fallback = data.get('color') or data.get('dominant_colors') or data.get('primary_colors') or []
            colors.extend(_clean_list(fallback, 6))

        # Deduplicate preserving order and ensure exactly 6 colors
        seen = set()
        unique_colors: List[str] = []
        for c in colors:
            if c and c not in seen:
                seen.add(c)
                unique_colors.append(c)
            if len(unique_colors) >= 6:
                break
        
        # Pad with default colors if needed
        default_colors = ['']
        for default_color in default_colors:
            if len(unique_colors) >= 6:
                break
            if default_color not in unique_colors:
                unique_colors.append(default_color)
        
        theme_colors = unique_colors[:6]
        
        # Extract fonts information - handle both list and dict formats
        fonts_info = data.get('fonts', [])
        element_fonts_info = data.get('element_fonts', {})
        
        all_fonts = []
        
        # Handle direct list format (new format from your scanner)
        if isinstance(fonts_info, list):
            all_fonts.extend(fonts_info[:5])
        # Handle dict format (old format)
        elif isinstance(fonts_info, dict):
            main_fonts = fonts_info.get('main_fonts', [])[:5]
            system_fonts = fonts_info.get('system_fonts', [])[:3]
            all_fonts.extend(main_fonts + system_fonts)
        
        # Also extract from element_fonts
        if isinstance(element_fonts_info, dict):
            for element, fonts_list in element_fonts_info.items():
                if isinstance(fonts_list, list):
                    all_fonts.extend(fonts_list[:2])  # Take top 2 from each element
                elif isinstance(fonts_list, str):
                    all_fonts.append(fonts_list)
        
        # Validate and clean all fonts
        all_fonts = _validate_and_clean_fonts(all_fonts)
        
        # If no valid fonts found, use fallback fonts
        if not all_fonts:
            all_fonts = ['']
        
        # Store element_fonts for detailed output
        element_fonts = {}
        if isinstance(element_fonts_info, dict):
            for element, fonts_list in element_fonts_info.items():
                if isinstance(fonts_list, list) and fonts_list:
                    element_fonts[element] = _validate_and_clean_fonts(fonts_list)
                elif isinstance(fonts_list, str) and fonts_list:
                    element_fonts[element] = _validate_and_clean_fonts([fonts_list])
        
        # Clean body text - handle dict case
        raw_body_text = data.get('body_text') or text_content or ''
        if isinstance(raw_body_text, dict):
            raw_body_text = ' '.join(f"{k}: {v}" for k, v in raw_body_text.items() if v)
        raw_body_text = str(raw_body_text).strip()
        body_text_snippet = _clean_body_text(raw_body_text, max_length=5000) or 'No content available'
        
        # Additional safety: ensure all text fields are properly sanitized
        if not isinstance(title, str):
            title = str(title)
        title = re.sub(r'\s+', ' ', title.strip())[:200] or 'N/A'
        
        # Log data quality metrics
        logging.info(f"Data quality for {company}: text_length={len(body_text_snippet)}, "
                    f"colors={len(theme_colors)}, fonts={len(all_fonts)}, keywords={len(scraped_keywords)}")

        # Wait for address validation to complete (with timeout) before using address in prompt
        validated_address = raw_address
        if address_validation_thread and address_validation_thread.is_alive():
            # Wait up to 25 seconds for validation (should be done by then)
            address_validation_thread.join(timeout=25.0)
            if address_validation_result[0] is not None:
                is_valid = address_validation_result[0]
                if not is_valid:
                    logging.warning(f"Invalid address detected and filtered out: {raw_address[:100]}...")
                    print(f"⚠️  Scraped text is not a valid address - filtering it out")
                    validated_address = ""  # Set to empty if invalid
                else:
                    print(f"✅ Address validated successfully")
            else:
                # Validation still running or timed out - use original address but log warning
                logging.warning(f"Address validation did not complete in time, using original address")
                print(f"⏱️  Address validation still running, proceeding with original address")
        elif address_validation_result[0] is not None:
            # Validation completed already
            is_valid = address_validation_result[0]
            if not is_valid:
                logging.warning(f"Invalid address detected and filtered out: {raw_address[:100]}...")
                print(f"⚠️  Scraped text is not a valid address - filtering it out")
                validated_address = ""
            else:
                print(f"✅ Address validated successfully")

        # Programmatically detect language from scraped text (before GPT)
        detected_lang_programmatic = 'en'  # Default fallback
        if LANGDETECT_AVAILABLE:
            try:
                # Combine title, meta description, and body text for better detection
                text_for_detection = f"{title} {meta_desc} {body_text_snippet[:2000]}".strip()
                if len(text_for_detection) > 50:  # Need minimum text for detection
                    detected_lang_programmatic = detect(text_for_detection)
                    logging.info(f"🌐 Programmatic language detection: {detected_lang_programmatic}")
                    print(f"🌐 Programmatically detected language: {detected_lang_programmatic}")
            except Exception as e:
                logging.warning(f"Programmatic language detection failed: {e}")
                detected_lang_programmatic = 'en'
        else:
            logging.info("langdetect not available, relying on GPT for language detection")

        # Build language hint for prompt (use language code directly)
        lang_hint = f"appears to be in language code: {detected_lang_programmatic}" if detected_lang_programmatic else "could not be programmatically detected"

        prompt = f"""You are a summary and data extraction expert. Analyze the provided data and return ONLY valid JSON.

CRITICAL LANGUAGE REQUIREMENT: 
- PROGRAMMATIC DETECTION HINT: The website content has been programmatically analyzed and {lang_hint}
- FIRST: Carefully detect the primary language of the website content by analyzing the text provided below. Use your own analysis to determine the correct language, even if it differs from the programmatic hint.
- THEN: Write ALL output fields (summary, industry, keywords, address, target_group, tone_analysis) in the EXACT SAME LANGUAGE as the detected website language
- DO NOT translate or change the language. Use the website's original language for ALL responses.
- IMPORTANT: If the text is clearly in English, return "en" as detected_language, even if other hints suggest otherwise.
- If the detected language is not in the common list (en, es, sv, de, fr, etc.), use the appropriate ISO 639-1 language code (two letters).

IMPORTANT: Focus on the most relevant information. Ignore any noise, cookie notices, or irrelevant text.

Tasks:
1. Detect the language of the website content.
2. Write a comprehensive 8-12 sentence summary of the company's business, main offerings, services, products, unique value propositions, and key differentiators in the SAME LANGUAGE as the website content. Include details about their business model, main features, and what makes them stand out.
3. Identify the industry/sector (MUST be in the EXACT SAME language as the detected website language).
4. Select 10 most relevant business keywords (MUST be in the EXACT SAME language as the detected website language, remove duplicates).
5. Validate and format the address if present (otherwise return empty string).
6. Identify the target audience (MUST be in the EXACT SAME language as the detected website language).
7. Analyze the tone of the website content in detail (4-5 sentences). Your analysis MUST be in the EXACT SAME language as the detected website language. Consider these specific aspects:
   - Language style: Is it casual/conversational, formal/corporate, technical/jargon-heavy, or playful/creative?
   - Emotional appeal: Does it use urgency, fear, excitement, trust, empathy, or inspiration?
   - Audience approach: Is it authoritative/expert, friendly/peer-to-peer, educational, or sales-driven?
   - Sentence structure: Short and punchy vs. long and descriptive?
   - Word choice patterns: Action-oriented, benefit-focused, problem-solving, aspirational, etc.
   - Overall personality: Bold/aggressive, supportive/nurturing, innovative/futuristic, traditional/reliable, etc.
   
   CRITICAL RULES:
   - The tone analysis MUST be in the EXACT SAME language as the detected website language
   - DO NOT quote or mention any specific phrases, words, or text from the website
   - DO NOT use phrases like "phrases like", "words such as", "mentions", "states", "says", etc.
   - Only describe the STYLE and CHARACTERISTICS of the tone
   - Focus on HOW they communicate, not WHAT they say

DATA:
Company: {company}
Title: {title or 'N/A'}
Keywords: {keywords_text}
Address: {validated_address}
Content: {body_text_snippet or 'N/A'}

RETURN ONLY THIS JSON FORMAT:
{{
    "detected_language": "FIRST: Detect and specify the language code (e.g., 'en' for English, 'es' for Spanish, 'sv' for Swedish, 'de' for German, etc.)",
    "summary": "Detailed company summary here (8-12 sentences with comprehensive information). MUST be written in the EXACT SAME LANGUAGE as detected_language.",
    "industry": "Industry name (MUST be in the EXACT SAME LANGUAGE as detected_language)",
    "keywords": ["All 10 keywords MUST be in the EXACT SAME LANGUAGE as detected_language"],
    "address": "Formatted address or empty string",
    "target_group": "Detailed target audience description (MUST be in the EXACT SAME LANGUAGE as detected_language)",
    "tone_analysis": "4-5 sentence detailed analysis (MUST be in the EXACT SAME LANGUAGE as detected_language). Describe only the STYLE and CHARACTERISTICS of communication. Focus on HOW they communicate, not WHAT they say."
}}
"""
        model = 'gpt-4o-mini'
        
        logging.info(f"Initiating OpenAI API call for company: {company} with model: {model}")
        logging.info(f"Prompt length: {len(prompt)} characters")
        print(f"⏳ Calling OpenAI API (this may take up to 90 seconds)...")
        
        try:
            # Use the timeout-wrapped API call function
            openai_client, _ = _get_cached_openai_client()
            response_text = _make_openai_api_call(openai_client, model, prompt, company)
            print(f"✅ API call completed successfully")
        except TimeoutError as te:
            logging.error(f"OpenAI API call timed out for company {company}: {te}")
            print(f"⏱️ API call timed out - returning partial results")
            
            return {
                'success': True,
                'company_name': company_name,
                'industry': 'Unknown',
                'theme_colors': theme_colors,
                'fonts_typography': all_fonts,
                'formatted_fonts': {
                    'general': all_fonts,
                    'by_element': element_fonts
                },
                'company_info': f"Analysis timeout - API took too long to respond. Colors and fonts detected successfully.",
                'keywords': scraped_keywords[:10] if scraped_keywords else [],
                'address': '',
                'target_group': ''
            }
        except Exception as api_e:
            logging.error(f"OpenAI API call failed for company {company}: {api_e}")
            print(f"❌ API call failed: {str(api_e)[:100]}")
            
            return {
                'success': False,
                'company_name': company_name,
                'industry': 'Unknown',
                'theme_colors': theme_colors,
                'fonts_typography': all_fonts,
                'formatted_fonts': {
                    'general': all_fonts,
                    'by_element': element_fonts
                },
                'company_info': f"❌ Error during OpenAI API call: {str(api_e)[:200]}",
                'keywords': scraped_keywords[:10] if scraped_keywords else [],
                'address': '',
                'target_group': ''
            }

        # Process the response
        try:
            logging.info(f"Attempting to parse JSON response for company: {company}")
            
            # Try to extract JSON from response (handle cases where GPT adds markdown)
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = response_text
            
            # Clean up common JSON formatting issues
            json_str = re.sub(r'\s+', ' ', json_str)
            
            # Parse JSON returned by GPT
            result_json = json.loads(json_str)
            
            if isinstance(result_json, list) and len(result_json) > 0:
                result_json = result_json[0]

            summary_text = result_json.get("summary", "")
            industry = result_json.get("industry", "Unknown")
            refined_keywords = result_json.get("keywords", [])
            address = result_json.get("address", "")
            # Handle address validation results - prioritize GPT's extraction unless validation explicitly failed
            if address_validation_result[0] is not None:
                # Validation completed
                if not address_validation_result[0]:
                    # Validation explicitly said invalid - use empty string
                    address = ""
                # If validation said valid (True), keep GPT's address (it should match validated_address)
            elif not address and validated_address:
                # Validation still running or timed out, but we have a validated_address from scraping
                # Use the scraped address if GPT didn't return one
                address = validated_address
            # If validated_address is empty (validation failed) but GPT returned an address,
            # we already filtered it out above, so no need to check again
            # If GPT has an address and validation hasn't explicitly failed, keep GPT's address
            target_group = result_json.get("target_group", "")
            tone_analysis = result_json.get("tone_analysis", "Tone analysis not available")
            detected_language = result_json.get("detected_language", "unknown")
            
            # Validate and potentially override GPT's language detection with programmatic detection
            if LANGDETECT_AVAILABLE and detected_lang_programmatic:
                # Normalize language codes (handle cases like "en-US" -> "en")
                gpt_lang_normalized = detected_language.lower().split('-')[0] if detected_language else 'unknown'
                programmatic_lang_normalized = detected_lang_programmatic.lower().split('-')[0]
                
                # If there's a significant mismatch, use programmatic detection (more reliable for English)
                if gpt_lang_normalized != programmatic_lang_normalized:
                    # Special case: if programmatic says English but GPT says Swedish/German/etc, trust programmatic
                    if programmatic_lang_normalized == 'en' and gpt_lang_normalized in ['sv', 'de', 'no', 'da']:
                        logging.warning(f"⚠️ Language mismatch: GPT detected '{detected_language}' but programmatic detection says '{detected_lang_programmatic}'. Using programmatic detection (English).")
                        print(f"⚠️ Language mismatch detected. GPT said '{detected_language}', but programmatic detection says '{detected_lang_programmatic}'. Using programmatic detection.")
                        detected_language = detected_lang_programmatic
                    # If programmatic says non-English and GPT says English, trust GPT (might be mixed content)
                    elif programmatic_lang_normalized != 'en' and gpt_lang_normalized == 'en':
                        logging.info(f"ℹ️ Language mismatch: Programmatic says '{detected_lang_programmatic}' but GPT says 'en'. Trusting GPT (might be mixed content).")
                        detected_language = 'en'
                    else:
                        # For other mismatches, prefer programmatic but log it
                        logging.info(f"ℹ️ Language mismatch: GPT detected '{detected_language}' vs programmatic '{detected_lang_programmatic}'. Using GPT's detection.")
                else:
                    logging.info(f"✅ Language detection matches: Both GPT and programmatic detected '{detected_language}'")
            
            # Log the final detected language
            logging.info(f"🌐 Final detected website language for {company}: {detected_language}")
            print(f"🌐 Detected website language: {detected_language}")
            
            # Validate that we got meaningful data
            if not summary_text or len(summary_text) < 20:
                logging.warning(f"Summary too short for company {company}, using fallback")
                summary_text = f"Analysis of {company} based on available website data."
            
            logging.info(f"Successfully parsed JSON for company: {company}")

        except json.JSONDecodeError as jde:
            logging.error(f"JSONDecodeError for company {company}: {jde}. Response text: {response_text[:500]}")
            # Fallback if GPT returns plain text or malformed JSON
            summary_text = response_text[:500] if len(response_text) > 500 else response_text
            industry = "Unknown"
            refined_keywords = scraped_keywords[:10] if scraped_keywords else []
            address = ""
            target_group = ""
        except Exception as e:
            logging.error(f"Unexpected error during JSON parsing for company {company}: {e}. Response text: {response_text[:500]}")
            summary_text = f"Unable to generate summary for {company}. Please check the logs for details."
            industry = "Unknown"
            refined_keywords = scraped_keywords[:10] if scraped_keywords else []
            address = ""
            target_group = ""

        # Format fonts in the requested structure
        formatted_fonts = {
            'general': all_fonts,
            'by_element': element_fonts
        }
        
        # NOTE: Product extraction and logo selection are now handled separately 
        # in website_analyzer.py to combine them in a single API call
        
        return {
            'success': True,
            'company_name': company,
            'industry': industry,
            'theme_colors': theme_colors,
            'fonts_typography': all_fonts,
            'formatted_fonts': formatted_fonts,
            'company_info': summary_text,
            'keywords': refined_keywords,
            'address': address,
            'target_group': target_group,
            'tone_analysis': tone_analysis
        }

    except Exception as e:
        logging.error(f"Error in summarize_data_with_gpt3: {e}")
        # Return a basic response with the error message
        return {
            'success': False,
            'company_name': company_name,
            'industry': '',
            'theme_colors': [],
            'fonts_typography': [],
            'formatted_fonts': {
                'general': [],
                'by_element': {}
            },
            'company_info': f"❌ Error generating summary: {str(e)}",
            'keywords': [],
            'address': '',
            'target_group': ''
        }

def format_company_info(company_data: Dict[str, Any]) -> str:
    """
    Format the company data as JSON string.
    
    Args:
        company_data: Dictionary containing company information
        
    Returns:
        JSON string with formatted company info
    """
    import json
    return json.dumps(company_data, indent=4, ensure_ascii=False)


def scrape_and_summarize_website(website_url_or_data: str, company_name: str = None, is_json: bool = False) -> Dict[str, Any]:
    """
    Complete workflow: scrape website data and generate structured AI summary.
    
    Args:
        website_url_or_data: The URL of the website to scrape and summarize, or pre-scraped JSON data
        company_name: User-provided company name (required if is_json is False)
        is_json: If True, website_url_or_data should be a JSON string of pre-scraped data
        
    Returns:
        Dictionary containing structured company information
    """
    try:
        if is_json:
            # If input is JSON string, parse it
            import json
            try:
                scraped_data = json.loads(website_url_or_data)
                if not company_name and 'url' in scraped_data:
                    from urllib.parse import urlparse
                    parsed_url = urlparse(scraped_data['url'])
                    company_name = parsed_url.netloc.replace('www.', '').split('.')[0].title()
                print("📝 Processing pre-scraped website data...")
            except json.JSONDecodeError:
                return {
                    'company_name': company_name or 'Unknown Company',
                    'theme_colors': [],
                    'company_info': "❌ Error: Invalid JSON data provided"
                }
        else:
            # If input is a URL, scrape it
            if not company_name:
                from urllib.parse import urlparse
                parsed_url = urlparse(website_url_or_data)
                company_name = parsed_url.netloc.replace('www.', '').split('.')[0].title()
                
            print(f"🔍 Scraping website: {website_url_or_data}")
            from scan import scrape_website_data
            scraped_data = scrape_website_data(website_url_or_data)
        
        if not scraped_data or 'error' in scraped_data:
            error_msg = scraped_data.get('error', 'Unknown scraping error') if scraped_data else 'Failed to process website data'
            # Try to extract colors even on error
            theme_colors = []
            if isinstance(scraped_data, dict):
                tc = scraped_data.get('theme_colors', {})
                if isinstance(tc, dict) and 'all_colors' in tc:
                    theme_colors = tc['all_colors'][:6]
            
            return {
                'company_name': company_name or 'Unknown Company',
                'theme_colors': theme_colors,
                'company_info': f"❌ Error: {error_msg}"
            }
        
        print("📝 Generating AI summary...")
        company_info = summarize_data_with_gpt3(scraped_data, company_name or 'The Company')
        
        print("✅ Summary generated successfully!")
        return company_info
        
    except ImportError as e:
        return {
            'company_name': company_name or 'Unknown Company',
            'theme_colors': [],
            'company_info': f"❌ Import Error: {str(e)}. Make sure all dependencies are installed."
        }
    except Exception as e:
        return {
            'company_name': company_name or 'Unknown Company',
            'theme_colors': [],
            'company_info': f"❌ Error during processing: {str(e)}"
        }

def main():
    """Main function for command-line usage"""
    import sys
    import json
    
    try:
        # Check if we're getting piped input from scan.py
        import sys
        if not sys.stdin.isatty():
            # Read JSON data from stdin
            json_data = sys.stdin.read().strip()
            if json_data:
                try:
                    # Validate JSON
                    parsed_data = json.loads(json_data)
                    # If we got here, it's valid JSON
                    result = scrape_and_summarize_website(json_data, is_json=True)
                    # Print JSON output
                    print(json.dumps(result, indent=4, ensure_ascii=False))
                    return
                except json.JSONDecodeError:
                    print("❌ Error: Invalid JSON input from stdin")
                    return
        
        # If no piped input, check command line arguments
        if len(sys.argv) > 2:
            website_url = sys.argv[1]
            company_name = sys.argv[2] if len(sys.argv) > 2 else None
        else:
            website_url = input("Enter website URL to scrape and summarize: ").strip()
            company_name = input("Enter company name: ").strip()
        
        if not website_url:
            print("❌ No URL provided")
            return
        
        if not company_name:
            # Try to extract company name from URL
            from urllib.parse import urlparse
            parsed_url = urlparse(website_url)
            company_name = parsed_url.netloc.replace('www.', '').split('.')[0].title()
            print(f"ℹ️  Using company name derived from URL: {company_name}")
        
        print(f"\n{'='*80}\n🔍 Starting analysis for: {company_name}\n{'='*80}")
        
        # Process the website
        result = scrape_and_summarize_website(website_url, company_name)
        
        # Print the results
        print("\n" + "="*80)
        print("📋 FINAL SUMMARY")
        print("="*80)
        print(format_company_info(result))
        
    except KeyboardInterrupt:
        print("\n❌ Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ An error occurred: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()




