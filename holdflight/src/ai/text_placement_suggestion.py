# Placeholder file - Copy your holdflight/src/ai/text_placement_suggestion.py content here
import base64
import json
import requests
import time
import re
import os
from PIL import Image, ImageFilter, ImageStat
from io import BytesIO
from openai import OpenAI
from dotenv import load_dotenv
from holdflight.src.utils.chrome_options import safe_get

# Load environment variables from .env file
load_dotenv()

# --- Download image with retry ---
def download_image(url, retries=3, delay=2, verbose=True):
    for attempt in range(1, retries + 1):
        if verbose:
            print(f"📥 Downloading image (attempt {attempt}/{retries})...")
        try:
            response = safe_get(requests, url, timeout=10)
            if response.status_code == 200:
                if verbose:
                    print("✅ Image downloaded successfully.\n")
                return response.content
        except Exception as e:
            if verbose:
                print(f"⚠️ Attempt {attempt} failed: {e}")
            if attempt < retries:
                time.sleep(delay)
    if verbose:
        print("❌ Could not download the image after retries.")
    return None


def _infer_typographic_weight_from_image(img: Image.Image) -> str:
    """
    Map low-level image stats to a font_weight hint for prompts and fallbacks.
    Busy / high-detail images → medium (bold body fights texture). Very flat → light/medium.
    High global luminance contrast without extreme edges → bold (posters, strong graphics).
    """
    try:
        g = img.convert("L")
        w, h = g.size
        m = max(w, h)
        if m > 512:
            r = 512 / m
            _lanczos = getattr(Image, "Resampling", Image).LANCZOS
            g = g.resize((max(1, int(w * r)), max(1, int(h * r))), _lanczos)
        edges = g.filter(ImageFilter.FIND_EDGES)
        edge_mean = ImageStat.Stat(edges).mean[0]
        lum_std = ImageStat.Stat(g).stddev[0]
        # Typical ranges: edge_mean ~3–35, lum_std ~15–70
        if edge_mean > 20:
            return "medium"
        if edge_mean < 6 and lum_std < 22:
            return "light"
        if edge_mean < 12 and lum_std < 30:
            return "medium"
        if lum_std > 48 and edge_mean < 25:
            return "bold"
        if edge_mean >= 12:
            return "medium"
        return "medium"
    except Exception:
        return "medium"


# --- Analyze image dimensions ---
def analyze_image(image_bytes):
    """Analyze image to determine appropriate text sizing"""
    try:
        # Open image and ensure we get full dimensions (not thumbnail)
        img = Image.open(BytesIO(image_bytes))
        
        # Load the full image to ensure we get actual dimensions
        img.load()
        
        width, height = img.size
        
        # Log actual dimensions for debugging
        print(f"🔍 Image dimensions detected: {width}x{height} pixels")
        print(f"🔍 Image format: {img.format}, mode: {img.mode}")
        
        # Verify dimensions are reasonable (not 0 or extremely large)
        if width <= 0 or height <= 0:
            print(f"⚠️ Invalid dimensions: {width}x{height}")
            return None
        
        if width > 100000 or height > 100000:
            print(f"⚠️ Suspiciously large dimensions: {width}x{height}")
            return None
        
        # Calculate base font size (2-4% of image width is typical)
        base_font_size = int(width * 0.035)
        
        # Determine size category
        total_pixels = width * height
        if total_pixels > 2000000:  # Large (e.g., 2000x1000+)
            size_category = "large"
            recommended_sizes = [base_font_size, int(base_font_size * 1.3), int(base_font_size * 0.7)]
        elif total_pixels > 500000:  # Medium (e.g., 1000x500)
            size_category = "medium"
            recommended_sizes = [base_font_size, int(base_font_size * 1.2), int(base_font_size * 0.8)]
        else:  # Small
            size_category = "small"
            recommended_sizes = [base_font_size, int(base_font_size * 1.15), int(base_font_size * 0.85)]
        
        # Aspect ratio analysis
        aspect_ratio = width / height
        if aspect_ratio > 2:
            orientation = "wide (banner-style)"
        elif aspect_ratio < 0.7:
            orientation = "tall (portrait)"
        else:
            orientation = "balanced"
        
        typographic_weight_hint = _infer_typographic_weight_from_image(img)

        result = {
            "width": width,
            "height": height,
            "size_category": size_category,
            "orientation": orientation,
            "base_font_size": base_font_size,
            "recommended_sizes": recommended_sizes,
            "total_pixels": total_pixels,
            "typographic_weight_hint": typographic_weight_hint,
        }
        
        # Log the analysis result
        print(
            f"✅ Image analysis complete: {width}x{height}, category: {size_category}, "
            f"base_font: {base_font_size}px, typographic_weight_hint: {typographic_weight_hint}"
        )
        
        return result
    except Exception as e:
        print(f"⚠️ Could not analyze image: {e}")
        import traceback
        traceback.print_exc()
        return None


