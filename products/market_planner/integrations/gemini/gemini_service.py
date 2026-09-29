import os
import asyncio
import re
from google import genai
from google.genai import types
import requests
import base64
from urllib.parse import urlparse
from typing import Dict, Any, Tuple, Optional, List
from dotenv import load_dotenv

# from utils.logger import setup_logger
from google.genai.types import HttpOptions

# logger = setup_logger("marketing-app")


load_dotenv()

def get_gemini_api_key():
    return os.getenv("GEMINI_API_KEY")


import os
gemini_api_url = os.getenv("GEMINI_API_URL") or os.getenv("GEMINI_BASE_URL")
if gemini_api_url:
    client = genai.Client(
        api_key=get_gemini_api_key(),
        http_options=HttpOptions(base_url=gemini_api_url)
    )
else:
    client = genai.Client(api_key=get_gemini_api_key())

# Retry configuration
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0  # seconds
MAX_RETRY_DELAY = 120.0  # seconds


ASPECT_RATIOS = {
    'square': '1:1',  
    'landscape': '16:9',  
    'portrait': '9:16',  
}


async def transcribe_audio(audio_bytes: bytes, prompt: str) -> Optional[str]:
    """
    Transcribe or analyze audio using Gemini.
    Used for high-fidelity Swedish address transcription.
    """
    if not audio_bytes:
        return None
        
    try:
        # Gemini 3.5 Flash: GA multimodal model (audio in, text out)
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=[
                prompt,
                {"inline_data": {"mime_type": "audio/wav", "data": audio_bytes}}
            ]
        )
        return response.text.strip()
    except Exception as e:
        # logger.error(f"Error transcribing audio with Gemini: {str(e)}")
        return None


def _gemini_image_model() -> str:
    return os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")


async def generate_image(planner_info: Dict[str, Any]) -> Tuple[bytes, str]:
    image_prompt = planner_info["image_prompt"]
    channel = planner_info["channel"].lower()
    aspect_ratio = ASPECT_RATIOS.get(planner_info["aspect_ratio"], "1:1")

    enhanced_prompt = f"""
        Generate a professional, high-quality, photorealistic image for a {channel} post.
        Subject: {image_prompt}.
        Use cinematic lighting, vibrant colors, and visually appealing composition suitable for a marketing campaign.
        Do not include any text, words, letters, logos, watermarks, or overlays — only visuals.
        """
    if channel == "instagram":
        pass
    elif channel == "linkedin":
        enhanced_prompt += " The style should be corporate and sophisticated."
    elif channel == "facebook":
        pass

    model = _gemini_image_model()
    retry_delay = INITIAL_RETRY_DELAY

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[enhanced_prompt],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio=aspect_ratio
                    ),
                ),
            )

            extracted = _extract_image_bytes_and_mime(response)
            if extracted:
                return extracted

            raise ValueError("No image data found in the response.")

        except Exception as e:
            error_str = str(e)
            if _is_rate_limit_error(e) and attempt < MAX_RETRIES:
                retry_delay = _extract_retry_delay(error_str)
                # logger.warning(
                #     f"Gemini image rate limit (attempt {attempt + 1}/{MAX_RETRIES + 1}), "
                #     f"retry in {retry_delay:.2f}s for channel '{channel}'"
                # )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)
                continue

            # logger.error(
            #     f"Error generating image with Gemini API for channel '{channel}': {error_str}"
            # )
            raise

def _extract_retry_delay(error_message: str) -> float:
    """
    Extract retry delay from Gemini API error message.
    Looks for patterns like "Please retry in 32.926273298s"
    """
    # Try to find retry delay in seconds
    match = re.search(r'retry in ([\d.]+)s', error_message, re.IGNORECASE)
    if match:
        try:
            delay = float(match.group(1))
            # Add small buffer (10%) and cap at max delay
            return min(delay * 1.1, MAX_RETRY_DELAY)
        except ValueError:
            pass
    
    # Fallback: try to find delay in RetryInfo
    match = re.search(r'"retryDelay":\s*"(\d+)s"', error_message)
    if match:
        try:
            return min(float(match.group(1)) * 1.1, MAX_RETRY_DELAY)
        except ValueError:
            pass
    
    return INITIAL_RETRY_DELAY


