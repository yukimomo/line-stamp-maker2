"""
Japanese-safe text rendering for LINE stamps.

Font search order:
  1. Yu Gothic Medium / Meiryo (Windows system fonts)
  2. LSM bundled kiwi.ttf / maru.ttf (Kiwi Maru – Japanese)
  3. Pillow default (last resort, no Japanese)
"""

from __future__ import annotations
import math
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Font discovery
# ---------------------------------------------------------------------------

_FONT_SEARCH_ORDER: list[Path] = [
    # Windows – Japanese system fonts
    Path(r"C:\Windows\Fonts\yugothm.ttc"),   # Yu Gothic Medium (best)
    Path(r"C:\Windows\Fonts\YuGothM.ttc"),
    Path(r"C:\Windows\Fonts\meiryo.ttc"),
    Path(r"C:\Windows\Fonts\msgothic.ttc"),
    # LSM bundled – Kiwi Maru (Japanese round font)
    Path(__file__).parents[3] / "line-stamp-maker/line_stamp_maker/assets/fonts/kiwi.ttf",
    Path(__file__).parents[3] / "line-stamp-maker/line_stamp_maker/assets/fonts/maru.ttf",
    Path(__file__).parents[3] / "line-stamp-maker/line_stamp_maker/assets/fonts/noto-sans-jp.ttf",
    # macOS
    Path("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"),
    # Linux / Noto
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
]

_font_path_cache: Optional[Path] = None
_font_path_resolved: bool = False


def find_japanese_font() -> Optional[Path]:
    """Return path of the first available Japanese-capable font."""
    global _font_path_cache, _font_path_resolved
    if _font_path_resolved:
        return _font_path_cache
    _font_path_resolved = True
    for p in _FONT_SEARCH_ORDER:
        if p.exists():
            _font_path_cache = p
            return p
    return None


_size_cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}

# Selectable font families (label shown in the UI). Each maps to candidate
# file paths; the first that exists is used. "auto" = default search order.
_LSM_FONTS = Path(__file__).parents[3] / "line-stamp-maker/line_stamp_maker/assets/fonts"
FONT_CHOICES: dict[str, str] = {
    "auto":   "標準（自動）",
    "gothic": "ゴシック",
    "maru":   "丸ゴシック",
    "mincho": "明朝",
    "pop":    "ポップ体",
}
_FONT_FILES: dict[str, list[Path]] = {
    "gothic": [Path(r"C:\Windows\Fonts\yugothm.ttc"), Path(r"C:\Windows\Fonts\meiryo.ttc"),
               Path(r"C:\Windows\Fonts\msgothic.ttc")],
    "maru":   [_LSM_FONTS / "kiwi.ttf", _LSM_FONTS / "maru.ttf",
               Path(r"C:\Windows\Fonts\msgothic.ttc")],
    "mincho": [Path(r"C:\Windows\Fonts\yumin.ttc"), Path(r"C:\Windows\Fonts\msmincho.ttc"),
               Path(r"C:\Windows\Fonts\HGRME.TTC")],
    "pop":    [_LSM_FONTS / "kiwi.ttf", Path(r"C:\Windows\Fonts\HGRPP1.TTC")],
}

_named_cache: dict[tuple[str, int], object] = {}