def build_brand_context(
    *,
    theme_colors,
    fonts_typography,
    matched_fonts,
    colors_from_logo=None,
):
    """Canonical scraped brand payload — colors + one unified `fonts` list (scraped-only names)."""
    theme = theme_colors if isinstance(theme_colors, list) else []
    theme = [c for c in theme[:16] if c]

    logo_colors = colors_from_logo if isinstance(colors_from_logo, list) else []
    logo_colors = [c for c in logo_colors[:8] if c]

    typo = fonts_typography if isinstance(fonts_typography, list) else []
    typo = [str(f) for f in typo[:24] if f]

    matched = matched_fonts if isinstance(matched_fonts, dict) else {}

    fonts_list = []
    seen_lower = set()

    def push_font(label):
        if not label:
            return
        s = str(label).strip()
        if not s:
            return
        key = s.lower()
        if key in seen_lower:
            return
        seen_lower.add(key)
        fonts_list.append(s)

    for raw in typo:
        push_font(raw)
    for scraped_name, info in list(matched.items())[:16]:
        push_font(scraped_name)
        if isinstance(info, dict):
            push_font(info.get("family"))

    return {
        "theme_colors": theme,
        "colors_from_logo": logo_colors,
        "fonts": fonts_list,
    }


def build_brand_context_from_analysis(analysis: dict) -> dict:
    """Maps full WebsiteAnalyzer output into build_brand_context()."""
    if not analysis or not isinstance(analysis, dict):
        return {}

    return build_brand_context(
        theme_colors=analysis.get("theme_colors") or [],
        fonts_typography=analysis.get("fonts_typography") or [],
        matched_fonts=analysis.get("matched_fonts") or {},
        colors_from_logo=analysis.get("colors_from_logo") or [],
    )


def _strip_reason_field(obj):
    """Ensure model output does not include a reason field."""
    if isinstance(obj, dict) and "reason" in obj:
        out = dict(obj)
        del out["reason"]
        return out
    return obj


def _normalize_hex(color):
    if not color:
        return None
    s = str(color).strip()
    if re.match(r"^#[0-9a-fA-F]{6}$", s):
        return s.lower()
    if re.match(r"^[0-9a-fA-F]{6}$", s):
        return f"#{s.lower()}"
    if re.match(r"^#[0-9a-fA-F]{3}$", s):
        r, g, b = s[1], s[2], s[3]
        return f"#{r}{r}{g}{g}{b}{b}".lower()
    return None


# Legacy anchor names → approximate normalized (x,y) for the text anchor point
# (fraction of width, fraction of height; origin top-left).
_POSITION_LEGACY_TO_XY = {
    "top_left": (0.15, 0.14),
    "top_center": (0.5, 0.14),
    "top_right": (0.85, 0.14),
    "center_left": (0.15, 0.5),
    "center": (0.5, 0.5),
    "center_right": (0.85, 0.5),
    "bottom_left": (0.15, 0.88),
    "bottom_center": (0.5, 0.88),
    "bottom_right": (0.85, 0.88),
}


def _clamp_unit(v):
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return max(0.0, min(1.0, f))
    except (TypeError, ValueError):
        return None


def _default_xy_from_image_orientation(image_info):
    """Anchors biased by aspect / orientation hint (fallback when x,y missing)."""
    if not image_info or not isinstance(image_info, dict):
        return 0.5, 0.88
    w = float(image_info.get("width") or 1024)
    h = float(image_info.get("height") or 1024)
    aspect = (w / h) if h else 1.0
    orientation = str(image_info.get("orientation") or "").lower()
    if "wide" in orientation or "banner" in orientation or aspect >= 1.85:
        return 0.5, 0.90
    if "portrait" in orientation or "tall" in orientation or aspect <= 0.65:
        return 0.5, 0.82
    if "balanced" in orientation:
        return 0.5, 0.86
    if aspect >= 1.35:
        return 0.5, 0.89
    return 0.5, 0.86


