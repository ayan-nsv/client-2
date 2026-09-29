# Placeholder file - Copy your holdflight/src/image/text_placement.py content here
# Text overlay on images



from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageStat, ImageColor
import re
import requests
from io import BytesIO
import os
import uuid
from datetime import datetime
from typing import List, Optional, Tuple, Union
from holdflight.src.utils.chrome_options import safe_get

_RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS


def load_image(source: str) -> Image.Image:
    """Load image from URL or local path."""
    try:
        if source.startswith(("http://", "https://")):
            response = safe_get(requests, source, timeout=10)
            response.raise_for_status()
            img = Image.open(BytesIO(response.content))
        else:
            img = Image.open(source)
        return img.convert("RGBA")
    except Exception as e:
        raise Exception(f"Error loading image: {e}")


def parse_color(color_str: str) -> tuple:
    """Parse color input (name, hex, or RGB string) into an RGB tuple."""
    if not color_str:
        return (255, 255, 255)  # Default to white
    
    color_str = color_str.strip().lower()
    
    # Handle RGB format: "255,0,0" or "255, 0, 0"
    if "," in color_str:
        try:
            parts = [int(x.strip()) for x in color_str.split(",")]
            if len(parts) == 3:
                return tuple(parts)
        except (ValueError, AttributeError):
            pass
    
    # Handle hex format: "#FF0000" or "FF0000"
    if color_str.startswith("#"):
        try:
            return ImageColor.getrgb(color_str)
        except:
            pass
    elif len(color_str) == 6 and all(c in '0123456789abcdefABCDEF' for c in color_str):
        try:
            return ImageColor.getrgb(f"#{color_str}")
        except:
            pass
    
    # Common color variations mapping
    color_variations = {
        # Dark variations
        "dark blue": (0, 0, 139),  # DarkBlue
        "darkblue": (0, 0, 139),
        "navy": (0, 0, 128),  # Navy
        "navy blue": (0, 0, 128),
        "navyblue": (0, 0, 128),
        "dark red": (139, 0, 0),  # DarkRed
        "darkred": (139, 0, 0),
        "dark green": (0, 100, 0),  # DarkGreen
        "darkgreen": (0, 100, 0),
        "dark gray": (169, 169, 169),  # DarkGray
        "darkgray": (169, 169, 169),
        "dark grey": (169, 169, 169),
        "darkgrey": (169, 169, 169),
        "dark purple": (128, 0, 128),  # Purple
        "darkpurple": (128, 0, 128),
        
        # Light variations
        "light blue": (173, 216, 230),  # LightBlue
        "lightblue": (173, 216, 230),
        "light red": (255, 182, 193),  # LightPink (closest to light red)
        "lightred": (255, 182, 193),
        "light green": (144, 238, 144),  # LightGreen
        "lightgreen": (144, 238, 144),
        "light gray": (211, 211, 211),  # LightGray
        "lightgray": (211, 211, 211),
        "light grey": (211, 211, 211),
        "lightgrey": (211, 211, 211),
        "light yellow": (255, 255, 224),  # LightYellow
        "lightyellow": (255, 255, 224),
        
        # Other common variations
        "sky blue": (135, 206, 235),  # SkyBlue
        "skyblue": (135, 206, 235),
        "royal blue": (65, 105, 225),  # RoyalBlue
        "royalblue": (65, 105, 225),
        "cornflower blue": (100, 149, 237),  # CornflowerBlue
        "cornflowerblue": (100, 149, 237),
        "steel blue": (70, 130, 180),  # SteelBlue
        "steelblue": (70, 130, 180),
        "midnight blue": (25, 25, 112),  # MidnightBlue
        "midnightblue": (25, 25, 112),
    }
    
    # Check if it's a known variation
    if color_str in color_variations:
        return color_variations[color_str]
    
    # Try to parse as standard color name (handles "blue", "red", "white", etc.)
    try:
        return ImageColor.getrgb(color_str)
    except:
        # If still not recognized, try to intelligently parse compound names
        # Split by space and try to find base color
        words = color_str.split()
        if len(words) >= 2:
            # Try to find base color (last word is usually the color)
            base_color = words[-1]
            modifier = " ".join(words[:-1]).lower()
            
            try:
                base_rgb = ImageColor.getrgb(base_color)
                # Apply modifier
                if "dark" in modifier:
                    # Darken the color by reducing brightness
                    return tuple(max(0, int(c * 0.5)) for c in base_rgb)
                elif "light" in modifier:
                    # Lighten the color by increasing brightness
                    return tuple(min(255, int(c + (255 - c) * 0.5)) for c in base_rgb)
                else:
                    # Just return base color if modifier not recognized
                    return base_rgb
            except:
                pass
        
        # Final fallback: try to return a reasonable default based on the string
        print(f"⚠️ Color '{color_str}' not recognized, defaulting to white")
        return (255, 255, 255)  # Default to white