def _is_rate_limit_error(error: Exception) -> bool:
    """Check if error is a rate limit/quota error"""
    error_str = str(error)
    return (
        "429" in error_str or
        "RESOURCE_EXHAUSTED" in error_str or
        "quota" in error_str.lower() or
        "rate limit" in error_str.lower()
    )

def _detect_mime_type(image_bytes_raw: bytes) -> str:
    """Detect MIME type from image magic numbers; falls back to image/jpeg."""
    if len(image_bytes_raw) >= 4 and image_bytes_raw[:4] == b'\x89PNG':
        return "image/png"
    if len(image_bytes_raw) >= 2 and image_bytes_raw[:2] == b'\xff\xd8':
        return "image/jpeg"
    if len(image_bytes_raw) >= 6 and image_bytes_raw[:6] in (b'GIF87a', b'GIF89a'):
        return "image/gif"
    if len(image_bytes_raw) >= 12 and image_bytes_raw[:4] == b'RIFF' and image_bytes_raw[8:12] == b'WEBP':
        return "image/webp"
    return "image/jpeg"


def _decode_image_data_field(data_field: Any) -> bytes:
    """Decode image payload returned by Gemini SDK."""
    if isinstance(data_field, (bytes, bytearray)):
        return bytes(data_field)

    if isinstance(data_field, str):
        # Most Gemini image payloads are base64 strings.
        try:
            return base64.b64decode(data_field, validate=True)
        except Exception:
            # Handle base64url/no-padding variants as fallback.
            normalized = data_field.replace("-", "+").replace("_", "/")
            padded = normalized + ("=" * ((4 - len(normalized) % 4) % 4))
            return base64.b64decode(padded)

    return bytes(data_field)


def _is_image_mime_type(mime_type: Optional[str]) -> bool:
    return bool(mime_type and str(mime_type).lower().startswith("image/"))


def _download_file_uri_bytes(file_uri: str) -> Optional[bytes]:
    """Attempt to download Gemini file URI payload bytes."""
    if not file_uri:
        return None

    try:
        parsed = urlparse(file_uri)
        if parsed.scheme not in ("http", "https"):
            return None
    except Exception:
        return None

    request_timeout_sec = 30
    api_key = get_gemini_api_key()

    # Try authenticated fetch first; fall back to direct fetch.
    attempts = []
    if api_key:
        attempts.append({"params": {"key": api_key}})
    attempts.append({})

    for kwargs in attempts:
        try:
            resp = requests.get(file_uri, timeout=request_timeout_sec, **kwargs)
            if resp.status_code == 200 and resp.content:
                return resp.content
        except Exception:
            continue

    return None