def finalize_suggestion_coordinates(suggestion, image_info):
    """
    Ensure suggestion uses normalized x,y in [0, 1] relative to canvas width and height.

    Consumers (e.g. POST /textplacement) map these with the same rule as rendered pixels:
    center at ``round(x * (width - 1))``, ``round(y * (height - 1))`` for that image.

    Removes legacy categorical ``position``. Pixel fields are not returned — only these fractions.
    """
    if not suggestion or not isinstance(suggestion, dict):
        return suggestion

    fx = _clamp_unit(suggestion.get("x"))
    fy = _clamp_unit(suggestion.get("y"))
    legacy = suggestion.get("position")

    if (fx is None or fy is None) and legacy is not None:
        key = str(legacy).strip().lower().replace(" ", "_")
        tup = _POSITION_LEGACY_TO_XY.get(key)
        if tup:
            lx, ly = tup
            if fx is None:
                fx = lx
            if fy is None:
                fy = ly

    dfx, dfy = _default_xy_from_image_orientation(image_info)
    if fx is None:
        fx = dfx
    if fy is None:
        fy = dfy

    fx = _clamp_unit(fx) if fx is not None else 0.5
    fy = _clamp_unit(fy) if fy is not None else 0.86

    out = dict(suggestion)
    out.pop("position", None)
    out.pop("x_px", None)
    out.pop("y_px", None)

    out["x"] = round(float(fx), 5)
    out["y"] = round(float(fy), 5)
    return out


def scraped_color_palette_hex(brand_context):
    palette = []
    if not isinstance(brand_context, dict):
        return palette
    for key in ("theme_colors", "colors_from_logo"):
        for c in brand_context.get(key) or []:
            hc = _normalize_hex(c)
            if hc and hc not in palette:
                palette.append(hc)
    return palette


def scraped_font_names_list(brand_context):
    if not isinstance(brand_context, dict):
        return []

    raw = brand_context.get("fonts")
    if isinstance(raw, list) and raw:
        out, seen = [], set()
        for x in raw:
            s = str(x).strip()
            if not s or s.lower() in seen:
                continue
            seen.add(s.lower())
            out.append(s)
        return out

    out, seen = [], set()

    def push(label):
        if not label:
            return
        s = str(label).strip()
        if not s or s.lower() in seen:
            return
        seen.add(s.lower())
        out.append(s)

    for raw in brand_context.get("fonts_typography") or []:
        push(raw)

    gf = brand_context.get("google_fonts")
    if isinstance(gf, dict):
        for scraped_name, info in gf.items():
            push(scraped_name)
            if isinstance(info, dict):
                push(info.get("family"))
    elif isinstance(gf, list):
        for entry in gf:
            if isinstance(entry, dict):
                push(entry.get("scraped_font_name") or entry.get("google_font_family"))
                push(entry.get("family"))
    return out


def ensure_colors_array_only(suggestion):
    """Use only `colors` (list of hex); drop legacy singular `color` and normalize entries."""
    if not isinstance(suggestion, dict):
        return suggestion
    o = dict(suggestion)
    legacy = o.pop("color", None)

    out_list = []
    raw = o.get("colors")
    if isinstance(raw, list):
        for c in raw:
            hc = _normalize_hex(c)
            if hc and hc not in out_list:
                out_list.append(hc)
    elif isinstance(raw, str):
        hc = _normalize_hex(raw)
        if hc:
            out_list.append(hc)

    hc_legacy = _normalize_hex(legacy)
    if hc_legacy and hc_legacy not in out_list:
        out_list.insert(0, hc_legacy)

    o["colors"] = out_list
    return o


def apply_scraped_brand_to_suggestion(suggestion, brand_context):
    """
    Set color/fonts from scrape only — no AI guesses. `colors` lists every scraped hex;
    `fonts` lists every scraped font name. No singular `color` field.
    """
    if not suggestion or not isinstance(suggestion, dict):
        return suggestion
    if not brand_context or not isinstance(brand_context, dict):
        return suggestion

    out = dict(suggestion)
    for key in ("color", "colors", "font_family"):
        out.pop(key, None)

    palette = scraped_color_palette_hex(brand_context)
    out["colors"] = palette

    out["fonts"] = scraped_font_names_list(brand_context)

    out.pop("google_font_family", None)
    out.pop("google_font_id", None)

    return out


def strip_google_font_id_fields(obj):
    if not isinstance(obj, dict):
        return obj
    o = dict(obj)
    o.pop("google_font_family", None)
    o.pop("google_font_id", None)
    return o


_ALLOWED_FONT_WEIGHTS = frozenset({"light", "medium", "bold", "extra_bold"})