def _system_font_directories() -> List[str]:
    """Common OS font roots (absolute paths that exist)."""
    candidates: List[str] = []
    if os.name == "nt":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        candidates.append(os.path.join(windir, "Fonts"))
    candidates.extend(
        [
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/truetype/liberation",
            "/usr/share/fonts",
            "/System/Library/Fonts",
            "/Library/Fonts",
        ]
    )
    out: List[str] = []
    seen = set()
    for d in candidates:
        if not d or d in seen:
            continue
        seen.add(d)
        if os.path.isdir(d):
            out.append(d)
    return out


def _font_filename_regularish(fn_lower: str) -> bool:
    return (
        "regular" in fn_lower
        or ("roman" in fn_lower and "times" not in fn_lower[:12])
        or fn_lower.endswith(("-r.ttf", "-r.otf", "_r.otf"))
        or "-regular." in fn_lower
    )


def _parse_font_family_label(raw_label: str) -> Tuple[str, Optional[bool]]:
    """
    Normalize labels like ``proxima-nova``, ``Helvetica-bold``, ``InterstateBold``
    into a compact family slug for file matching plus optional bold preference.

    Returns:
        ``(main_slug, want_bold)`` — ``want_bold`` is True/False if the name implies weight;
        ``None`` means no strong preference (pick best regular-ish match).
    """
    raw = str(raw_label).strip().strip('"').strip("'")
    # Split CamelCase: "InterstateBold" -> "Interstate Bold"
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    tokens = [t for t in re.split(r"[\s_\-,.]+", spaced.strip()) if t]
    bold_tokens = frozenset(
        {"bold", "bd", "bld", "black", "blk", "heavy", "heavyface", "strong"}
    )

    wants_bold: Optional[bool] = None
    kept: List[str] = []
    for t in tokens:
        tl = t.lower()
        if tl in bold_tokens:
            wants_bold = True
            continue
        if tl in ("regular", "normal", "roman", "book"):
            wants_bold = False
            continue
        kept.append(t)

    main_slug = re.sub(r"[^a-z0-9]+", "", "".join(kept).lower())
    return main_slug, wants_bold