def _extract_image_bytes_and_mime(response: Any) -> Optional[Tuple[bytes, str]]:
    """Extract image bytes from Gemini response across SDK response variants."""
    def _extract_from_inline_data(inline_data: Any) -> Optional[Tuple[bytes, str]]:
        if inline_data is None:
            return None

        if isinstance(inline_data, dict):
            data_field = inline_data.get("data")
            mime = inline_data.get("mime_type") or inline_data.get("mimeType") or "image/png"
        else:
            data_field = getattr(inline_data, "data", None)
            mime = getattr(inline_data, "mime_type", None) or getattr(inline_data, "mimeType", None) or "image/png"

        if data_field is None:
            return None

        decoded = _decode_image_data_field(data_field)
        if not decoded:
            return None
        return decoded, mime

    def _extract_from_file_data(file_data: Any) -> Optional[Tuple[bytes, str]]:
        if file_data is None:
            return None

        if isinstance(file_data, dict):
            file_uri = file_data.get("file_uri") or file_data.get("fileUri")
            mime = file_data.get("mime_type") or file_data.get("mimeType") or "image/png"
        else:
            file_uri = getattr(file_data, "file_uri", None) or getattr(file_data, "fileUri", None)
            mime = getattr(file_data, "mime_type", None) or getattr(file_data, "mimeType", None) or "image/png"

        if not _is_image_mime_type(mime):
            return None

        downloaded_bytes = _download_file_uri_bytes(file_uri)
        if not downloaded_bytes:
            return None
        return downloaded_bytes, mime

    # Primary path: typed SDK candidates -> content -> parts.
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) if content else None
        if not parts:
            continue
        for part in parts:
            extracted = _extract_from_inline_data(getattr(part, "inline_data", None))
            if extracted:
                return extracted
            extracted = _extract_from_file_data(getattr(part, "file_data", None))
            if extracted:
                return extracted

    # Fallback path: recursively inspect dumped payload for inline_data blobs.
    try:
        if hasattr(response, "model_dump"):
            payload = response.model_dump(mode="python", exclude_none=True)
        elif isinstance(response, dict):
            payload = response
        else:
            payload = None
    except Exception:
        payload = None

    def _scan(node: Any) -> Optional[Tuple[bytes, str]]:
        if isinstance(node, dict):
            if "inline_data" in node:
                extracted = _extract_from_inline_data(node["inline_data"])
                if extracted:
                    return extracted
            if "inlineData" in node:
                extracted = _extract_from_inline_data(node["inlineData"])
                if extracted:
                    return extracted
            if "file_data" in node:
                extracted = _extract_from_file_data(node["file_data"])
                if extracted:
                    return extracted
            if "fileData" in node:
                extracted = _extract_from_file_data(node["fileData"])
                if extracted:
                    return extracted
            # Some payloads flatten {mime_type, data} directly.
            if "data" in node and ("mime_type" in node or "mimeType" in node):
                extracted = _extract_from_inline_data(node)
                if extracted:
                    return extracted
            for value in node.values():
                extracted = _scan(value)
                if extracted:
                    return extracted
        elif isinstance(node, list):
            for item in node:
                extracted = _scan(item)
                if extracted:
                    return extracted
        return None

    if payload is not None:
        return _scan(payload)

    return None


def _summarize_response_parts(response: Any) -> str:
    """Build a compact, log-safe summary of candidate part payloads."""
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return "no-candidates"

    candidate_summaries = []
    for index, candidate in enumerate(candidates[:2]):
        parts = getattr(getattr(candidate, "content", None), "parts", None) or []
        part_summaries = []
        for part in parts[:4]:
            text_value = getattr(part, "text", None)
            text_len = len(text_value) if isinstance(text_value, str) else 0

            inline_data = getattr(part, "inline_data", None)
            inline_mime = getattr(inline_data, "mime_type", None) if inline_data is not None else None

            file_data = getattr(part, "file_data", None)
            file_mime = getattr(file_data, "mime_type", None) if file_data is not None else None
            file_uri = getattr(file_data, "file_uri", None) if file_data is not None else None
            file_uri_host = ""
            if file_uri:
                try:
                    file_uri_host = urlparse(file_uri).netloc
                except Exception:
                    file_uri_host = "invalid-uri"

            part_summaries.append(
                f"text_len={text_len},inline_mime={inline_mime},"
                f"file_mime={file_mime},file_uri_host={file_uri_host}"
            )

        finish_reason = getattr(candidate, "finish_reason", None)
        candidate_summaries.append(
            f"candidate{index}(finish={finish_reason},parts=[{' ; '.join(part_summaries)}])"
        )

    return " | ".join(candidate_summaries)