def _resolve_family_path(family: str) -> Optional[Path]:
    for p in _FONT_FILES.get(family, []):
        if p.exists():
            return p
    return None


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load the default Japanese-capable font at *size* (cached)."""
    if size in _size_cache:
        return _size_cache[size]
    path = find_japanese_font()
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    if path:
        try:
            font = ImageFont.truetype(str(path), size)
            _size_cache[size] = font
            return font
        except Exception:
            pass
    font = ImageFont.load_default()
    return font


def load_named_font(family: str, size: int):
    """Load a named font family at *size*, falling back to the default font."""
    if not family or family == "auto":
        return load_font(size)
    key = (family, size)
    if key in _named_cache:
        return _named_cache[key]
    path = _resolve_family_path(family)
    if path:
        try:
            f = ImageFont.truetype(str(path), size)
            _named_cache[key] = f
            return f
        except Exception:
            pass
    return load_font(size)


def auto_font_size(
    text: str,
    max_width: int,
    base_size: int = 40,
    min_size: int = 18,
) -> int:
    """Binary-search the largest font size that fits *text* within *max_width*."""
    for size in range(base_size, min_size - 1, -2):
        font = load_font(size)
        dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        bbox = dummy_draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return size
    return min_size


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _draw_outlined_text(
    draw: ImageDraw.ImageDraw,
    pos: Tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: Tuple[int, int, int, int],
    stroke_fill: Tuple[int, int, int, int],
    stroke_width: int,
) -> None:
    x, y = pos
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx * dx + dy * dy <= stroke_width * stroke_width:
                draw.text((x + dx, y + dy), text, font=font, fill=stroke_fill)
    draw.text((x, y), text, font=font, fill=fill)


def _bottom_center_xy(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    img_w: int,
    img_h: int,
    margin_bottom: int = 16,
) -> Tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    return (img_w - tw) // 2, img_h - th - margin_bottom


def wrap_text(
    text: str,
    max_width: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_lines: int = 2,
) -> list[str]:
    """
    Split *text* into ≤ *max_lines* lines that each fit within *max_width* px.

    Works for both space-separated (Latin) and unseparated (Japanese) text.
    """
    if not text:
        return []
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def _width(t: str) -> int:
        b = dummy.textbbox((0, 0), t, font=font)
        return b[2] - b[0]

    if _width(text) <= max_width:
        return [text]

    # Try space-splitting first (Latin / mixed)
    if " " in text:
        words = text.split(" ")
        lines: list[str] = []
        cur = ""
        for word in words:
            trial = (cur + " " + word).strip()
            if _width(trial) <= max_width:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = word
                if len(lines) >= max_lines - 1:
                    break
        if cur:
            lines.append(cur)
        return lines[:max_lines]

    # Japanese: binary-search split point per line
    lines = []
    remaining = text
    while remaining and len(lines) < max_lines:
        lo, hi = 1, len(remaining)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _width(remaining[:mid]) <= max_width:
                lo = mid
            else:
                hi = mid - 1
        lines.append(remaining[:lo])
        remaining = remaining[lo:]
    if remaining:
        lines[-1] += "…"
    return lines


# ---------------------------------------------------------------------------
# Public text styles
# ---------------------------------------------------------------------------

TEXT_STYLES: dict[str, str] = {
    "bubble":        "吹き出し",
    "pop":           "ポップ（太フチ）",
    "shadow":        "ドロップシャドウ",
    "outline_white": "白フチ",
    "outline_black": "黒フチ（白縁）",
}


# Per-preset rendering defaults. Custom overrides are merged on top of these,
# so a stamp with no overrides renders exactly as before (back-compat).
_PRESET_DEFAULTS: dict[str, dict] = {
    "pop":           dict(bubble=False, text_color=(255, 255, 255), stroke_color=(0, 0, 0),
                          stroke_width=6, shadow=False),
    "shadow":        dict(bubble=False, text_color=(255, 255, 255), stroke_color=(0, 0, 0),
                          stroke_width=0, shadow=True, shadow_color=(0, 0, 0, 150),
                          shadow_dx=3, shadow_dy=3),
    "outline_white": dict(bubble=False, text_color=(255, 255, 255), stroke_color=(0, 0, 0),
                          stroke_width=5, shadow=False),
    "outline_black": dict(bubble=False, text_color=(20, 20, 20), stroke_color=(255, 255, 255),
                          stroke_width=5, shadow=False),
    "bubble":        dict(bubble=True, text_color=(15, 15, 15), stroke_color=(255, 255, 255),
                          stroke_width=2, shadow=False),
}


def add_caption(
    img: Image.Image,
    text: str,
    style: str = "bubble",
    overrides: dict | None = None,
) -> Image.Image:
    """
    Add *text* to *img* (RGBA). The look is determined by the *style* preset,
    optionally customized by *overrides* (text_color, stroke_color, stroke_width,
    shadow/shadow_color/shadow_dx/dy, font, font_size, text_pos, text_y, align).

    With no overrides the output is identical to the original presets.
    Returns a new RGBA image (same size).
    """
    if not text or not text.strip():
        return img

    cfg = dict(_PRESET_DEFAULTS.get(style, _PRESET_DEFAULTS["pop"]))
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})

    w, h = img.size
    max_w = w - 28

    # Font size: explicit override (>0) or auto-fit
    font_size = int(cfg.get("font_size") or 0)
    family = cfg.get("font", "auto")
    if font_size > 0:
        font = load_named_font(family, font_size)
    else:
        font_size = auto_font_size(text, max_w)
        font = load_named_font(family, font_size)
    lines = wrap_text(text, max_w, font, max_lines=2)

    if cfg.get("bubble"):
        return _render_bubble(img, lines, font, cfg)
    return _render_text(img, lines, font, cfg)


def _tup(c, default):
    """Coerce a color (list/tuple) to an int tuple, else default."""
    if c is None:
        return default
    try:
        return tuple(int(x) for x in c)
    except (TypeError, ValueError):
        return default


def _resolve_xy(cfg: dict, w: int, h: int, total_w: int, total_h: int,
                align: str) -> tuple[int, int]:
    """Compute the top-left anchor for a text block from position/align cfg."""
    # Horizontal by align
    if align == "left":
        x = 14
    elif align == "right":
        x = w - total_w - 14
    else:
        x = (w - total_w) // 2

    # Vertical by text_y (free 0..1) or text_pos preset
    text_y = cfg.get("text_y")
    if text_y is not None:
        y = int(float(text_y) * h) - total_h // 2
    else:
        pos = cfg.get("text_pos", "bottom")
        if pos == "top":
            y = 14
        elif pos == "center":
            y = (h - total_h) // 2
        else:
            y = h - total_h - 14
    y = max(2, min(y, h - total_h - 2))
    return x, y


def _render_text(img: Image.Image, lines: list[str], font, cfg: dict) -> Image.Image:
    """Unified free-text renderer (color / stroke / shadow / position / align)."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    lh = _line_height(draw, font)
    gap = 4
    total_h = lh * len(lines) + gap * (len(lines) - 1)
    line_widths = [draw.textbbox((0, 0), ln, font=font)[2] - draw.textbbox((0, 0), ln, font=font)[0]
                   for ln in lines]
    total_w = max(line_widths) if line_widths else 0
    align = cfg.get("align", "center")

    bx, by = _resolve_xy(cfg, w, h, total_w, total_h, align)

    fill = (*_tup(cfg.get("text_color"), (255, 255, 255)), 255)
    stroke = (*_tup(cfg.get("stroke_color"), (0, 0, 0)), 255)
    sw = int(cfg.get("stroke_width", 0) or 0)
    use_shadow = bool(cfg.get("shadow"))
    sh_color = cfg.get("shadow_color", (0, 0, 0, 150))
    if len(_tup(sh_color, (0, 0, 0))) == 3:
        sh_color = (*_tup(sh_color, (0, 0, 0)), 150)
    sdx = int(cfg.get("shadow_dx", 3))
    sdy = int(cfg.get("shadow_dy", 3))

    for i, line in enumerate(lines):
        tw = line_widths[i]
        if align == "center":
            x = bx + (total_w - tw) // 2
        elif align == "right":
            x = bx + (total_w - tw)
        else:
            x = bx
        y = by + i * (lh + gap)
        if use_shadow:
            draw.text((x + sdx, y + sdy), line, font=font, fill=tuple(sh_color))
        if sw > 0:
            _draw_outlined_text(draw, (x, y), line, font, fill=fill,
                                stroke_fill=stroke, stroke_width=sw)
        else:
            draw.text((x, y), line, font=font, fill=fill)
    return img


