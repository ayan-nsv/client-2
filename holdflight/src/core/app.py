# Placeholder file - Copy your holdflight/src/core/app.py content here
# Main FastAPI application (1641 lines)

import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, File, UploadFile, Form, Body
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Union, Dict, Any
from urllib.parse import urlparse, quote

# Load environment variables from .env file
load_dotenv()
from holdflight.src.core.website_analyzer import WebsiteAnalyzer
from holdflight.src.scraping.images_scraping import scrape_website_images
from holdflight.src.ai.chatgpt import ImageAnalyzer
from holdflight.src.image.text_placement import place_text_on_image
from holdflight.src.ai.text_placement_suggestion import (
    build_brand_context,
    get_logo_placement_suggestion,
    get_text_placement_suggestions,
)
from holdflight.src.color.colors import analyze_website_theme_and_fonts
from holdflight.src.scraping.logo_scarping import scrape_logo
from holdflight.src.utils.fonts_matching import match_scraped_fonts_regular_only
from holdflight.src.image.colors_from_favicon import extract_logo_colors, extract_colors_from_image_data
from datetime import datetime, timedelta
import io
import sys
import re
import base64
import requests
from holdflight.src.config.firebase_con import get_bucket, init_firebase
from holdflight.src.config.firebase_con import get_bucket
import uuid
from io import BytesIO
from holdflight.src.utils.chrome_options import safe_get, safe_post, safe_put, validate_public_url


def _get_firebase_bucket():
    return get_bucket()


def _normalize_section_key(section_name, existing_keys):
    """Convert section headings into snake_case keys with predefined mappings."""
    if not section_name:
        section_name = "section"

    normalized = re.sub(r'\s+', ' ', section_name).strip().lower()

    mappings = {
        "image types & animation": "image_types_and_animation",
        "image types and animation": "image_types_and_animation",
        "theme / atmosphere": "theme_and_atmosphere",
        "theme and atmosphere": "theme_and_atmosphere",
        "environment / setting": "environment_settings",
        "environment and setting": "environment_settings",
        "subjects / people": "subjects_and_people",
        "subjects and people": "subjects_and_people",
        "technology elements": "technology_elements",
        "lighting & color tone": "lighting_and_color_tone",
        "lighting and color tone": "lighting_and_color_tone",
        "composition & style": "composition_and_style",
        "composition and style": "composition_and_style",
        "keywords for ai image generation": "keywords_for_ai_image_generation",
    }

    if normalized in mappings:
        base_key = mappings[normalized]
    else:
        base_key = re.sub(r'[^a-z0-9]+', '_', normalized).strip('_') or "section"

    key = base_key
    counter = 2
    while key in existing_keys:
        key = f"{base_key}_{counter}"
        counter += 1

    return key


def upload_logo_or_favicon_to_firebase(image_url, folder_name='user_uploads', file_type='logo'):
    """
    Upload a logo or favicon to Firebase Storage (simpler version, no data URI needed).
    
    Args:
        image_url: URL of the logo/favicon to download
        folder_name: Base folder name in Firebase Storage (default: 'user_uploads')
        file_type: 'logo' or 'favicon' to determine subfolder
        
    Returns:
        str: Firebase Storage URL of the uploaded file, or None if failed
    """
    try:
        print(f"📥 Downloading {file_type} from: {image_url}")
        
        # Skip Google favicon service URLs (they're already accessible)
        if 'google.com/s2/favicons' in image_url:
            print(f"   ℹ️ Skipping Google favicon service URL (already accessible)")
            return image_url
        
        # Download the image
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/avif,image/svg+xml,image/*,*/*;q=0.8',
        }
        response = safe_get(requests, image_url, headers=headers, timeout=30, stream=True)
        response.raise_for_status()
        
        # Get image data
        image_data = response.content
        if not image_data:
            print(f"❌ Empty {file_type} data for {image_url}")
            return image_url  # Return original URL as fallback
        
        print(f"✅ Downloaded {len(image_data)} bytes")
        
        # Determine file extension from URL or content type
        content_type = response.headers.get('content-type', '')
        if 'svg' in content_type or image_url.lower().endswith('.svg'):
            ext = '.svg'
        elif 'jpeg' in content_type or 'jpg' in content_type or image_url.lower().endswith(('.jpg', '.jpeg')):
            ext = '.jpg'
        elif 'png' in content_type or image_url.lower().endswith('.png'):
            ext = '.png'
        elif 'webp' in content_type or image_url.lower().endswith('.webp'):
            ext = '.webp'
        elif 'ico' in content_type or image_url.lower().endswith('.ico'):
            ext = '.ico'
        else:
            # Try to get extension from URL
            ext = os.path.splitext(image_url.split('?')[0])[1] or '.png'
        
        # Generate unique filename
        filename = f"{uuid.uuid4()}{ext}"
        subfolder = 'logos' if file_type == 'logo' else 'favicons'
        firebase_path = f"{folder_name}/{subfolder}/{filename}"
        
        print(f"📤 Uploading to Firebase Storage path: {firebase_path}")
        
        # Upload to Firebase Storage
        bucket = _get_firebase_bucket()
        blob = bucket.blob(firebase_path)
        
        # Generate download token for URL
        import uuid as uuid_module
        download_token = str(uuid_module.uuid4())
        
        # Set metadata with download token
        blob.metadata = {
            'firebaseStorageDownloadTokens': download_token
        }
        
        blob.upload_from_string(image_data, content_type=content_type or 'image/png')
        
        print(f"✅ {file_type.capitalize()} uploaded to Firebase Storage")
        
        # Try to make public (may fail with uniform bucket-level access)
        try:
            blob.make_public()
            blob.reload()
        except Exception as e:
            print(f"⚠️ Warning: Could not make blob public: {str(e)}")
        
        # Construct Firebase URL with token
        bucket_name = bucket.name
        from urllib.parse import quote
        encoded_path = quote(firebase_path, safe='')
        firebase_url = f"https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o/{encoded_path}?alt=media&token={download_token}"
        
        print(f"✅ Firebase Storage URL: {firebase_url}")
        return firebase_url
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error downloading {file_type} {image_url}: {str(e)}")
        return image_url  # Return original URL as fallback
    except Exception as e:
        print(f"❌ Error uploading {file_type} {image_url} to Firebase: {str(e)}")
        import traceback
        traceback.print_exc()
        return image_url  # Return original URL as fallback


def _normalize_image_content_type(content_type: Optional[str]) -> str:
    if not content_type or content_type == "application/octet-stream":
        return "image/jpeg"
    return (content_type.split(";")[0]).strip().lower() or "image/jpeg"


def _upload_bytes_to_firebase_storage(
    image_data: bytes,
    firebase_path: str,
    content_type: str,
) -> Optional[Dict[str, str]]:
    """
    Upload raw bytes to Firebase Storage and resolve a public-style download URL.
    Shared by upload_image_to_firebase and text overlay uploads.
    """
    if not image_data:
        return None
    ct = _normalize_image_content_type(content_type)
    try:
        print(f"📤 Uploading to Firebase Storage path: {firebase_path}")
        bucket = _get_firebase_bucket()
        blob = bucket.blob(firebase_path)

        download_token = str(uuid.uuid4())
        blob.metadata = {"firebaseStorageDownloadTokens": download_token}
        blob.upload_from_string(image_data, content_type=ct)

        print("✅ Image uploaded to Firebase Storage")

        try:
            blob.make_public()
            blob.reload()
        except Exception as e:
            print(f"⚠️ Warning: Could not make blob public: {str(e)}")

        firebase_url = None
        try:
            firebase_url = blob.public_url
            if firebase_url and "firebasestorage.googleapis.com" in firebase_url:
                print(f"✅ Got public URL: {firebase_url}")
        except Exception as e:
            print(f"⚠️ Could not get public_url: {str(e)}")

        if not firebase_url or "firebasestorage.googleapis.com" not in firebase_url:
            try:
                firebase_url = blob.generate_signed_url(
                    expiration=datetime.now() + timedelta(days=3650),
                    method="GET",
                )
                print(f"✅ Generated signed URL: {firebase_url}")
            except Exception as e:
                print(f"⚠️ Could not generate signed URL: {str(e)}")

        if not firebase_url or "firebasestorage.googleapis.com" not in firebase_url:
            try:
                bucket_name = bucket.name
                encoded_path = quote(firebase_path, safe="")
                try:
                    blob.reload()
                except Exception:
                    pass
                token = download_token
                try:
                    if hasattr(blob, "metadata") and blob.metadata:
                        metadata_token = blob.metadata.get("firebaseStorageDownloadTokens")
                        if metadata_token:
                            token = metadata_token
                except Exception as e:
                    print(f"⚠️ Could not retrieve token from metadata: {str(e)}")
                firebase_url = (
                    f"https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o/"
                    f"{encoded_path}?alt=media&token={token}"
                )
                print(f"✅ Constructed Firebase URL with token: {firebase_url}")
            except Exception as e:
                print(f"❌ Could not construct URL manually: {str(e)}")
                return None

        if not firebase_url:
            print("❌ Failed to get Firebase Storage URL")
            return None

        try:
            encoded_image = base64.b64encode(image_data).decode("utf-8")
            data_uri = f"data:{ct};base64,{encoded_image}"
        except Exception as e:
            print(f"⚠️ Warning: Could not create data URI: {str(e)}")
            data_uri = firebase_url

        print(f"✅ Final Firebase Storage URL: {firebase_url}")
        return {"firebase_url": firebase_url, "data_uri": data_uri}

    except Exception as e:
        print(f"❌ Error uploading bytes to Firebase: {str(e)}")
        import traceback

        traceback.print_exc()
        return None