async def generate_edited_image(
    image_bytes: bytes,
    edit_instruction: str,
    channel: str,
    aspect_ratio: str,
) -> Optional[Tuple[bytes, str]]:
    """
    Edit an existing image using Gemini's image model.

    The original image is sent as visual context so style, lighting and composition
    are preserved. The user's free-form `edit_instruction` overrides only the
    aspects it explicitly mentions (subjects, scenery, mood, etc.).

    Returns (image_bytes, mime_type) on success, or None if all retries fail.
    """
    if not image_bytes:
        # logger.error("generate_edited_image called with empty image bytes")
        return None

    edit_instruction = (edit_instruction or "").strip()
    if not edit_instruction:
        # logger.error("generate_edited_image called with empty edit_instruction")
        return None

    mime_type = _detect_mime_type(image_bytes)
    channel_lower = (channel or "").lower()
    aspect_ratio = ASPECT_RATIOS.get(aspect_ratio.lower(), "1:1")

    prompt_text = f"""You are editing the provided image for a {channel_lower or 'social media'} post.

USER EDIT INSTRUCTION (highest priority — overrides anything in the original image that conflicts):
{edit_instruction}

RULES:
1. Start from the provided image. Keep its overall style, art direction, lighting and color tone unless the instruction changes them.
2. Apply ONLY the changes described in the user instruction. Do not invent unrelated changes.
3. The output must be a single photorealistic, professional, marketing-quality image.
4. Maintain an aspect ratio of {aspect_ratio}.
5. Do NOT include any text, words, letters, logos, watermarks or overlays in the image.
6. Do NOT return the image unchanged — apply the requested edit.
"""

    primary_model = _gemini_image_model()
    model_candidates = []
    for model_name in [
        primary_model,
        "gemini-3.1-flash-image-preview",
        "gemini-3-pro-image-preview",
    ]:
        if model_name and model_name not in model_candidates:
            model_candidates.append(model_name)
    retry_delay = INITIAL_RETRY_DELAY

    for attempt in range(MAX_RETRIES + 1):
        try:
            contents_list = [
                {
                    "parts": [
                        {"text": prompt_text},
                        {"inline_data": {"mime_type": mime_type, "data": image_bytes}},
                    ]
                }
            ]

            # logger.debug(
            #     f"Requesting image edit (attempt {attempt + 1}) "
            #     f"channel='{channel_lower}' instruction_len={len(edit_instruction)}"
            # )

            response = None
            final_error: Optional[Exception] = None
            final_finish_reason = None
            last_model_exception: Optional[Exception] = None

            for model_name in model_candidates:
                try:
                    # logger.debug(
                    #     f"Submitting image edit request with model '{model_name}' "
                    #     f"(attempt {attempt + 1})"
                    # )
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents_list,
                        config=types.GenerateContentConfig(
                            response_modalities=["IMAGE"],
                            image_config=types.ImageConfig(
                                aspect_ratio=aspect_ratio,
                            ),
                        ),
                    )
                except Exception as model_error:
                    last_model_exception = model_error
                    # logger.warning(
                    #     "Image edit model request failed "
                    #     f"(model='{model_name}', attempt={attempt + 1}): {model_error}"
                    # )
                    continue

                extracted = _extract_image_bytes_and_mime(response)
                if extracted:
                    result_bytes, result_mime_type = extracted
                    # logger.info(
                    #     f"Successfully edited image for channel '{channel_lower}' "
                    #     f"using model '{model_name}' "
                    #     f"(size: {len(result_bytes)/1024:.1f} KB)"
                    # )
                    return result_bytes, result_mime_type

                candidates = getattr(response, "candidates", None) or []
                if candidates:
                    final_finish_reason = getattr(candidates[0], "finish_reason", None)
                    # logger.warning(
                    #     "Gemini image edit returned no extractable image "
                    #     f"(model='{model_name}', finish_reason={final_finish_reason}, "
                    #     f"channel='{channel_lower}', parts_summary={_summarize_response_parts(response)})"
                    # )
                else:
                    # logger.warning(
                    #     "Gemini image edit returned no candidates "
                    #     f"(model='{model_name}', channel='{channel_lower}')"
                    # )
                    pass

            if response is None and last_model_exception is not None:
                final_error = last_model_exception
            elif response is None:
                final_error = ValueError("No model response received for image edit.")
            else:
                final_error = ValueError(
                    "No image data found in the edit response "
                    f"(finish_reason={final_finish_reason})"
                )

            raise final_error

        except Exception as e:
            error_str = str(e)

            if _is_rate_limit_error(e) and attempt < MAX_RETRIES:
                retry_delay = _extract_retry_delay(error_str)
                # logger.warning(
                #     f"Image edit rate limit (attempt {attempt + 1}/{MAX_RETRIES + 1}), "
                #     f"retry in {retry_delay:.2f}s for channel '{channel_lower}'"
                # )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)
                continue

            if attempt == MAX_RETRIES:
                # logger.error(
                #     f"Error editing image after {MAX_RETRIES + 1} attempts: {error_str}",
                #     exc_info=True,
                # )
                return None

            # logger.error(
            #     f"Error editing image (attempt {attempt + 1}): {error_str}"
            # )
            break

    return None