def _normalize_font_weight_value(raw, hint: str) -> str:
    """Map model output to allowed weights; invalid strings fall back to image-derived hint."""
    if hint not in _ALLOWED_FONT_WEIGHTS:
        hint = "medium"
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return hint
    s = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "normal": "medium",
        "regular": "medium",
        "semibold": "bold",
        "semi_bold": "bold",
        "demibold": "bold",
        "heavy": "bold",
        "black": "extra_bold",
        "extrabold": "extra_bold",
    }
    s = aliases.get(s, s)
    w = s if s in _ALLOWED_FONT_WEIGHTS else hint
    if w == "bold" and hint == "light":
        return "medium"
    if w == "extra_bold" and hint in ("light", "medium"):
        return "bold"
    return w


def _guess_mime_from_bytes(image_bytes: bytes) -> str:
    if not image_bytes or len(image_bytes) < 12:
        return "image/png"
    b = image_bytes
    if b[:2] == b"\xff\xd8":
        return "image/jpeg"
    if len(b) >= 8 and b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:2] == b"BM":
        return "image/bmp"
    return "image/png"


def _default_logo_anchor(image_info):
    """
    Fallback center for a small brand mark: top area, end side — keeps clear of bottom body copy.
    """
    if not image_info or not isinstance(image_info, dict):
        return 0.92, 0.10
    aspect = float(image_info.get("width") or 1024) / max(
        1.0, float(image_info.get("height") or 1024)
    )
    orientation = str(image_info.get("orientation") or "").lower()
    if "wide" in orientation or "banner" in orientation or aspect >= 1.85:
        return 0.94, 0.10
    if "portrait" in orientation or "tall" in orientation or aspect <= 0.65:
        return 0.90, 0.08
    return 0.92, 0.10


def _logo_aspect_ratio_from_bytes(logo_bytes):
    try:
        with Image.open(BytesIO(logo_bytes)) as logo_img:
            logo_img.load()
            w, h = logo_img.size
            if w > 0 and h > 0:
                return float(w) / float(h)
    except Exception:
        pass
    return None


def _default_logo_max_width_ratio(image_info, logo_aspect_ratio=None):
    """Fallback logo width as a fraction of canvas width."""
    ratio = 0.18
    if image_info and isinstance(image_info, dict):
        aspect = float(image_info.get("width") or 1024) / max(
            1.0, float(image_info.get("height") or 1024)
        )
        orientation = str(image_info.get("orientation") or "").lower()
        if "wide" in orientation or "banner" in orientation or aspect >= 1.85:
            ratio = 0.14
        elif "portrait" in orientation or "tall" in orientation or aspect <= 0.65:
            ratio = 0.20

    if logo_aspect_ratio:
        if logo_aspect_ratio >= 4.0:
            ratio *= 0.85
        elif logo_aspect_ratio <= 0.6:
            ratio *= 0.9

    return round(max(0.02, min(0.5, ratio)), 4)


def _normalize_logo_max_width_ratio(raw, image_info, logo_aspect_ratio=None):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = _default_logo_max_width_ratio(image_info, logo_aspect_ratio)
    return round(max(0.02, min(0.5, value)), 4)


def finalize_logo_placement(placement_frag, image_info):
    """Normalize logo anchor and max width ratio for the render endpoint."""
    frag = placement_frag or {}
    fx = _clamp_unit(frag.get("x"))
    fy = _clamp_unit(frag.get("y"))
    if fx is None or fy is None:
        fx, fy = _default_logo_anchor(image_info)
    out = finalize_suggestion_coordinates({"x": fx, "y": fy}, image_info)
    size_raw = (
        frag.get("logo_max_width_ratio")
        if isinstance(frag, dict)
        else None
    )
    if size_raw is None and isinstance(frag, dict):
        size_raw = frag.get("max_width_ratio")
    if size_raw is None and isinstance(frag, dict):
        size_raw = frag.get("width_ratio")
    logo_aspect_ratio = frag.get("_logo_aspect_ratio") if isinstance(frag, dict) else None
    return {
        "x": out["x"],
        "y": out["y"],
        "logo_max_width_ratio": _normalize_logo_max_width_ratio(
            size_raw,
            image_info,
            logo_aspect_ratio,
        ),
    }


def _logo_placement_with_fallback_size(placement_frag, image_info, logo_aspect_ratio=None):
    frag = dict(placement_frag or {})
    if logo_aspect_ratio is not None:
        frag["_logo_aspect_ratio"] = logo_aspect_ratio
    return finalize_logo_placement(frag, image_info)