def upload_image_to_firebase(image_url, folder_name='user_uploads'):
    """
    Download an image from a URL and upload it to Firebase Storage.
    
    Args:
        image_url: URL of the image to download
        folder_name: Folder name in Firebase Storage (default: 'user_uploads')
        
    Returns:
        dict: {
            'firebase_url': str,  # Firebase Storage URL
            'data_uri': str       # Base64 data URI for direct use in OpenAI API
        } or None if failed
    """
    try:
        print(f"📥 Downloading image from: {image_url}")
        # Download the image
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/avif,image/svg+xml,image/*,*/*;q=0.8',
        }
        response = safe_get(requests, image_url, headers=headers, timeout=30, stream=True)
        response.raise_for_status()
        
        # Get image data
        image_data = response.content
        if not image_data:
            print(f"❌ Empty image data for {image_url}")
            return None
        
        print(f"✅ Downloaded {len(image_data)} bytes")
        
        # Determine file extension from URL or content type
        content_type = response.headers.get('content-type', '')
        if 'jpeg' in content_type or 'jpg' in content_type:
            ext = '.jpg'
        elif 'png' in content_type:
            ext = '.png'
        elif 'webp' in content_type:
            ext = '.webp'
        else:
            # Try to get extension from URL
            ext = os.path.splitext(image_url.split('?')[0])[1] or '.jpg'
        
        # Generate unique filename
        filename = f"{uuid.uuid4()}{ext}"
        firebase_path = f"{folder_name}/{filename}"

        ct_hdr = response.headers.get("content-type", "")
        if "png" in ct_hdr or ext == ".png":
            ct_use = "image/png"
        elif "webp" in ct_hdr or ext == ".webp":
            ct_use = "image/webp"
        else:
            ct_use = "image/jpeg"

        uploaded = _upload_bytes_to_firebase_storage(image_data, firebase_path, ct_use)
        if not uploaded:
            return None
        print("✅ Created data URI for OpenAI API")
        return uploaded
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error downloading image {image_url}: {str(e)}")
        import traceback
        traceback.print_exc()
        return None
    except Exception as e:
        print(f"❌ Error uploading image {image_url} to Firebase: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def _extract_subsections(section_text):
    """
    Extract subsections formatted with bold headings (e.g., **Title**: text)
    and return a dictionary mapping normalized keys to their content.
    """
    if not section_text:
        return {}
    pattern = re.compile(r'\*\*(.+?)\*\*\s*:?\s*(.*?)(?=(\*\*.+?\*\*)|$)', re.DOTALL)

    subsections = {}
    for match in pattern.finditer(section_text):
        title = match.group(1).strip()
        content = match.group(2).strip()

        if not title or not content:
            continue

        normalized_key = _normalize_section_key(title, subsections.keys())
        subsections[normalized_key] = content

    return subsections


def convert_analysis_text_to_dict(
    analysis_text,
    *,
    enforce_canonical_keys=False,
    include_subsections=True
):
    """
    Convert the markdown-style analysis text into a structured dictionary.
    
    Args:
        analysis_text: The raw analysis text returned by the model.
        enforce_canonical_keys: If True, headings are mapped to the predefined
            English snake_case keys in their canonical order.
        include_subsections: If True, bolded subheadings within sections are
            extracted into nested dictionaries; otherwise sections remain strings.
    """
    if not analysis_text or not isinstance(analysis_text, str):
        return {}

    sections = {}
    current_section = None

    for line in analysis_text.splitlines():
        stripped = line.strip()

        if not stripped:
            continue

        hash_heading = re.match(r'^#{1,6}\s*(.+)$', stripped)
        bold_heading = re.match(r'^\*\*(.+?)\*\*$', stripped)

        if hash_heading:
            current_section = hash_heading.group(1).strip()
            sections[current_section] = []
            continue

        if bold_heading and not stripped.startswith('-'):
            current_section = bold_heading.group(1).strip()
            sections[current_section] = []
            continue

        if current_section:
            cleaned_line = stripped
            if cleaned_line.startswith('- '):
                cleaned_line = cleaned_line[2:].strip()
            elif cleaned_line.startswith('•'):
                cleaned_line = cleaned_line[1:].strip()

            if cleaned_line:
                sections[current_section].append(cleaned_line)

    normalized_sections = {}
    canonical_order = [
        "image_types_and_animation",
        "theme_and_atmosphere",
        "environment_settings",
        "subjects_and_people",
        "technology_elements",
        "lighting_and_color_tone",
        "composition_and_style",
        "keywords_for_ai_image_generation",
    ]

    canonical_index = 0

    for key, value in sections.items():
        if not value:
            continue

        section_text = ' '.join(part.strip() for part in value if part.strip())
        cleaned_value = section_text.strip()
        if not cleaned_value:
            continue
        if enforce_canonical_keys and canonical_index < len(canonical_order):
            while (
                canonical_index < len(canonical_order)
                and canonical_order[canonical_index] in normalized_sections
            ):
                canonical_index += 1
            if canonical_index < len(canonical_order):
                normalized_key = canonical_order[canonical_index]
                canonical_index += 1
            else:
                normalized_key = _normalize_section_key(key, normalized_sections.keys())
        else:
            normalized_key = _normalize_section_key(key, normalized_sections.keys())

        if include_subsections:
            subsections = _extract_subsections(cleaned_value)
            if subsections:
                normalized_sections[normalized_key] = subsections
                continue

        normalized_sections[normalized_key] = cleaned_value

    return normalized_sections

# Pydantic models for request bodies
class AnalyzeRequest(BaseModel):
    url: str

class ImageWorkflowRequest(BaseModel):
    url: str
    max_images: Optional[int] = Field(default=10, ge=1, le=50)
    language: Optional[str] = Field(
        default='auto',
        description="Use 'auto' to detect from the page, or an ISO 639-1 code (e.g. de) or common English name (e.g. german).",
    )

class UserImageryRequest(BaseModel):
    image_urls: List[str] = Field(..., min_items=1, max_items=10)
    language: Optional[str] = Field(default='en')

class TextPlacementRequest(BaseModel):
    """
    Text and logo share the same anchor convention: normalized [0..1] or pixel coords for the **center**.

    Provide non-empty ``text`` with ``x``/``y``, and/or ``logo_url`` with ``logo_x``/``logo_y``.
    ``text_placement_body`` from POST ``/textplacementsuggestions`` includes logo fields when a logo exists.
    """
    image_url: str
    text: Optional[Union[str, List[str]]] = Field(
        default=None,
        description="Overlay copy; omit for logo-only render. Multiline strings or list of lines.",
    )
    x: Optional[float] = Field(
        default=None,
        description="Text center horizontal anchor; required together with ``y`` when ``text`` is set.",
    )
    y: Optional[float] = Field(
        default=None,
        description="Text center vertical anchor; required together with ``x`` when ``text`` is set.",
    )
    font_size: Optional[int] = Field(default=None, ge=1)
    font_weight: Optional[str] = Field(default='normal')
    text_color: Optional[str] = Field(default='white')
    font_family: Optional[str] = Field(
        default=None,
        description=(
            "Family name or font file path. Accepts e.g. "
            "``proxima-nova``, ``Helvetica``, ``Helvetica-bold``, ``Interstate``, ``InterstateBold``. "
            "Hyphens, ``-bold`` suffixes, and CamelCase (``InterstateBold``) are normalized to find "
            "``.ttf/.otf/.ttc`` on the system."
        ),
    )
    logo_url: Optional[str] = Field(default=None)
    logo_x: Optional[float] = Field(
        default=None,
        description="Logo center horizontal anchor (same normalization as ``x``).",
    )
    logo_y: Optional[float] = Field(
        default=None,
        description="Logo center vertical anchor (same normalization as ``y``).",
    )
    logo_placement: Optional[Dict[str, float]] = Field(
        default=None,
        description=(
            "Alternative logo shape: ``{\"x\": 0.91, \"y\": 0.11, "
            "\"logo_max_width_ratio\": 0.16}`` (normalized center plus optional size). "
            "When set, these are used if ``logo_x``/``logo_y`` or ``logo_max_width_ratio`` are omitted."
        ),
    )
    logo_max_width_ratio: Optional[float] = Field(
        default=0.18,
        ge=0.02,
        le=0.5,
        description="Max logo width as a fraction of canvas width (aspect ratio preserved).",
    )

class TextPlacementSuggestionsRequest(BaseModel):
    image_url: str
    text: str
    website_url: Optional[str] = Field(
        default=None,
        description=(
            "If set: requests-based logo scrape (single best URL via ``scrape_logo``), plus one Selenium session "
            "for viewport-weighted theme colors and computed font families. Google Fonts matching "
            "when GOOGLE_FONTS_API_KEY is set. Response includes ``logo_url`` and, when a logo is found, "
            "``logo_placement`` (AI x/y and logo size on the canvas image, same normalized convention as text)."
        ),
    )

class ExtractColorsRequest(BaseModel):
    image_url: str
    num_colors: Optional[int] = Field(default=5, ge=1, le=20)

class RunScheduledScrapeRequest(BaseModel):
    company_id: str
    website_url: str
    frequency: str = Field(..., pattern="^(6_months|12_months)$")

# Pydantic models for response bodies
class HealthResponse(BaseModel):
    status: str

class AnalyzeResponse(BaseModel):
    success: bool
    url: str
    company_name: str
    industry: str
    theme_colors: List[str]
    colors_from_logo: List[str]
    favicon_colors_detailed: List[str]
    keywords: List[str]
    fonts_typography: List[str]
    element_fonts: Dict[str, Any]
    matched_fonts: Dict[str, Any]
    company_info: str
    tone_analysis: str
    target_group: str
    address: str
    logo_url: str
    favicon_url: str
    original_logo_url: str
    original_favicon_url: str
    products: List[Dict[str, Any]]
    product_categories: Dict[str, Any]

class ImageWorkflowResponse(BaseModel):
    analysis: Union[Dict[str, Any], str]
    analyzed_images: List[str]
    original_image_urls: List[str]
    firebase_image_urls: List[str]
    execution_time: str

class UserImageryResponse(BaseModel):
    analysis: Union[Dict[str, Any], str]
    image_urls: List[str]

class TextPlacementResponse(BaseModel):
    success: bool
    output_url: str
    filename: str
    full_url: str
    execution_time: str
    old_url: str = Field(..., description="Same image_url as in the request payload (input image).")
    note: Optional[str] = None
    # Where the primary URLs point: firebase (public HTTPS, same bucket as other flows) vs local (/images/).
    storage: Optional[str] = None

class TextPlacementSuggestionsResponse(BaseModel):
    success: bool
    suggestions: List[Dict[str, Any]] = Field(
        ...,
        description="Exactly one placement object; scraped palette is `colors` array when website_url was used.",
    )
    text_placement_body: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Ready-to-send JSON body for POST /textplacement (same ``image_url``): "
            "``x``, ``y``, ``text``, styling fields, and when a logo exists "
            "``logo_url``, ``logo_x``, ``logo_y``, ``logo_max_width_ratio`` "
            "(aligned with ``logo_placement``)."
        ),
    )
    logo_url: Optional[str] = Field(
        default=None,
        description="Single best logo image URL when ``website_url`` was provided (``scrape_logo``, return_all=False).",
    )
    logo_placement: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "When ``logo_url`` is set: AI-suggested center and size of the logo on the canvas — "
            "normalized ``x``/``y`` in [0,1] plus ``logo_max_width_ratio``."
        ),
    )