from products.market_planner.schema.content_schema import GeneratedPost


def _mime_type_for_product_format(image_format: str) -> str:
    fmt = (image_format or "jpeg").lower().lstrip(".")
    if fmt == "jpg":
        fmt = "jpeg"
    if fmt not in ("png", "jpeg", "webp", "gif"):
        fmt = "jpeg"
    return f"image/{fmt}"


async def generate_post_from_product_with_gemini(
    company_payload: Dict[str, Any],
    product_images: List[Tuple[bytes, str]],
    theme: str,
    channel: str,
    aspect_ratio: str,
 ) -> GeneratedPost:
    """
    Generate a single social post image with one or two product reference images via Gemini.
    When two images are supplied, the model is instructed to feature both products if they differ.
    """
    if not product_images or len(product_images) > 2:
        raise ValueError("product_images must contain 1 or 2 (bytes, format) entries")

    industry = company_payload.get('industry', '')
    target_group = company_payload.get('target_group', '')
    two_refs = len(product_images) == 2

    aspect_ratio_str = ASPECT_RATIOS.get(aspect_ratio.lower(), "1:1")
    multi_product_instructions = ""
    if two_refs:
        multi_product_instructions = """
        REFERENCE IMAGES: You are given TWO images. They may show the same product from different angles or TWO DIFFERENT PRODUCTS.
        - If they are different products, the final image MUST clearly include BOTH products in one cohesive composition (natural pairing, lifestyle scene, or side-by-side), and each product must stay recognizable.
        - If they are the same product, treat as one hero product with richer context.
        """

    style_prompt = f"""
        Create an engaging lifestyle social media post featuring {"these products" if two_refs else "this product"}.
        {multi_product_instructions}
        CRITICAL REQUIREMENT:
        - The product{"s" if two_refs else ""} from the reference image{"s" if two_refs else ""} MUST remain clearly visible and identifiable
        - The product{"s" if two_refs else ""} should be naturally integrated into a lifestyle setting
        - The image should be aligned with the theme: {theme}
        - The image will be used for {channel}
        - The image strictly should not have any overlays, text, logos, watermarks, or any other elements
        
        Style: Lifestyle, aspirational, showing product in use
        Industry: {industry}
        Target Audience: {target_group}
        Platform: {channel}
        """

    def _parts_for_prompt() -> list:
        parts: list = [{"text": style_prompt}]
        for img_bytes, img_fmt in product_images:
            parts.append({
                "inline_data": {
                    "mime_type": _mime_type_for_product_format(img_fmt),
                    "data": img_bytes,
                }
            })
        return parts

    content_item = {"parts": _parts_for_prompt()}

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=[content_item],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio=aspect_ratio_str,
                ),
            ),
        )

        extracted = _extract_image_bytes_and_mime(response)
        if extracted:
            generated_image, mime = extracted
            fmt = mime.split("/")[-1] if "/" in mime else "png"
            image_base64 = base64.b64encode(generated_image).decode('utf-8')
            return GeneratedPost(
                channel=channel,
                image_data=image_base64,
                format=fmt,
            )
    except Exception as e:
        # logger.error(f"Error generating post image with Gemini: {str(e)}")
        pass

    # Fallback: first reference image only
    fb_bytes, fb_fmt = product_images[0]
    image_base64 = base64.b64encode(fb_bytes).decode('utf-8')
    return GeneratedPost(
        channel=channel,
        image_data=image_base64,
        format=fb_fmt if fb_fmt else "jpeg",
    )












    