def _line_height(draw: ImageDraw.ImageDraw,
                 font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    b = draw.textbbox((0, 0), "あA", font=font)
    return b[3] - b[1]


def _draw_lines_bottom_center(
    img: Image.Image,
    lines: list[str],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    margin_bottom: int,
    draw_fn,  # callable(draw, x, y, line, font)
) -> None:
    """Render multi-line text, bottom-centered."""
    draw = ImageDraw.Draw(img)
    lh = _line_height(draw, font)
    gap = 4
    total_h = lh * len(lines) + gap * (len(lines) - 1)
    w, h = img.size
    y_start = h - total_h - margin_bottom
    for i, line in enumerate(lines):
        b = draw.textbbox((0, 0), line, font=font)
        tw = b[2] - b[0]
        x = (w - tw) // 2
        y = y_start + i * (lh + gap)
        draw_fn(draw, x, y, line, font)


def _render_bubble(img: Image.Image, lines: list[str], font, cfg: dict) -> Image.Image:
    """Speech-bubble renderer. Bubble fill = stroke_color, text = text_color."""
    w, h = img.size
    dummy_draw = ImageDraw.Draw(img)
    pad = 12
    tail = 13
    lh = _line_height(dummy_draw, font)
    gap = 3

    max_tw = max(dummy_draw.textbbox((0, 0), line, font=font)[2]
                 - dummy_draw.textbbox((0, 0), line, font=font)[0]
                 for line in lines)
    total_text_h = lh * len(lines) + gap * (len(lines) - 1)

    bw = max_tw + pad * 2
    bh = total_text_h + pad * 2
    bx = (w - bw) // 2

    # Vertical position respects text_pos / text_y (default: bottom)
    text_y = cfg.get("text_y")
    if text_y is not None:
        by = int(float(text_y) * h) - bh // 2
    else:
        pos = cfg.get("text_pos", "bottom")
        by = 14 + tail if pos == "top" else (h - bh) // 2 if pos == "center" else h - bh - 10
    by = max(tail + 2, min(by, h - bh - 2))

    bubble_fill = (*_tup(cfg.get("stroke_color"), (255, 255, 255)), 235)
    text_fill = (*_tup(cfg.get("text_color"), (15, 15, 15)), 255)
    line_col = (0, 0, 0, 255)

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    r = min(bh // 2, 14)
    ld.rounded_rectangle([bx, by, bx + bw, by + bh], radius=r,
                         fill=bubble_fill, outline=line_col, width=3)
    tcx = bx + bw // 2
    ld.polygon([(tcx - 9, by + 1), (tcx + 9, by + 1), (tcx, by - tail)], fill=bubble_fill)
    ld.line([(tcx - 9, by), (tcx, by - tail)], fill=line_col, width=3)
    ld.line([(tcx + 9, by), (tcx, by - tail)], fill=line_col, width=3)

    img = Image.alpha_composite(img, layer)
    draw2 = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        b = draw2.textbbox((0, 0), line, font=font)
        tw = b[2] - b[0]
        tx = bx + pad + (bw - pad * 2 - tw) // 2
        ty = by + pad + i * (lh + gap)
        _draw_outlined_text(draw2, (tx, ty), line, font, fill=text_fill,
                            stroke_fill=(255, 255, 255, 180),
                            stroke_width=int(cfg.get("stroke_width", 2)))
    return img