class ExtractColorsResponse(BaseModel):
    success: bool
    colors: List[Dict[str, Any]]
    num_colors: int
    execution_time: str

class RunScheduledScrapeResponse(BaseModel):
    success: bool
    message: str
    scheduler_error: Optional[str] = None

app = FastAPI(
    title="HoldFlight API",
    version="1.0",
    description="API for website analysis, image processing, and brand extraction",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Initialize Firebase
init_firebase()

# Enable CORS with an explicit origin allowlist from application config
from config.cors_config import get_cors_allowed_origins, get_cors_allow_credentials

# Enable CORS for all routes with more specific settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_allowed_origins(),
    allow_credentials=get_cors_allow_credentials(),
    allow_methods=["GET", "POST", "OPTIONS", "HEAD"],
    allow_headers=["Content-Type", "Authorization", "Access-Control-Allow-Origin"],
    expose_headers=["Content-Type", "X-Total-Count"],
    max_age=600
)

@app.get(
    '/',
    response_model=HealthResponse,
    status_code=200,
    summary="Health Check",
    description="Health check endpoint for Cloud Run and monitoring"
)
def health_check():
    """Health check endpoint for Cloud Run"""
    return {'status': 'healthy'}

@app.get('/api-docs')
def api_docs():
    """
    Custom API Documentation endpoint (JSON format).
    For interactive Swagger UI, visit /docs instead.
    """
    docs = {
        'title': 'HoldFlight API Documentation',
        'version': '1.0',
        'base_url': 'http://127.0.0.1:8080',
        'swagger_ui': 'http://127.0.0.1:8080/docs',
        'redoc': 'http://127.0.0.1:8080/redoc',
        'endpoints': [
            {
                'path': '/',
                'method': 'GET',
                'description': 'Health check endpoint',
                'response': {'status': 'healthy'}
            },
            {
                'path': '/analyze',
                'method': 'POST',
                'description': 'Analyze a website - extracts company info, colors, fonts, etc.',
                'request_body': {
                    'url': 'string (required) - Website URL to analyze'
                }
            },
            {
                'path': '/img',
                'method': 'POST',
                'description': 'Image workflow - analyze and process images',
                'request_body': {
                    'url': 'string (required) - Website URL'
                }
            },
            {
                'path': '/userimagery',
                'method': 'POST',
                'description': 'User imagery analysis - analyze up to 10 images directly',
                'request_body': {
                    'image_urls': 'array (required) - Array of image URLs to analyze (max 10)',
                    'language': 'string (optional) - Language code, defaults to "en"'
                },
                'example': {
                    'image_urls': ['https://example.com/image1.jpg', 'https://example.com/image2.jpg'],
                    'language': 'en'
                }
            },
            {
                'path': '/textplacement',
                'method': 'POST',
                'description': 'Text placement on images',
                'request_body': {
                    'image_url': 'string (required) - Image URL',
                    'text': 'string or array (required) - Text to place (use ``lines`` from suggestions)',
                    'x': 'float required, 0–1 — horizontal anchor from ``/textplacementsuggestions``',
                    'y': 'float required, 0–1 — vertical anchor',
                    'font_size': 'int (optional) — copy from suggestion',
                    'font_weight': 'string (optional) — copy from suggestion',
                    'text_color': 'string (optional) — hex from suggestion ``colors[0]`` or scrape',
                    'font_family': 'string (optional) — GPT ``font_family`` or first ``fonts`` name; or path to .ttf'
                }
            },
            {
                'path': '/textplacementsuggestions',
                'method': 'POST',
                'description': 'Get AI-powered text placement suggestions',
                'request_body': {
                    'image_url': 'string (required) - Image URL',
                    'text': 'string (required) - Text to place'
                }
            },
            {
                'path': '/extract-colors',
                'method': 'POST',
                'description': 'Extract colors from logo/favicon',
                'request_body': {
                    'image_url': 'string (required) - Image URL or base64 data'
                }
            },
            {
                'path': '/images/{filename}',
                'method': 'GET',
                'description': 'Serve generated images',
                'parameters': {
                    'filename': 'string (required) - Image filename'
                }
            },
            {
                'path': '/run_scheduled_scrape',
                'method': 'POST',
                'description': 'Run scheduled website scraping and update company data',
                'request_body': {
                    'company_id': 'string (required) - Company ID',
                    'website_url': 'string (required) - Website URL to scrape',
                    'frequency': 'string (required) - "6_months" or "12_months"'
                },
                'example': {
                    'company_id': '123',
                    'website_url': 'https://example.com',
                    'frequency': '6_months'
                }
            }
        ],
        'testing': {
            'note': 'Use Swagger UI at /docs for interactive testing, or tools like Postman, curl, or Python requests',
            'swagger_ui_url': 'http://127.0.0.1:8080/docs',
            'example_curl': 'curl -X POST http://127.0.0.1:8080/analyze -H "Content-Type: application/json" -d \'{"url": "https://example.com"}\'',
            'example_python': 'import requests\nresponse = requests.post("http://127.0.0.1:8080/analyze", json={"url": "https://example.com"})'
        }
    }
    return docs