def resolve_font_family_to_path(
    font_family: Optional[str],
    *,
    font_weight_hint: Optional[str] = None,
) -> Optional[str]:
    """
    Map a font family label (e.g. ``proxima-nova``, ``Helvetica-bold``, ``InterstateBold``)
    or a path ending in ``.ttf``/``.otf``/``.ttc`` to a loadable file path.
    """
    if not font_family or not str(font_family).strip():
        return None
    raw = str(font_family).strip().strip('"').strip("'")
    low = raw.lower()
    if low.endswith((".ttf", ".otf", ".ttc")) and os.path.isfile(raw):
        return raw

    main_slug, name_wants_bold = _parse_font_family_label(raw)

    wl = (font_weight_hint or "").strip().lower()
    weight_bold_pref: Optional[bool] = None
    if wl in ("bold", "700", "800", "900", "extra_bold", "extrabold", "black", "heavy"):
        weight_bold_pref = True
    elif wl in ("normal", "400", "regular", "roman", "light", "300", "200", "100", "medium", "500"):
        weight_bold_pref = False

    if name_wants_bold is True or weight_bold_pref is True:
        want_bold = True
    elif name_wants_bold is False or weight_bold_pref is False:
        want_bold = False
    else:
        want_bold = None

    alt_slugs: List[str] = []
    if main_slug:
        alt_slugs.append(main_slug)

    spaced = " ".join(
        [p for p in re.split(r"[\s_\-,.]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw)) if p]
    ).lower()

    words = [
        re.sub(r"[^a-z0-9]+", "", w)
        for w in spaced.split()
        if re.sub(r"[^a-z0-9]+", "", w).lower()
        not in frozenset(
            {"bold", "regular", "normal", "light", "medium", "black", "heavy", "italic", "roman"}
        )
    ]
    if words:
        combined = "".join(words)
        if combined != main_slug and len(combined) >= 4:
            alt_slugs.append(combined)

    seen_slug: set[str] = set()
    unique_slugs: List[str] = []
    for s in alt_slugs:
        if not s or len(s) < 2 or s in seen_slug:
            continue
        seen_slug.add(s)
        unique_slugs.append(s)

    if not unique_slugs:
        return None

    exts = (".ttf", ".otf", ".ttc")
    scored: List[tuple[int, str]] = []

    for font_dir in _system_font_directories():
        try:
            names = os.listdir(font_dir)
        except OSError:
            continue
        for fname in names:
            if not fname.lower().endswith(exts):
                continue
            path = os.path.join(font_dir, fname)
            if not os.path.isfile(path):
                continue
            stem = re.sub(r"[^a-z0-9]+", "", os.path.splitext(fname)[0].lower())
            if not stem:
                continue

            fn = fname.lower()

            boldish = (
                ("bold" in fn)
                or ("black" in fn)
                or ("heavy" in fn)
                or (" bd" in fn)
                or ("-bd." in fn)
                or ("bd." in fn)
                or ("bld" in fn)
            )
            italicish = "italic" in fn or "it." in fn or "_it" in fn
            regulish = _font_filename_regularish(fn) or ("light" in fn and not boldish)

            weight_adj = 0
            if want_bold is True:
                if boldish and not italicish:
                    weight_adj += 42
                elif boldish:
                    weight_adj += 28
                elif regulish:
                    weight_adj -= 22
                else:
                    weight_adj -= 5
                if italicish and not boldish:
                    weight_adj -= 8
            elif want_bold is False:
                if boldish:
                    weight_adj -= 35
                if regulish or ("light" in fn):
                    weight_adj += 18
                if not boldish and not italicish:
                    weight_adj += 6
                if italicish:
                    weight_adj -= 6
            else:
                if boldish:
                    weight_adj -= 6
                if regulish:
                    weight_adj += 5

            best_slug_score = 0
            for slug in unique_slugs:
                if stem == slug:
                    sc = 100 + len(slug)
                elif stem.startswith(slug) and len(slug) >= 3:
                    sc = 60 + len(slug)
                elif slug in stem and len(slug) >= 4:
                    sc = 35 + min(len(slug), len(stem) // 3)
                else:
                    continue
                best_slug_score = max(best_slug_score, sc)

            if best_slug_score <= 0:
                continue
            scored.append((best_slug_score + weight_adj, path))

    if not scored:
        return None

    scored.sort(key=lambda t: -t[0])
    chosen = scored[0][1]
    print(f"   Resolved '{raw}' → {os.path.basename(chosen)} (bold_pref={want_bold})")
    return chosen


def _measure_font_render_height(font: ImageFont.FreeTypeFont) -> int:
    """Estimate visible glyph height in pixels for calibration."""
    try:
        bbox = font.getbbox("Hg")
        if bbox:
            h = int(bbox[3] - bbox[1])
            if h > 0:
                return h
    except Exception:
        pass
    try:
        asc, desc = font.getmetrics()
        h = int(asc + desc)
        if h > 0:
            return h
    except Exception:
        pass
    return max(1, int(getattr(font, "size", 1)))


def _load_truetype_exact_px(font_path: str, target_px: int) -> ImageFont.FreeTypeFont:
    """
    Load a TrueType/OpenType font and calibrate so rendered height ~= target_px.
    Pillow's raw font size maps to EM-size and can differ by family.
    """
    target = max(1, int(target_px))
    font = ImageFont.truetype(font_path, target)
    measured = _measure_font_render_height(font)
    if measured <= 0 or measured == target:
        return font

    # First-pass correction from measured glyph height.
    corrected = max(1, int(round(target * (target / measured))))
    if corrected != target:
        font = ImageFont.truetype(font_path, corrected)
        measured2 = _measure_font_render_height(font)
        if measured2 > 0 and measured2 != target:
            # One extra refinement pass is enough and keeps this cheap.
            corrected2 = max(1, int(round(corrected * (target / measured2))))
            if corrected2 != corrected:
                font = ImageFont.truetype(font_path, corrected2)
    return font


def get_font(
    size: int,
    font_family: Optional[str] = None,
    font_weight_hint: Optional[str] = None,
) -> ImageFont.FreeTypeFont:
    """Load a font at ``size``; prefer ``font_family`` when resolvable, else system fallbacks."""
    font_paths: List[str] = []
    resolved = resolve_font_family_to_path(
        font_family, font_weight_hint=font_weight_hint
    )
    if resolved:
        font_paths.append(resolved)

    # Pillow-bundled scalable fallback (works even when system fonts are sparse).
    try:
        pil_fonts_dir = os.path.join(os.path.dirname(ImageFont.__file__), "fonts")
        font_paths.append(os.path.join(pil_fonts_dir, "DejaVuSans.ttf"))
    except Exception:
        pass

    # Windows defaults
    if os.name == "nt":
        windows_font_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        font_paths.extend(
            [
                os.path.join(windows_font_dir, "arial.ttf"),
                os.path.join(windows_font_dir, "Arial.ttf"),
                os.path.join(windows_font_dir, "calibri.ttf"),
                os.path.join(windows_font_dir, "Calibri.ttf"),
            ]
        )

    font_paths.extend(
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial.ttf",
            "arial.ttf",
            "Arial.ttf",
        ]
    )

    # Try to load font with the specified size
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                font = _load_truetype_exact_px(font_path, size)
                print(f"✅ Loaded font: {font_path} at size {size}px")
                return font
            except Exception as e:
                # Continue to next font if this one fails
                print(f"⚠️ Failed to load {font_path} at size {size}px: {e}")
                continue
    
    # Last resort: try to find ANY font file and use it
    print(f"⚠️ No standard fonts found. Attempting to find any available font...")
    try:
        if os.name == 'nt':
            # On Windows, try to list fonts directory
            windows_font_dir = "C:/Windows/Fonts"
            if os.path.exists(windows_font_dir):
                for font_file in os.listdir(windows_font_dir):
                    if font_file.lower().endswith(('.ttf', '.ttc', '.otf')):
                        font_path = os.path.join(windows_font_dir, font_file)
                        try:
                            font = _load_truetype_exact_px(font_path, size)
                            print(f"✅ Loaded fallback font: {font_path} at size {size}px")
                            return font
                        except:
                            continue
    except Exception as e:
        print(f"⚠️ Error searching for fonts: {e}")
    
    # Final fallback - but warn that size won't be accurate
    print(f"❌ WARNING: Using default font (size will NOT be accurate). Requested size: {size}px")
    print(f"   The default font has a fixed size and cannot be scaled.")
    print(f"   Please ensure system fonts are available for proper font sizing.")
    return ImageFont.load_default()


def parse_font_weight(weight_input: str) -> int:
    """Convert CSS-style font weight (100–900 or name) into stroke width multiplier."""
    weight_input = weight_input.strip().lower()
    
    weight_map = {
        "100": 0, "200": 0,
        "300": 0, "light": 0,
        "400": 0, "normal": 0,
        "500": 1, "medium": 1,
        "600": 2, "semibold": 2,
        "700": 3, "bold": 3,
        "800": 4,
        "900": 5, "extra_bold": 5, "extrabold": 5, "black": 5,
    }
    
    return weight_map.get(weight_input, 0)


def wrap_text(text, font, draw, max_width):
    """Wrap text into multiple lines if it's too wide."""
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current_line.append(word)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
    return "\n".join(lines)


def get_text_dimensions(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    spacing: float,
    align: str,
) -> tuple:
    """Get accurate multiline text bounds with the same draw settings used for rendering."""
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align=align)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    offset_x = bbox[0]
    offset_y = bbox[1]
    return width, height, offset_x, offset_y


def _coord_to_pixel_anchor(coord: float, size: int) -> float:
    """
    Accept normalized [0..1] or absolute pixel coordinates.
    - 0..1 => normalized fraction of (size - 1)
    - otherwise => treat as pixels directly
    """
    span = max(1, int(size)) - 1
    v = float(coord)
    if 0.0 <= v <= 1.0:
        return v * span
    return max(0.0, min(float(span), v))


def _clamp_draw_point_to_image(
    draw_x: int,
    draw_y: int,
    text_w: int,
    text_h: int,
    offset_x: int,
    offset_y: int,
    image_w: int,
    image_h: int,
) -> tuple[int, int]:
    """Clamp draw origin using true bbox extents (offset-aware)."""
    left = draw_x + offset_x
    top = draw_y + offset_y
    right = left + text_w
    bottom = top + text_h

    if left < 0:
        draw_x += -left
        right += -left
        left = 0
    if right > image_w:
        shift = right - image_w
        draw_x -= shift
        left -= shift
        right = image_w

    if top < 0:
        draw_y += -top
        bottom += -top
        top = 0
    if bottom > image_h:
        shift = bottom - image_h
        draw_y -= shift
        top -= shift
        bottom = image_h

    return int(draw_x), int(draw_y)


def composite_logo_on_image(
    base_rgba: Image.Image,
    logo_url: str,
    anchor_x: float,
    anchor_y: float,
    max_width_ratio: float = 0.18,
) -> Image.Image:
    """
    Paste a logo onto ``base_rgba`` centered at normalized (or pixel) ``anchor_x``/``anchor_y``,
    same convention as ``place_text_on_image``. Logo is scaled so its width ≤ canvas width × ``max_width_ratio``.
    """
    logo = load_image(logo_url)
    ratio = float(max_width_ratio or 0.18)
    ratio = max(0.02, min(0.5, ratio))
    mw = max(10, min(int(base_rgba.width * ratio), base_rgba.width))
    lw, lh = logo.size
    scale = mw / float(max(lw, 1))
    nw = max(1, int(round(lw * scale)))
    nh = max(1, int(round(lh * scale)))
    if nw > base_rgba.width:
        scale = base_rgba.width / float(max(lw, 1))
        nw = base_rgba.width
        nh = max(1, int(round(lh * scale)))
    if nh > base_rgba.height:
        s2 = base_rgba.height / float(nh)
        nw = max(1, int(round(nw * s2)))
        nh = base_rgba.height
    logo = logo.resize((nw, nh), _RESAMPLE)

    cx = _coord_to_pixel_anchor(float(anchor_x), base_rgba.width)
    cy = _coord_to_pixel_anchor(float(anchor_y), base_rgba.height)
    lx0 = int(round(cx - nw / 2))
    ly0 = int(round(cy - nh / 2))
    lx0 = max(0, min(base_rgba.width - nw, lx0))
    ly0 = max(0, min(base_rgba.height - nh, ly0))

    if logo.mode != "RGBA":
        logo = logo.convert("RGBA")

    layer = Image.new("RGBA", base_rgba.size, (0, 0, 0, 0))
    layer.paste(logo, (lx0, ly0), logo)
    return Image.alpha_composite(base_rgba, layer)


def calculate_text_position(image: Image.Image, text_w: int, text_h: int, position: str, margin_ratio: float = 0.05) -> tuple:
    """Determine pixel-perfect placement with correct alignment."""
    margin = int(min(image.width, image.height) * margin_ratio)
    pos = position.replace("-", "").replace("_", "").replace(" ", "").lower()
    
    if pos == "topleft":
        return (margin, margin)
    elif pos == "topright":
        return (image.width - text_w - margin, margin)
    elif pos == "topcenter":
        return ((image.width - text_w) // 2, margin)
    elif pos == "bottomleft":
        return (margin, image.height - text_h - margin)
    elif pos == "bottomright":
        return (image.width - text_w - margin, image.height - text_h - margin)
    elif pos == "bottomcenter":
        return ((image.width - text_w) // 2, image.height - text_h - margin)
    elif pos == "center":
        return ((image.width - text_w) // 2, (image.height - text_h) // 2)
    else:
        # Auto brightness-based detection
        gray = image.convert("L")
        top_crop = gray.crop((0, 0, image.width, image.height // 3))
        bottom_crop = gray.crop((0, 2 * image.height // 3, image.width, image.height))
        if ImageStat.Stat(top_crop).mean[0] > ImageStat.Stat(bottom_crop).mean[0]:
            return ((image.width - text_w) // 2, image.height - text_h - margin)
        else:
            return ((image.width - text_w) // 2, margin)


def place_text_on_image(
    image_url: str,
    text: Optional[Union[str, List[str]]] = None,
    position: str = "auto",
    font_size: int = None,
    font_weight: str = "normal",
    text_color: str = "white",
    output_dir: str = ".",
    anchor_x: Optional[float] = None,
    anchor_y: Optional[float] = None,
    font_family: Optional[str] = None,
    logo_url: Optional[str] = None,
    logo_anchor_x: Optional[float] = None,
    logo_anchor_y: Optional[float] = None,
    logo_max_width_ratio: float = 0.18,
) -> dict:
    """
    Place optional text overlay and/or a logo on an image and save the result.
    
    Text anchor and logo anchor both use normalized [0..1] or pixel coordinates via
    ``_coord_to_pixel_anchor``: position is the **visual center** of the text bbox or logo.
    
    Provide at least one of non-empty ``text`` (with anchors) or ``logo_url`` (with logo anchors).
    
    Args:
        image_url: Public URL or local path to the image
        text: Optional text overlay (multiline \\n or list of lines)
        position: Used when anchors are omitted (see existing presets)
        font_size, font_weight, text_color, font_family: Text styling
        output_dir: Output directory for the JPEG
        anchor_x / anchor_y: Text center anchors when placing text
        logo_url / logo_anchor_x / logo_anchor_y / logo_max_width_ratio: Logo overlay (same anchor semantics)

    Returns:
        Dictionary with 'success', 'output_path', 'output_url', and optionally 'error'
    """
    try:
        if isinstance(text, list):
            final_text = "\n".join(str(line) for line in text if line is not None)
        elif text is not None:
            final_text = str(text)
        else:
            final_text = ""

        has_text_content = bool(final_text.strip())

        has_logo = bool(
            logo_url
            and str(logo_url).strip()
            and logo_anchor_x is not None
            and logo_anchor_y is not None
        )

        if not has_text_content and not has_logo:
            return {
                "success": False,
                "error": "Provide non-empty text (with x,y) and/or logo_url with logo_x, logo_y",
            }
        
        # Load base canvas
        image = load_image(image_url)

        if has_text_content:
            # Font size auto-scaling
            if font_size is None or font_size <= 0:
                base_size = int(image.height * 0.07)
                total_chars = sum(len(line) for line in final_text.splitlines())
                length_factor = max(0.5, 1.0 - (total_chars / 80))
                font_size = int(base_size * length_factor)
                font_size = max(20, min(font_size, 150))
            else:
                if font_size > 2000:
                    print(
                        "⚠️ Font size {} is very large, capping to 2000px to prevent issues".format(
                            font_size
                        )
                    )
                    font_size = 2000

            print(f"📝 Using font size: {font_size}px")
            if font_family:
                print(f"📝 Font family request: {font_family}")
            font = get_font(
                font_size,
                font_family=font_family,
                font_weight_hint=font_weight,
            )
            text_color_rgb = parse_color(text_color)
            stroke = parse_font_weight(font_weight)

            draw_temp = ImageDraw.Draw(Image.new("RGBA", image.size))
            if font_size > 200:
                max_text_width = int(image.width * 0.95)
            else:
                max_text_width = int(image.width * 0.8)
            wrapped_lines = [
                wrap_text(line, font, draw_temp, max_text_width)
                for line in final_text.splitlines()
            ]
            wrapped_final = "\n".join(wrapped_lines)

            text_align = "center"
            line_spacing = font_size * 0.4

            text_w, text_h, offset_x, offset_y = get_text_dimensions(
                draw_temp,
                wrapped_final,
                font,
                spacing=line_spacing,
                align=text_align,
            )

            use_anchor = anchor_x is not None and anchor_y is not None
            if use_anchor:
                try:
                    cx = _coord_to_pixel_anchor(float(anchor_x), image.width)
                    cy = _coord_to_pixel_anchor(float(anchor_y), image.height)
                except (TypeError, ValueError):
                    cx = _coord_to_pixel_anchor(0.5, image.width)
                    cy = _coord_to_pixel_anchor(0.85, image.height)
                x = int(round(cx - text_w / 2)) - offset_x
                y = int(round(cy - text_h / 2)) - offset_y
            else:
                x, y = calculate_text_position(image, text_w, text_h, position)
                x -= offset_x
                y -= offset_y

            x, y = _clamp_draw_point_to_image(
                x,
                y,
                text_w,
                text_h,
                offset_x,
                offset_y,
                image.width,
                image.height,
            )

            txt_layer = Image.new("RGBA", image.size, (255, 255, 255, 0))
            draw_txt = ImageDraw.Draw(txt_layer)
            text_opacity = 240

            draw_txt.multiline_text(
                (x, y),
                wrapped_final,
                font=font,
                fill=text_color_rgb + (text_opacity,),
                spacing=line_spacing,
                align=text_align,
                stroke_width=stroke,
                stroke_fill=text_color_rgb + (text_opacity,),
            )

            final_img = Image.alpha_composite(image, txt_layer)
        else:
            final_img = image

        if has_logo:
            final_img = composite_logo_on_image(
                final_img,
                str(logo_url).strip(),
                float(logo_anchor_x),
                float(logo_anchor_y),
                float(logo_max_width_ratio or 0.18),
            )

        final_img = ImageEnhance.Contrast(final_img).enhance(1.05)
        final_img = ImageEnhance.Brightness(final_img).enhance(1.03)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        if has_text_content and has_logo:
            stem = "overlay"
        elif has_logo:
            stem = "logo_overlay"
        else:
            stem = "text_overlay"
        filename = f"{stem}_{timestamp}_{unique_id}.jpg"
        output_path = os.path.join(output_dir, filename)
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Save image
        final_img.convert("RGB").save(output_path, "JPEG", quality=95)

        return {
            'success': True,
            'output_path': output_path,
            'filename': filename,
            'output_url': f'/images/{filename}',
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