def get_logo_placement_suggestion(
    canvas_image_url: str,
    logo_image_url: str,
    image_info=None,
    verbose: bool = True,
    api_key=None,
):
    """
    Use vision to pick normalized (x, y) on the canvas for the center of the scraped logo asset.
    Sends the canvas image first, then the logo image, so the model can respect composition.
    """
    out_err = {"success": False, "error": None, "logo_placement": None}
    if not canvas_image_url or not logo_image_url:
        out_err["error"] = "canvas_image_url and logo_image_url are required"
        return out_err

    canvas_bytes = download_image(canvas_image_url, verbose=verbose)
    if not canvas_bytes:
        out_err["error"] = "Failed to download canvas image"
        return out_err

    logo_bytes = download_image(logo_image_url, verbose=verbose)
    if not logo_bytes:
        out_err["error"] = "Failed to download logo image"
        return out_err
    logo_aspect_ratio = _logo_aspect_ratio_from_bytes(logo_bytes)

    if not api_key:
        api_key = os.environ.get("HOLDFLIGHT_OPENAI_API_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        )
    if not api_key:
        out_err["error"] = (
            "HOLDFLIGHT_OPENAI_API_KEY or OPENAI_API_KEY not set — cannot infer logo placement"
        )
        return out_err

    img_width = int((image_info or {}).get("width") or 0) or None
    img_height = int((image_info or {}).get("height") or 0) or None
    if not img_width or not img_height:
        analyzed = analyze_image(canvas_bytes)
        if analyzed:
            image_info = analyzed
            img_width = analyzed["width"]
            img_height = analyzed["height"]

    img_width = img_width or 1080
    img_height = img_height or 1080
    img_orientation = (
        str((image_info or {}).get("orientation") or "").strip() or "balanced"
    )

    canvas_mime = _guess_mime_from_bytes(canvas_bytes)
    logo_mime = _guess_mime_from_bytes(logo_bytes)

    prompt_text = (
        "You place a brand logo on a marketing/ad creative (first image).\n"
        "The SECOND image is the actual logo artwork to overlay (preserve aspect ratio in your reasoning).\n\n"
        f"Canvas size: {img_width}×{img_height} px; composition hint: {img_orientation}.\n\n"
        "Choose one anchor point and one size on the FIRST image:\n"
        "- x: float 0–1 (0 left edge of canvas, 1 right)\n"
        "- y: float 0–1 (0 top, 1 bottom)\n"
        "- logo_max_width_ratio: float 0.02–0.50, the maximum rendered logo width as a fraction of canvas width.\n"
        "Pick clear space typical for watermarks/submarks: corners or top bands, avoiding subjects' faces, "
        "primary product focus, large existing text blocks, or busy clutter. "
        "Use margins ~0.06–0.14 from edges (so x/y not exactly 0 or 1). "
        "Choose a tasteful logo size: usually 0.10–0.22; smaller on busy images or very wide logos, "
        "larger only when the canvas has clear whitespace.\n\n"
        "Return ONLY JSON, one object with keys x, y, and logo_max_width_ratio (numbers only). "
        'Example: {"x": 0.91, "y": 0.11, "logo_max_width_ratio": 0.16}\n'
    )

    base_url = os.getenv("OPENAI_API_URL") or os.getenv("OPENAI_BASE_URL")
    if base_url:
        client = OpenAI(api_key=api_key, base_url=base_url)
    else:
        client = OpenAI(api_key=api_key)
    try:
        c_b64 = base64.b64encode(canvas_bytes).decode("utf-8")
        l_b64 = base64.b64encode(logo_bytes).decode("utf-8")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{canvas_mime};base64,{c_b64}"
                            },
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{logo_mime};base64,{l_b64}"
                            },
                        },
                    ],
                }
            ],
            max_tokens=200,
            temperature=0.35,
        )
        content = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        if verbose:
            print(f"⚠️ Logo placement GPT failed: {exc}")
        fx, fy = _default_logo_anchor(image_info or {"width": img_width, "height": img_height})
        placement = _logo_placement_with_fallback_size(
            {"x": fx, "y": fy},
            image_info,
            logo_aspect_ratio,
        )
        return {"success": True, "error": None, "logo_placement": placement}

    parsed = None
    if content:
        try:
            json_text = re.search(r"\{[\s\S]*\}", content)
            if json_text:
                parsed = json.loads(json_text.group(0))
        except Exception as exc:
            if verbose:
                print(f"⚠️ Logo placement JSON parse failed: {exc}")

    if isinstance(parsed, dict) and parsed.get("x") is not None and parsed.get("y") is not None:
        placement = _logo_placement_with_fallback_size(
            parsed,
            image_info,
            logo_aspect_ratio,
        )
        if verbose:
            print(
                "✅ Logo placement (AI): "
                f"x={placement['x']} y={placement['y']} "
                f"logo_max_width_ratio={placement['logo_max_width_ratio']}"
            )
        return {"success": True, "error": None, "logo_placement": placement}

    if verbose:
        print("⚠️ Logo placement fallback to default corner anchor")
    fx, fy = _default_logo_anchor(image_info or {"width": img_width, "height": img_height})
    placement = _logo_placement_with_fallback_size(
        {"x": fx, "y": fy},
        image_info,
        logo_aspect_ratio,
    )
    return {"success": True, "error": None, "logo_placement": placement}