# Dedicated images directory — absolute path under holdflight/ (not os.getcwd(), which breaks
# /images/{filename} when uvicorn is started from a different working directory).
_holdflight_src_core = os.path.abspath(os.path.dirname(__file__))
_HOLDFLIGHT_ROOT = os.path.abspath(os.path.join(_holdflight_src_core, '..', '..'))
IMAGES_DIR = os.environ.get(
    'HOLDFLIGHT_IMAGES_DIR',
    os.path.join(_HOLDFLIGHT_ROOT, 'generated_images'),
)
os.makedirs(IMAGES_DIR, exist_ok=True)
print(f"📁 Generated images directory: {IMAGES_DIR}")

@app.get(
    '/images/{filename}',
    response_class=FileResponse,
    status_code=200,
    summary="Serve Generated Images",
    description="Serve generated images from the images directory",
    responses={
        200: {"description": "Image file returned successfully", "content": {"image/jpeg": {}}},
        400: {"description": "Invalid filename"},
        404: {"description": "Image not found"}
    }
)
def serve_image(filename: str):
    """Serve generated images"""
    try:
        # Security: Only allow serving files from images directory
        if '..' in filename or '/' in filename or '\\' in filename:
            raise HTTPException(status_code=400, detail='Invalid filename')
        
        file_path = os.path.join(IMAGES_DIR, filename)
        
        # Check if file exists
        if not os.path.exists(file_path):
            print(f"❌ Image not found: {file_path}")
            print(f"   Current working directory: {os.getcwd()}")
            print(f"   Images directory: {IMAGES_DIR}")
            print(f"   Files in images directory: {os.listdir(IMAGES_DIR) if os.path.exists(IMAGES_DIR) else 'Directory does not exist'}")
            raise HTTPException(status_code=404, detail='Image not found')
        
        return FileResponse(file_path, media_type='image/jpeg')
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error serving image: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    '/analyze',
    response_model=AnalyzeResponse,
    status_code=200,
    summary="Analyze Website",
    description="Analyze a website - extracts company info, colors, fonts, products, and more",
    responses={
        200: {"description": "Website analysis completed successfully"},
        400: {"description": "Invalid request - URL is required"},
        500: {"description": "Internal server error during analysis"}
    }
)
def analyze_website(request_data: AnalyzeRequest):
    """API endpoint to analyze a website"""
    try:
        url = request_data.url
        
        if not url:
            raise HTTPException(status_code=400, detail='URL is required')
        
        # Create analyzer and extract company name from URL
        analyzer = WebsiteAnalyzer()
        company_name = analyzer.extract_company_name_from_url(url)
        
        # Analyze the website
        result = analyzer.analyze_website(url, company_name)
        
        if not result:
            raise HTTPException(status_code=500, detail='Failed to analyze website')
        
        # Check if the result contains an error
        if 'error' in result:
            raise HTTPException(status_code=500, detail=result['error'])
        
        # Debug: Log theme_colors from result
        theme_colors_from_result = result.get('theme_colors', [])
        colors_from_logo = result.get('colors_from_logo', [])  # Colors extracted from logo/favicon
        
        print(f"🔍 DEBUG: theme_colors from analyze_website result: {len(theme_colors_from_result)} colors")
        if theme_colors_from_result:
            print(f"🔍 DEBUG: First 10 colors: {theme_colors_from_result[:10]}")
        else:
            print(f"⚠️ WARNING: theme_colors is empty in result!")
            print(f"🔍 DEBUG: Result keys: {list(result.keys())}")
        
        # Log brand color extraction details
        print(f"\n🎨 Brand Color Extraction Details:")
        if colors_from_logo:
            print(f"   colors_from_logo: {len(colors_from_logo)} colors - {colors_from_logo}")
        print(f"   ✅ Combined Theme Colors: {len(theme_colors_from_result)} colors")
        
        # Upload logo and favicon to Firebase Storage
        logo_url = result.get('logo_url', '')
        favicon_url = result.get('favicon_url', '')
        firebase_logo_url = logo_url
        firebase_favicon_url = favicon_url
        
        if logo_url:
            print(f"\n📤 Uploading logo to Firebase Storage...")
            firebase_logo_url = upload_logo_or_favicon_to_firebase(logo_url, folder_name='user_uploads', file_type='logo')
            if firebase_logo_url != logo_url:
                print(f"✅ Logo uploaded to Firebase: {firebase_logo_url}")
            else:
                print(f"ℹ️ Using original logo URL (upload skipped or failed)")
        
        if favicon_url:
            print(f"\n📤 Uploading favicon to Firebase Storage...")
            firebase_favicon_url = upload_logo_or_favicon_to_firebase(favicon_url, folder_name='user_uploads', file_type='favicon')
            if firebase_favicon_url != favicon_url:
                print(f"✅ Favicon uploaded to Firebase: {firebase_favicon_url}")
            else:
                print(f"ℹ️ Using original favicon URL (upload skipped or failed)")
        
        # Extract detailed colors from logo and favicon using the same method as /extract-colors
        logo_colors_detailed = []
        favicon_colors_detailed = []
        
        if logo_url:
            try:
                print(f"\n🎨 Extracting detailed colors from logo...")
                logo_colors_full = extract_logo_colors(logo_url, num_colors=5)
                # Extract only hex codes
                logo_colors_detailed = [color.get('hex', '') for color in logo_colors_full if color.get('hex')]
                print(f"✅ Extracted {len(logo_colors_detailed)} colors from logo")
            except Exception as e:
                print(f"⚠️ Failed to extract colors from logo: {str(e)}")
                logo_colors_detailed = []
        
        if favicon_url and favicon_url != logo_url:  # Only extract if different from logo
            try:
                print(f"\n🎨 Extracting detailed colors from favicon...")
                favicon_colors_full = extract_logo_colors(favicon_url, num_colors=5)
                # Extract only hex codes
                favicon_colors_detailed = [color.get('hex', '') for color in favicon_colors_full if color.get('hex')]
                print(f"✅ Extracted {len(favicon_colors_detailed)} colors from favicon")
            except Exception as e:
                print(f"⚠️ Failed to extract colors from favicon: {str(e)}")
                favicon_colors_detailed = []
        
        # Format the response with structured data in the exact format requested
        # All data including logo, favicon, and colors are already in the result from website_analyzer
        theme_colors = result.get('theme_colors', [])
        
        # Merge favicon_colors_detailed into theme_colors (avoiding duplicates)
        if favicon_colors_detailed:
            # Convert theme_colors to set for quick lookup (normalize to uppercase for comparison)
            theme_colors_set = {color.upper() if isinstance(color, str) else str(color).upper() for color in theme_colors}
            
            # Add favicon colors that aren't already in theme_colors
            for favicon_color in favicon_colors_detailed:
                if favicon_color and favicon_color.upper() not in theme_colors_set:
                    theme_colors.append(favicon_color)
                    theme_colors_set.add(favicon_color.upper())
            
            print(f"🎨 Merged {len(favicon_colors_detailed)} favicon colors into theme_colors")
        
        products = result.get('products', [])
        product_categories = result.get('product_categories', {})
        
        # Convert products from list of strings to list of dictionaries to match response model
        if products and isinstance(products, list) and len(products) > 0:
            # Check if first item is already a dict
            if isinstance(products[0], dict):
                # Already in correct format
                formatted_products = products
            else:
                # Convert strings to dictionaries
                formatted_products = [{'name': str(product)} if isinstance(product, str) else product for product in products]
        else:
            formatted_products = []
        
        print(f"🎨 API Response: Returning {len(theme_colors)} colors from brand_color_analyzer (including favicon colors)")
        if theme_colors:
            print(f"🎨 Colors: {theme_colors[:10]}")  # Print first 10 colors for debugging
        print(f"📦 API Response: Returning {len(formatted_products)} products in {len(product_categories)} categories")
        
        matched_fonts = result.get('matched_fonts', {})
        print(f"\n{'='*60}")
        print(f"📊 API RESPONSE SUMMARY - All Data Included")

        print(f"{'='*60}")
        print(f"🎨 Theme Colors (Combined): {len(theme_colors)} colors")
        print(f"🎨 Colors from Logo/Favicon: {len(colors_from_logo)} colors - {colors_from_logo}")
        print(f"🎨 Detailed Logo Colors: {len(logo_colors_detailed)} hex codes - {logo_colors_detailed}")
        print(f"🎨 Detailed Favicon Colors: {len(favicon_colors_detailed)} hex codes - {favicon_colors_detailed}")
        print(f"📦 Products: {len(formatted_products)} products in {len(product_categories)} categories")
        print(f"🔤 Matched Google Fonts: {len(matched_fonts)} fonts")
        print(f"🔑 Keywords: {len(result.get('keywords', []))} keywords")
        print(f"📝 Company Info: {'✓' if result.get('company_info') else '✗'}")
        print(f"🎯 Target Group: {'✓' if result.get('target_group') else '✗'}")
        print(f"📍 Address: {'✓' if result.get('address') else '✗'}")
        print(f"🖼️ Logo URL: {'✓' if firebase_logo_url else '✗'}")
        print(f"🌟 Favicon URL: {'✓' if firebase_favicon_url else '✗'}")
        print(f"{'='*60}")
        
        # Log complete font details
        if matched_fonts:
            print("\n🔤 Matched Fonts Details:")
            for font_name, font_info in matched_fonts.items():
                print(f"  {font_name}:")
                print(f"    Family: {font_info.get('family', '')}")
                print(f"    Category: {font_info.get('category', '')}")
                print(f"    Variant: {font_info.get('variant', '')}")
                print(f"    File: {font_info.get('file', '')}")
                print(f"    Import URL: {font_info.get('import_url', '')}")
        
        print(f"\n✅ All results returned in API response - No files saved")
        
        response = {
            'success': True,
            'url': url,
            'company_name': result.get('company_name', 'Unknown'),
            'industry': result.get('industry', 'Unknown'),
            'theme_colors': theme_colors,  # Combined colors from brand color extraction (logo + website + favicon colors)
            'colors_from_logo': colors_from_logo,  # Colors extracted from AI-selected logo/favicon (hex strings only)
            'favicon_colors_detailed': favicon_colors_detailed,  # Hex codes only from favicon (array of hex strings)
            'keywords': result.get('keywords', []),
            'fonts_typography': result.get('fonts_typography', []),
            'element_fonts': result.get('element_fonts', {}),
            'matched_fonts': matched_fonts,  # Complete Google Fonts data with all fields
            'company_info': result.get('company_info', 'No information available'),
            'tone_analysis': result.get('tone_analysis', 'No tone analysis available'),
            'target_group': result.get('target_group', 'Unknown'),
            'address': result.get('address', 'Not able to scrape or data is not present'),
            'logo_url': firebase_logo_url,  # Firebase Storage URL
            'favicon_url': firebase_favicon_url,  # Firebase Storage URL
            'original_logo_url': logo_url,  # Original URL for reference
            'original_favicon_url': favicon_url,  # Original URL for reference
            'products': formatted_products,  # Converted to list of dicts
            'product_categories': result.get('product_categories', {})
        }
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post(
    '/img',
    response_model=ImageWorkflowResponse,
    status_code=200,
    summary="Image Workflow Analysis",
    description="Run the complete image analysis workflow - scrapes images from website and analyzes them with AI",
    responses={
        200: {"description": "Image analysis completed successfully"},
        400: {"description": "Invalid request - URL is required"},
        404: {"description": "No images found on the website"},
        500: {"description": "Internal server error during analysis"}
    }
)
def image_workflow(request_data: ImageWorkflowRequest):
    """
    API endpoint to run the complete image analysis workflow
    
    Request JSON:
    {
        "url": "https://example.com",
        "max_images": 10,  # optional, defaults to 10
        "language": "auto"  # optional, auto-detect if not specified
    }
    """
    try:
        # Capture the start time
        start_time = datetime.now()
        
        # Get request data
        url = request_data.url
        max_images = request_data.max_images
        language = request_data.language
        
        if not url:
            raise HTTPException(status_code=400, detail='URL is required')
        
        # Add https:// if not present
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        # Step 1: Scrape images and detect language
        print(f"🔍 Scraping images from: {url}")
        scrape_result = scrape_website_images(url)
        
        if not scrape_result or 'images' not in scrape_result or not scrape_result['images']:
            raise HTTPException(
                status_code=404,
                detail='No images found on the website or failed to scrape'
            )
        
        # Get the detected language if auto-detection was requested
        if language == 'auto':
            language = scrape_result.get('language', 'en')
            print(f"🌐 Detected website language: {language}")
        
        scraped_images = scrape_result['images']
        
        # Step 2: Upload images to Firebase Storage and prepare data URIs for analysis
        print(f"📤 Processing {min(len(scraped_images), max_images)} images for Firebase Storage and analysis...")
        firebase_image_urls = []
        image_data_uris = []  # Store data URIs for OpenAI API
        original_image_urls = []
        upload_failures = []
        
        # Process images - limit to max_images for analysis
        images_to_process = scraped_images[:max_images]
        
        for idx, img in enumerate(images_to_process, 1):
            if isinstance(img, str):
                original_url = img
            elif isinstance(img, dict) and 'url' in img:
                original_url = img['url']
            else:
                continue
                
            original_image_urls.append(original_url)
            
            # Upload to Firebase and get data URI
            print(f"🔄 Processing image {idx}/{len(images_to_process)}: {original_url[:60]}...")
            try:
                upload_result = upload_image_to_firebase(original_url, folder_name='user_uploads')
                if upload_result and isinstance(upload_result, dict):
                    firebase_image_urls.append(upload_result['firebase_url'])
                    image_data_uris.append(upload_result['data_uri'])
                    print(f"   ✅ Uploaded to Firebase and created data URI")
                else:
                    upload_failures.append(original_url)
                    print(f"   ❌ Failed to upload: {original_url}")
            except Exception as e:
                upload_failures.append(original_url)
                print(f"   ❌ Error uploading {original_url}: {str(e)}")
        
        print(f"\n📊 Processing Summary:")
        print(f"   ✅ Successfully processed: {len(firebase_image_urls)} images")
        print(f"   ❌ Failed: {len(upload_failures)} images")
        
        if upload_failures and len(upload_failures) <= 5:
            print(f"   ⚠️ Failed image URLs:")
            for failed_url in upload_failures:
                print(f"      - {failed_url}")
        
        # Step 3: Analyze images with GPT-4o-mini
        # Use data URIs for analysis to avoid URL access issues
        if not image_data_uris:
            raise HTTPException(
                status_code=500,
                detail='No images were successfully processed for analysis'
            )
        
        print(f"\n🤖 Starting analysis of {len(image_data_uris)} images with GPT-4o-mini...")
        print(f"   Using data URIs (base64 encoded) for direct API access")
        print(f"   Language: {language}")
        
        try:
            analyzer = ImageAnalyzer()
            
            # Use data URIs for analysis - these are base64 encoded images that OpenAI can use directly
            # This avoids any URL access issues with Firebase Storage
            image_urls = image_data_uris
                    
            # Analyze the images with the detected language
            result = analyzer.analyze_images(image_urls, language=language)
            
            print(f"✅ Analysis completed successfully")
            
        except Exception as e:
            print(f"❌ Error during analysis: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f'Analysis failed: {str(e)}'
            )
        
        # Calculate execution time
        execution_time = str(datetime.now() - start_time)
        
        if not result or not result.get('success'):
            error_msg = result.get('error', 'Failed to analyze images') if result else 'Analysis failed'
            raise HTTPException(status_code=500, detail=error_msg)
            
        # Return analysis along with the image URLs that were analyzed
        analysis_text = result.get('analysis', '')
        structured_analysis = convert_analysis_text_to_dict(
            analysis_text,
            enforce_canonical_keys=True,
            include_subsections=False
        )

        return {
            'analysis': structured_analysis if structured_analysis else analysis_text,
            'analyzed_images': firebase_image_urls,  # Firebase URLs that were analyzed (publicly accessible)
            'original_image_urls': original_image_urls[:len(firebase_image_urls)],  # Original URLs for reference
            'firebase_image_urls': firebase_image_urls,  # URLs of images saved to Firebase Storage
            'execution_time': execution_time
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post(
    '/userimagery',
    response_model=UserImageryResponse,
    status_code=200,
    summary="User Imagery Analysis",
    description="Analyze up to 10 user-provided images directly with AI",
    responses={
        200: {"description": "Image analysis completed successfully"},
        400: {"description": "Invalid request - image_urls required"},
        500: {"description": "Internal server error during analysis"}
    }
)
def user_imagery_analysis(request_data: UserImageryRequest):
    """
    API endpoint for user to directly submit up to 10 images for analysis
    
    Request JSON:
    {
        "image_urls": [
            "https://example.com/image1.jpg",
            "https://example.com/image2.jpg",
            ...
        ],
        "language": "en"  # optional, defaults to "en"
    }
    """
    try:
        # Capture the start time
        start_time = datetime.now()
        
        # Get request data
        image_urls = request_data.image_urls
        language = request_data.language
        
        print(f"🤖 Analyzing {len(image_urls)} user-provided images with GPT-4o-mini")
        
        # Analyze the images using ImageAnalyzer
        analyzer = ImageAnalyzer()
        result = analyzer.analyze_images(image_urls, language=language)
        
        # Calculate execution time
        execution_time = str(datetime.now() - start_time)
        
        if not result or not result.get('success'):
            error_msg = result.get('error', 'Failed to analyze images') if result else 'Analysis failed'
            raise HTTPException(status_code=500, detail=error_msg)
        
        # Return comprehensive analysis results with structured analysis dictionary
        analysis_text = result.get('analysis', '')
        structured_analysis = convert_analysis_text_to_dict(
            analysis_text,
            include_subsections=False
        )

        return {
            'analysis': structured_analysis if structured_analysis else analysis_text,
            'image_urls': image_urls
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def build_text_placement_body_from_suggestion(
    image_url: str,
    fallback_text: str,
    suggestion: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Map ``suggestions[0]`` into the JSON body expected by ``POST /textplacement``.
    """
    if not suggestion or not isinstance(suggestion, dict):
        return None
    try:
        x = float(suggestion["x"])
        y = float(suggestion["y"])
    except (KeyError, TypeError, ValueError):
        return None

    lines = suggestion.get("lines")
    if isinstance(lines, list) and lines:
        text_field: Union[str, List[str]] = [str(line) for line in lines if line is not None]
        if not text_field:
            text_field = fallback_text
    else:
        text_field = fallback_text

    body: Dict[str, Any] = {
        "image_url": image_url,
        "text": text_field,
        "x": x,
        "y": y,
    }

    fs = suggestion.get("font_size")
    if fs is not None:
        try:
            body["font_size"] = max(1, int(fs))
        except (TypeError, ValueError):
            pass

    fw = suggestion.get("font_weight")
    if fw:
        body["font_weight"] = str(fw).strip()

    colors = suggestion.get("colors")
    if isinstance(colors, list) and colors:
        first = colors[0]
        if first:
            body["text_color"] = str(first).strip()

    ff = suggestion.get("font_family")
    if ff and str(ff).strip():
        body["font_family"] = str(ff).strip()
    else:
        fonts = suggestion.get("fonts")
        if isinstance(fonts, list):
            for fn in fonts:
                if fn and str(fn).strip():
                    body["font_family"] = str(fn).strip()
                    break

    return body


@app.post(
    '/textplacement',
    response_model=TextPlacementResponse,
    status_code=200,
    summary="Text & logo placement on image",
    description=(
        "Composite text and/or logo using the same normalized (or pixel) center anchors as "
        "``/textplacementsuggestions`` / ``text_placement_body``."
    ),
    responses={
        200: {"description": "Text placed successfully on image"},
        400: {"description": "Invalid request - image_url and text required"},
        500: {"description": "Internal server error during text placement"}
    }
)
def text_placement_workflow(request_data: TextPlacementRequest, request: Request):
    """
    Overlay text and/or logo on ``image_url`` using center anchors aligned with suggestions.

    When both text and logo are present, reuse ``POST /textplacementsuggestions`` → ``text_placement_body``
    (includes ``logo_url``, ``logo_x``, ``logo_y`` when applicable).
    """
    try:
        start_time = datetime.now()
        
        # Get request data
        image_url = request_data.image_url
        text = request_data.text
        
        if not image_url:
            raise HTTPException(status_code=400, detail='image_url is required')

        def _has_nonempty_overlay_copy(t: Any) -> bool:
            if t is None:
                return False
            if isinstance(t, list):
                return any(str(line).strip() for line in t if line is not None)
            return bool(str(t).strip())

        has_text = _has_nonempty_overlay_copy(text)
        logo_url_raw = (request_data.logo_url or "").strip() or None
        lp_obj = request_data.logo_placement or {}
        lp_x = request_data.logo_x if request_data.logo_x is not None else lp_obj.get("x")
        lp_y = request_data.logo_y if request_data.logo_y is not None else lp_obj.get("y")
        has_logo = bool(
            logo_url_raw
            and lp_x is not None
            and lp_y is not None
        )

        if not has_text and not has_logo:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Provide non-empty text with x/y, and/or logo_url with logo_x/logo_y "
                    "(or logo_placement.x/logo_placement.y)"
                ),
            )

        if has_text and (
            request_data.x is None
            or request_data.y is None
        ):
            raise HTTPException(
                status_code=400,
                detail="text requires x and y anchors",
            )

        # Keep logo anchors image-size-dependent by default (normalized 0..1).
        # Pixel anchors are still accepted in renderer, but here we enforce normalized
        # for logo_placement payload to keep behavior consistent across any canvas size.
        if has_logo:
            try:
                lpx = float(lp_x)
                lpy = float(lp_y)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="logo placement x/y must be numeric")
            if not (0.0 <= lpx <= 1.0 and 0.0 <= lpy <= 1.0):
                raise HTTPException(
                    status_code=400,
                    detail="logo placement must be normalized (0..1) so it scales with image size",
                )

        ax = float(request_data.x) if request_data.x is not None else None
        ay = float(request_data.y) if request_data.y is not None else None
        font_size = request_data.font_size
        font_weight = request_data.font_weight
        text_color = request_data.text_color
        font_family = (request_data.font_family or "").strip() or None

        logo_size_raw = (
            request_data.logo_max_width_ratio
            if request_data.logo_max_width_ratio is not None
            else lp_obj.get("logo_max_width_ratio")
        )
        lmr = float(logo_size_raw) if logo_size_raw is not None else 0.18
        lmr = max(0.02, min(0.5, lmr))
        
        # Validate font_size if provided
        if font_size is not None:
            try:
                font_size = int(font_size)
                if font_size <= 0:
                    font_size = None
            except (ValueError, TypeError):
                font_size = None
        
        print(f"🎨 Processing text placement:")
        print(f"   Image URL: {image_url}")
        print(f"   Text: {text if has_text else '(none)'}")
        if has_text and ax is not None and ay is not None:
            print(f"   Text anchor: x={ax}, y={ay} (0..1 or pixels)")
        print(f"   Font Size: {font_size or 'auto'}")
        print(f"   Font Weight: {font_weight}")
        print(f"   Text Color: {text_color}")
        if font_family:
            print(f"   Font family: {font_family}")
        if has_logo:
            print(
                f"   Logo: {logo_url_raw} @ logo_x={lpx}, logo_y={lpy} "
                f"(max_width_ratio={lmr})"
            )
        
        # Process the image with text overlay
        # Use dedicated images directory for persistence
        result = place_text_on_image(
            image_url=image_url,
            text=text if has_text else None,
            position="auto",
            font_size=font_size,
            font_weight=font_weight,
            text_color=text_color,
            output_dir=IMAGES_DIR,  # Save to dedicated images directory
            anchor_x=ax,
            anchor_y=ay,
            font_family=font_family,
            logo_url=logo_url_raw if has_logo else None,
            logo_anchor_x=lpx if has_logo else None,
            logo_anchor_y=lpy if has_logo else None,
            logo_max_width_ratio=lmr,
        )
        
        execution_time = str(datetime.now() - start_time)
        
        if not result.get('success'):
            raise HTTPException(
                status_code=500,
                detail=result.get('error', 'Failed to place text on image')
            )
        
        # Verify the file was actually saved
        filename = result.get('filename')
        file_path = os.path.join(IMAGES_DIR, filename)
        
        if not os.path.exists(file_path):
            print(f"❌ ERROR: File was not saved successfully!")
            print(f"   Expected path: {file_path}")
            print(f"   Images directory exists: {os.path.exists(IMAGES_DIR)}")
            raise HTTPException(
                status_code=500,
                detail='Image was processed but file was not saved. This may be due to filesystem limitations in cloud environments.'
            )
        
        print(f"✅ Image saved successfully: {file_path}")
        print(f"   File size: {os.path.getsize(file_path)} bytes")

        firebase_folder = (
            os.environ.get("HOLDFLIGHT_TEXT_OVERLAY_FIREBASE_FOLDER") or "text_overlays"
        ).strip("/")
        use_firebase = os.environ.get("HOLDFLIGHT_TEXT_OVERLAY_USE_FIREBASE", "true").lower() in (
            "1",
            "true",
            "yes",
        )
        uploaded_public_url: Optional[str] = None
        if use_firebase:
            try:
                with open(file_path, "rb") as fh:
                    jpeg_bytes = fh.read()
                firebase_path = f"{firebase_folder}/{filename}"
                up = _upload_bytes_to_firebase_storage(
                    jpeg_bytes, firebase_path, "image/jpeg"
                )
                if up and up.get("firebase_url"):
                    uploaded_public_url = up["firebase_url"]
                    print(f"✅ Text overlay uploaded to Firebase: {uploaded_public_url}")
                    keep_local = os.environ.get("HOLDFLIGHT_KEEP_LOCAL_TEXT_OVERLAY", "").lower() in (
                        "1",
                        "true",
                        "yes",
                    )
                    if not keep_local:
                        try:
                            os.remove(file_path)
                            print("   Removed local overlay file (Firebase is canonical).")
                        except OSError as oe:
                            print(f"⚠️ Could not remove local file {file_path}: {oe}")
            except Exception as ex:
                print(f"⚠️ Firebase upload for text overlay failed, falling back to local URL: {ex}")

        base_url = str(request.base_url).rstrip("/")
        rel_path = result.get("output_url") or f"/images/{filename}"

        if uploaded_public_url:
            response_data = {
                "success": True,
                "output_url": uploaded_public_url,
                "filename": filename,
                "full_url": uploaded_public_url,
                "execution_time": execution_time,
                "old_url": image_url,
                "storage": "firebase",
            }
        else:
            response_data = {
                "success": True,
                "output_url": rel_path,
                "filename": filename,
                "full_url": f"{base_url}{rel_path}",
                "execution_time": execution_time,
                "old_url": image_url,
                "storage": "local",
            }

        if uploaded_public_url:
            response_data["note"] = (
                "Persistent URL via Firebase Storage (same pattern as other image uploads). "
                "Use output_url or full_url in the UI."
            )
        else:
            response_data["note"] = (
                "Serving from this API under /images/ (relative output_url). "
                "Enable Firebase upload for a persistent public HTTPS URL."
            )

        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post(
    '/textplacementsuggestions',
    response_model=TextPlacementSuggestionsResponse,
    status_code=200,
    summary="AI Text Placement Suggestions",
    description=(
        "Returns one suggestion plus ``text_placement_body``: paste into POST ``/textplacement`` "
        "with the same ``image_url``."
    ),
    responses={
        200: {"description": "Suggestions generated successfully"},
        400: {"description": "Invalid request - image_url and text required"},
        500: {"description": "Internal server error during suggestion generation"}
    }
)
def text_placement_suggestions_workflow(request_data: TextPlacementSuggestionsRequest):
    """
    API endpoint for AI-powered text placement suggestions
    
    Request JSON:
    {
        "image_url": "https://example.com/image.jpg",
        "text": "Your text here",
        "website_url": "https://example.com"
    }

    Optional website_url: one Selenium session for on-page colors + fonts (fast),
    plus Google Fonts matching — not full /analyze.

    Response includes ``text_placement_body``: send that JSON as the body of POST ``/textplacement``.
    """
    try:
        # Get request data
        image_url = request_data.image_url
        text = request_data.text
        website_url = (request_data.website_url or "").strip() or None
        
        if not image_url:
            raise HTTPException(status_code=400, detail='image_url is required')
        
        if not text:
            raise HTTPException(status_code=400, detail='text is required')
        
        brand_context = None
        website_brand = None
        logo_url: Optional[str] = None

        if website_url:
            analyze_url = website_url
            if not analyze_url.startswith(('http://', 'https://')):
                analyze_url = 'https://' + analyze_url
            print(f"🧠 Getting AI text placement suggestions (website brand scrape: {analyze_url}):")
            try:
                scraped_one = scrape_logo(analyze_url, return_all=False)
                if scraped_one:
                    one = str(scraped_one).strip()
                    logo_url = one or None
                if logo_url:
                    print(f"   Logo scrape: {logo_url}")
                else:
                    print("   Logo scrape: none found")
            except Exception as le:
                print(f"⚠️ Logo scrape failed (suggestions continue): {le}")

            try:
                lw = analyze_website_theme_and_fonts(analyze_url, timeout=40, max_colors=16)
                if lw is None:
                    print("⚠️ Website color/font scrape returned no result")
                else:
                    td = lw.get('theme_data') or {}
                    theme_hex = td.get('all_colors') if isinstance(td, dict) else []
                    general = lw.get('general_fonts') or []
                    el_fonts = lw.get('element_fonts') or {}
                    fonts_for_match = []
                    fonts_for_match.extend(general if isinstance(general, list) else [])
                    if isinstance(el_fonts, dict):
                        for lst in el_fonts.values():
                            if isinstance(lst, list):
                                fonts_for_match.extend(lst)

                    uniq_fonts = []
                    seen_font = set()
                    for f in fonts_for_match:
                        if not f:
                            continue
                        s = str(f).strip()
                        if s and s not in seen_font:
                            seen_font.add(s)
                            uniq_fonts.append(s)

                    matched_fonts = {}
                    gf_key = os.environ.get('GOOGLE_FONTS_API_KEY')
                    if gf_key and uniq_fonts:
                        try:
                            matched_fonts = match_scraped_fonts_regular_only(uniq_fonts, gf_key)
                        except Exception as fm_err:
                            print(f"⚠️ Google Fonts matching failed: {fm_err}")

                    website_brand = build_brand_context(
                        theme_colors=theme_hex if isinstance(theme_hex, list) else [],
                        fonts_typography=uniq_fonts[:12],
                        matched_fonts=matched_fonts,
                        colors_from_logo=[],
                    )
                    has_brand = (
                        bool(website_brand.get('theme_colors'))
                        or bool(website_brand.get('colors_from_logo'))
                        or bool(website_brand.get('fonts'))
                    )
                    if has_brand:
                        brand_context = website_brand
                    else:
                        print("⚠️ No theme colors or fonts extracted from page")
                        website_brand = None
                    if website_brand:
                        print(
                            f"   Brand context: {len(website_brand.get('theme_colors', []))} theme colors, "
                            f"{len(website_brand.get('fonts', []))} scraped font names"
                        )
            except Exception as e:
                print(f"⚠️ Website brand extraction failed (suggestions continue without it): {e}")
        else:
            print(f"🧠 Getting AI text placement suggestions:")

        print(f"   Image URL: {image_url}")
        print(f"   Text: {text}")

        result = get_text_placement_suggestions(
            image_url=image_url,
            text=text,
            verbose=True,  # Enable verbose logging
            brand_context=brand_context,
        )
        
        if not result.get('success'):
            raise HTTPException(
                status_code=500,
                detail=result.get('error', 'Failed to generate suggestions')
            )
        
        suggestions = result.get("suggestions") or []
        tpl: Optional[Dict[str, Any]] = None
        if isinstance(suggestions, list) and suggestions and isinstance(suggestions[0], dict):
            tpl = build_text_placement_body_from_suggestion(image_url, text, suggestions[0])

        logo_placement: Optional[Dict[str, Any]] = None
        if logo_url:
            lp_res = get_logo_placement_suggestion(
                canvas_image_url=image_url,
                logo_image_url=logo_url,
                image_info=result.get("image_info"),
                verbose=True,
            )
            if lp_res.get("success") and isinstance(lp_res.get("logo_placement"), dict):
                logo_placement = lp_res["logo_placement"]

        if tpl is not None and logo_url and logo_placement:
            try:
                tpl = dict(tpl)
                tpl["logo_url"] = logo_url
                tpl["logo_x"] = float(logo_placement["x"])
                tpl["logo_y"] = float(logo_placement["y"])
                if logo_placement.get("logo_max_width_ratio") is not None:
                    tpl["logo_max_width_ratio"] = float(
                        logo_placement["logo_max_width_ratio"]
                    )
            except (KeyError, TypeError, ValueError):
                pass

        return {
            "success": True,
            "suggestions": suggestions,
            "text_placement_body": tpl,
            "logo_url": logo_url if website_url else None,
            "logo_placement": logo_placement,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    '/extract-colors',
    response_model=ExtractColorsResponse,
    status_code=200,
    summary="Extract Colors from Image",
    description="Extract dominant colors from an image (logo, favicon, etc.) - accepts file upload or URL",
    responses={
        200: {"description": "Colors extracted successfully"},
        400: {"description": "Invalid request - provide either file upload or image_url"},
        500: {"description": "Internal server error during color extraction"}
    }
)
async def extract_colors(
    request: Request,
    file: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None),
    num_colors: Optional[int] = Form(5),
    json_data: Optional[ExtractColorsRequest] = Body(None)
):
    """
    API endpoint to extract colors from an image.
    
    Accepts either:
    1. JSON with image_url:
       {
           "image_url": "https://example.com/image.jpg",
           "num_colors": 5  # optional, defaults to 5
       }
    
    2. Multipart form data with file upload:
       - file: image file (jpg, png, etc.)
       - num_colors: optional, defaults to 5
    
    Returns:
    {
        "success": true,
        "colors": [
            {
                "rgb": (255, 0, 0),
                "hex": "#FF0000",
                "name": "red"
            },
            ...
        ],
        "num_colors": 5
    }
    """
    try:
        start_time = datetime.now()
        
        # Check if request has file upload
        if file and file.filename:
            # Handle file upload
            if file.filename == '':
                raise HTTPException(status_code=400, detail='No file provided')
            
            # Validate num_colors
            if num_colors < 1 or num_colors > 20:
                num_colors = 5
            
            print(f"🎨 Extracting colors from uploaded file: {file.filename}")
            print(f"   Requested colors: {num_colors}")
            
            # Read file into BytesIO
            file_contents = await file.read()
            image_data = BytesIO(file_contents)
            image_data.seek(0)  # Reset to beginning
            
            # Extract colors
            colors = extract_colors_from_image_data(image_data, num_colors=num_colors)
            
        else:
            # Handle JSON request body
            if json_data:
                image_url = json_data.image_url
                num_colors = json_data.num_colors
            elif image_url:
                # Use form data image_url
                pass
            else:
                # Try to parse JSON from request body
                try:
                    content_type = request.headers.get('content-type', '')
                    if 'application/json' in content_type:
                        data = await request.json()
                        image_url = data.get('image_url')
                        num_colors = data.get('num_colors', 5)
                    else:
                        # Try form data
                        form_data = await request.form()
                        image_url = form_data.get('image_url')
                        num_colors = int(form_data.get('num_colors', num_colors or 5))
                except:
                    # Fallback to form parameters
                    num_colors = num_colors or 5
            
            if not image_url:
                raise HTTPException(status_code=400, detail='Either provide a file upload or JSON/form data with image_url')
            
            if not isinstance(num_colors, int) or num_colors < 1 or num_colors > 20:
                num_colors = 5
            
            print(f"🎨 Extracting colors from image URL: {image_url}")
            print(f"   Requested colors: {num_colors}")
            
            # Extract colors from URL
            colors = extract_logo_colors(image_url, num_colors=num_colors)
        
        execution_time = str(datetime.now() - start_time)
        
        if not colors:
            raise HTTPException(
                status_code=500,
                detail='Failed to extract colors from image. Image may be too small or invalid.'
            )
        
        print(f"✅ Successfully extracted {len(colors)} colors")
        print(f"   Execution time: {execution_time}")
        
        return {
            'success': True,
            'colors': colors,
            'num_colors': len(colors),
            'execution_time': execution_time
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error extracting colors: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    '/run_scheduled_scrape',
    response_model=RunScheduledScrapeResponse,
    status_code=200,
    summary="Run Scheduled Website Scrape",
    description="Run scheduled website scraping and update company data, optionally setting up Cloud Scheduler",
    responses={
        200: {"description": "Scrape and update completed successfully"},
        400: {"description": "Invalid request - company_id, website_url, and frequency required"},
        500: {"description": "Internal server error during scraping"}
    }
)
def run_scheduled_scrape(request_data: RunScheduledScrapeRequest):
    company_id = request_data.company_id
    website_url = request_data.website_url
    frequency = request_data.frequency  # "6_months" or "12_months"

    if not company_id or not website_url:
        raise HTTPException(status_code=400, detail="company_id and website_url required")

    if frequency not in ["6_months", "12_months"]:
        raise HTTPException(status_code=400, detail="frequency must be '6_months' or '12_months'")

    try:
        # 1️⃣ SCRAPE THE WEBSITE
        validate_public_url(website_url)
        scraping_api_url = "https://website-analyzer-9330546216.us-central1.run.app/analyze"
        resp = safe_post(requests, scraping_api_url, json={"url": website_url}, timeout=300)
        scraped_data = resp.json()

        # 2️⃣ UPDATE THE COMPANY IN DATABASE
        update_api_url = f"https://market-planner-test-container-9330546216.us-central1.run.app/api/v1/company/{company_id}"
        update_resp = safe_put(requests, update_api_url, json=scraped_data, timeout=300)

        # 3️⃣ CREATE/UPDATE CLOUD SCHEDULER JOB (only if gcloud is available)
        import subprocess
        import shutil
        
        # Check if gcloud is available (only in production/cloud environment)
        gcloud_available = shutil.which("gcloud") is not None
        
        if gcloud_available:
            try:
                job_id = f"scrape-company-{company_id}"

                if frequency == "6_months":
                    schedule = "0 0 2 */6 *"  # 2nd day every 6 months
                else:
                    schedule = "0 0 2 1 *"  # Jan 2 every year

                create_job_cmd = [
                    "gcloud", "scheduler", "jobs", "create", "http", job_id,
                    f"--schedule={schedule}",
                    "--uri=https://website-analyzer-9330546216.us-central1.run.app/run_scheduled_scrape",
                    "--http-method=POST",
                    f"--message-body={{\"company_id\":\"{company_id}\",\"website_url\":\"{website_url}\",\"frequency\":\"{frequency}\"}}",
                    "--time-zone=Asia/Kolkata",
                    "--location=us-central1",
                    "--attempt-deadline=300s"
                ]
                result = subprocess.run(create_job_cmd, capture_output=True, text=True)
                
                if result.returncode == 0:
                    return {
                        "success": True,
                        "message": "Scrape + Update completed, Scheduler set for next run"
                    }
                else:
                    # Scheduler creation failed, but scraping succeeded
                    return {
                        "success": True,
                        "message": "Scrape + Update completed, but scheduler setup failed",
                        "scheduler_error": result.stderr
                    }
            except Exception as scheduler_error:
                # Scheduler creation failed, but scraping succeeded
                return {
                    "success": True,
                    "message": "Scrape + Update completed, but scheduler setup failed",
                    "scheduler_error": str(scheduler_error)
                }
        else:
            # gcloud not available (local development)
            return {
                "success": True,
                "message": "Scrape + Update completed (scheduler setup skipped - gcloud not available in local environment)"
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



if __name__ == '__main__':
    import uvicorn
    port = int(os.environ.get('PORT', 8080))
    uvicorn.run(app, host='127.0.0.1', port=port)