def get_text_placement_suggestions(
    image_url,
    text,
    verbose=True,
    api_key=None,
    brand_context=None,
):
    """
    Get a single text placement suggestion for an image using GPT-4o-mini.

    Args:
        image_url: Public URL of the image
        text: Text to place on the image
        verbose: Whether to print progress messages (default: True)
        api_key: OpenAI API key (optional)
        brand_context: Optional dict — brand colors and Google font families.

    Returns:
        Dictionary with 'success', 'suggestions' (one dict, no reason field), optional 'image_info',
        or 'error'.
    """
    try:
        if verbose:
            print("=== 🧠 Smart Text Placement Suggester (Image-Aware Sizing) ===\n")
        
        # Download image
        image_bytes = download_image(image_url, verbose=verbose)
        if not image_bytes:
            return {
                'success': False,
                'error': 'Failed to download image. Please check your URL or connection.',
                'suggestions': [],
                'image_info': None,
            }

        # Log image download info
        if verbose:
            print(f"📥 Downloaded image size: {len(image_bytes)} bytes")
            print(f"🔗 Image URL: {image_url}")

        # Analyze the image
        image_info = analyze_image(image_bytes)
        
        if not image_info:
            if verbose:
                print("⚠️ Failed to analyze image, using default dimensions")
            # Return default image info if analysis fails
            image_info = {
                "width": 1024,
                "height": 1024,
                "size_category": "medium",
                "orientation": "balanced",
                "base_font_size": 35,
                "recommended_sizes": [35, 42, 28],
                "total_pixels": 1048576,
                "typographic_weight_hint": "medium",
            }
        if image_info and verbose:
            print("📊 IMAGE ANALYSIS")
            print("="*60)
            print(f"📐 Dimensions: {image_info['width']}x{image_info['height']} pixels")
            print(f"📏 Size Category: {image_info['size_category'].upper()}")
            print(f"🖼️  Orientation: {image_info['orientation']}")
            print(f"🔤 Calculated Base Font Size: {image_info['base_font_size']}px")
            print("="*60 + "\n")

        text_length = len(text)
        word_count = len(text.split())

        weight_hint = (image_info or {}).get("typographic_weight_hint") or "medium"
        default_weight = weight_hint
        if text_length > 140:
            default_weight = "medium"
        elif text_length > 90 and default_weight in ("bold", "extra_bold"):
            default_weight = "medium"

        # Use provided API key or get from environment variable (try holdflight-specific key first)
        if not api_key:
            api_key = os.environ.get('HOLDFLIGHT_OPENAI_API_KEY') or os.environ.get('OPENAI_API_KEY')
        
        if not api_key:
            if verbose:
                print("\n⚠️ WARNING: HOLDFLIGHT_OPENAI_API_KEY or OPENAI_API_KEY environment variable is not set. Please set it in your .env file.")
            return {
                'success': False,
                'error': 'HOLDFLIGHT_OPENAI_API_KEY or OPENAI_API_KEY environment variable is not set. Please set it in your .env file.',
                'suggestions': [],
                'image_info': image_info,
            }
        else:
            # Use OpenAI client
            base_url = os.getenv("OPENAI_API_URL") or os.getenv("OPENAI_BASE_URL")
            if base_url:
                client = OpenAI(api_key=api_key, base_url=base_url)
            else:
                client = OpenAI(api_key=api_key)
            
            # Enhanced prompt with image context
            sizing_context = ""
            if image_info:
                tw_hint = image_info.get("typographic_weight_hint") or "medium"
                sizing_context = f"""
IMAGE CONTEXT FOR LAYOUT AND SIZING:
- Pixel dimensions — width W={image_info['width']} px, height H={image_info['height']} px
- Aspect / orientation hint: {image_info['orientation']} (tie x,y placement to this).
- Calculated base font size (from image width): {image_info['base_font_size']} px
- Text length: {text_length} characters ({word_count} words)

TYPOGRAPHIC WEIGHT (server measured edge/detail and luminance contrast on THIS image — use with what you see in the picture):
- Suggested font_weight: "{tw_hint}" (one of light, medium, bold, extra_bold).
- Look at existing text, logos, and UI in the image: match their visual weight when obvious.
- Do NOT default to bold. Use bold or extra_bold only when the composition or existing type clearly calls for heavy weight; on busy photos or fine typography prefer light or medium.

Use W and H to choose placement: x,y are normalized to this width and height (see below).
"""

            # Use actual image dimensions instead of hardcoded values
            img_width = image_info['width'] if image_info else 1536
            img_height = image_info['height'] if image_info else 1024
            img_orientation = image_info['orientation'] if image_info else 'balanced'

            using_scraped_brand = bool(brand_context and isinstance(brand_context, dict))

            xy_instructions = (
                "PLACEMENT AXES (mandatory — do not use named positions like bottom_center):\n"
                f"- x: float between 0.0 and 1.0 → horizontal anchor as a fraction of image WIDTH ({img_width}px). "
                "0 = left edge, 1 = right edge — keep typical text inside ~0.05–0.95 for margins.\n"
                f"- y: float between 0.0 and 1.0 → vertical anchor as a fraction of image HEIGHT ({img_height}px). "
                "0 = top edge, 1 = bottom edge.\n"
                f"Base x,y on the actual composition, clear space, faces, clutter, aspect ratio ({img_width}:{img_height}), "
                f"and the orientation/context note: '{img_orientation}'. "
                "The server derives pixel anchors from W,H using your x,y — they must correspond to THIS image.\n\n"
            )

            if using_scraped_brand:
                prompt_text = (
                    "You are a creative design assistant. Analyze the given image and propose "
                    "ONE best way to place the text.\n\n"
                    "Website text color and fonts are supplied separately by the server from a scrape — "
                    "do NOT include color or any font identifiers in your answer.\n\n"
                    f"Image dimensions: width {img_width} px × height {img_height} px.\n\n"
                    f"Text: '{text}'\n\n"
                    + sizing_context
                    + xy_instructions
                    + "Return exactly ONE JSON object with ONLY these keys (no 'reason', no 'position' field):\n"
                    "- lines: list of split lines for the text. Split ONLY by natural length or '\\n' if "
                    "provided — DO NOT change, reword, or add punctuation to the text.\n"
                    "- x and y as defined above.\n"
                    f"- font_size: integer, scaled appropriately for this {img_width}×{img_height} px image.\n"
                    "- font_weight: exactly one of ['light', 'medium', 'bold', 'extra_bold'] — choose from the image and the suggested weight above, not from habit.\n"
                    "- text_width: one of ['narrow', 'normal', 'wide', 'extra_wide'].\n\n"
                    "Example shape only (vary font_weight to fit THIS image; do not copy blindly):\n"
                    "{'lines': ['Line 1', 'Line 2'], 'x': 0.5, 'y': 0.88, 'font_size': 70, "
                    "'font_weight': 'medium', 'text_width': 'normal'}\n\n"
                )
            else:
                prompt_text = (
                    "You are a creative design assistant. Analyze the given image and propose "
                    "ONE best way to place the text.\n\n"
                    f"Image dimensions: width {img_width} px × height {img_height} px.\n\n"
                    f"Text: '{text}'\n\n"
                    + sizing_context
                    + xy_instructions
                    + "Return exactly ONE JSON object with these keys only (do not include 'reason' or 'position'):\n"
                    "- lines: list of split lines for the text. Split ONLY by natural length or '\\n' if "
                    "provided — DO NOT change, reword, or add punctuation to the text.\n"
                    "- x and y as defined above.\n"
                    f"- font_size: integer, scaled appropriately for this {img_width}×{img_height} px image.\n"
                    "- font_weight: exactly one of ['light', 'medium', 'bold', 'extra_bold'] — base this on visible typography and contrast in the image and the suggested weight above.\n"
                    "- colors: array of 6-digit hex strings for text (most important first), e.g. ['#FFFFFF', '#E0E0E0'].\n"
                    "- text_width: one of ['narrow', 'normal', 'wide', 'extra_wide'].\n"
                    "- font_family: one font name string (best match for the image).\n\n"
                    "Example shape only (vary font_weight for THIS image):\n"
                    "{'lines': ['Line 1', 'Line 2'], 'x': 0.5, 'y': 0.88, 'font_size': 70, "
                    "'font_weight': 'medium', 'colors': ['#FFFFFF'], 'text_width': 'normal', "
                    "'font_family': 'Inter'}\n\n"
                )

            if verbose:
                print("\n🧠 Sending image + text to GPT-4o-mini... please wait\n")

            try:
                # Encode image for OpenAI
                encoded_image = base64.b64encode(image_bytes).decode("utf-8")
                
                # Use OpenAI client with vision API
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt_text},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{encoded_image}"
                                    }
                                }
                            ]
                        }
                    ],
                    max_tokens=900,
                    temperature=0.45,
                )
                
                content = response.choices[0].message.content
                
            except Exception as e:
                if verbose:
                    print(f"❌ GPT API request failed: {e}\n")
                content = None

        # --- Handle AI response or fallback ---
        if not content:
            if verbose:
                print("⚠️ Using intelligent local fallback based on image analysis...\n")
            
            # Smart text splitting
            words = text.split()
            if len(words) > 10:
                # Split into 2-3 lines
                third = len(words) // 3
                lines = [
                    ' '.join(words[:third*2]),
                    ' '.join(words[third*2:])
                ]
            elif len(words) > 5:
                mid = len(words) // 2
                lines = [' '.join(words[:mid]), ' '.join(words[mid:])]
            else:
                lines = [text]
            
            # Use image-based sizing
            if image_info:
                font_size = image_info['base_font_size']
            else:
                font_size = 32
            
            if brand_context and isinstance(brand_context, dict):
                one = _strip_reason_field({
                    "lines": lines,
                    "font_size": font_size,
                    "font_weight": default_weight,
                    "text_width": "normal",
                })
            else:
                one = _strip_reason_field({
                    "lines": lines,
                    "font_size": font_size,
                    "font_weight": default_weight,
                    "colors": ["#ffffff"],
                    "text_width": "normal",
                    "font_family": None,
                })
            json_data = [one]
        else:
            try:
                json_text = re.search(r'\[.*\]|\{.*\}', content, re.S).group(0)
                parsed = json.loads(json_text)
                if isinstance(parsed, dict):
                    parsed = [_strip_reason_field(parsed)]
                elif isinstance(parsed, list):
                    first = next((x for x in parsed if isinstance(x, dict)), None)
                    parsed = [_strip_reason_field(first)] if first else []
                else:
                    parsed = []
                json_data = parsed[:1]
                if not json_data:
                    raise ValueError("empty suggestion")
            except Exception as e:
                if verbose:
                    print(f"⚠️ Failed to parse AI response: {e}\n")
                
                words = text.split()
                if len(words) > 8:
                    mid = len(words) // 2
                    lines = [' '.join(words[:mid]), ' '.join(words[mid:])]
                else:
                    lines = [text]
                
                font_size = image_info['base_font_size'] if image_info else 32
                
                if brand_context and isinstance(brand_context, dict):
                    json_data = [_strip_reason_field({
                        "lines": lines,
                        "font_size": font_size,
                        "font_weight": default_weight,
                        "text_width": "normal",
                    })]
                else:
                    json_data = [_strip_reason_field({
                        "lines": lines,
                        "font_size": font_size,
                        "font_weight": default_weight,
                        "colors": ["#ffffff"],
                        "text_width": "normal",
                        "font_family": None,
                    })]

        weight_hint_norm = (image_info or {}).get("typographic_weight_hint") or "medium"
        if json_data:
            for item in json_data:
                if isinstance(item, dict):
                    item["font_weight"] = _normalize_font_weight_value(
                        item.get("font_weight"), weight_hint_norm
                    )

        # Server-side scraped colors/fonts (never AI) when brand_context exists
        if json_data and brand_context and isinstance(brand_context, dict):
            json_data = [apply_scraped_brand_to_suggestion(s, brand_context) for s in json_data]

        if json_data and image_info:
            json_data = [finalize_suggestion_coordinates(s, image_info) for s in json_data]

        json_data = [strip_google_font_id_fields(s) for s in json_data]
        json_data = [ensure_colors_array_only(s) for s in json_data]

        if verbose:
            print("\n✅ Suggestions generated successfully!")

        # Return the result
        return {
            'success': True,
            'suggestions': json_data,
            'image_info': image_info,
        }
    
    except Exception as e:
        error_msg = f"Error generating suggestions: {str(e)}"
        if verbose:
            print(f"❌ {error_msg}")
        return {
            'success': False,
            'error': error_msg,
            'suggestions': [],
            'image_info': None,
        }





