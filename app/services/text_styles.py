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


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a Japanese-capable font at *size* (cached)."""
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


def add_caption(img: Image.Image, text: str, style: str = "bubble") -> Image.Image:
    """
    Add *text* to *img* (RGBA) using the requested text *style*.
    Supports 2-line wrap; long text is auto-shrunk to fit.
    Returns a new RGBA image (same size).
    """
    if not text or not text.strip():
        return img

    w, _ = img.size
    max_w = w - 28

    # Find the right font size (considering 2-line wrap)
    font_size = auto_font_size(text, max_w)
    font = load_font(font_size)
    lines = wrap_text(text, max_w, font, max_lines=2)

    dispatch = {
        "bubble":        _bubble,
        "pop":           _pop,
        "shadow":        _shadow,
        "outline_white": lambda i, ls, f: _simple_outline(i, ls, f,
                             fill=(255, 255, 255, 255), stroke=(0, 0, 0, 255), sw=5),
        "outline_black": lambda i, ls, f: _simple_outline(i, ls, f,
                             fill=(20, 20, 20, 255), stroke=(255, 255, 255, 255), sw=5),
    }
    fn = dispatch.get(style, _pop)
    return fn(img, lines, font)


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


def _pop(img: Image.Image, lines: list[str], font) -> Image.Image:
    def fn(draw, x, y, line, f):
        _draw_outlined_text(draw, (x, y), line, f,
                            fill=(255, 255, 255, 255),
                            stroke_fill=(0, 0, 0, 255),
                            stroke_width=6)
    _draw_lines_bottom_center(img, lines, font, 14, fn)
    return img


def _shadow(img: Image.Image, lines: list[str], font) -> Image.Image:
    def fn(draw, x, y, line, f):
        draw.text((x + 3, y + 3), line, font=f, fill=(0, 0, 0, 150))
        draw.text((x, y), line, font=f, fill=(255, 255, 255, 255))
    _draw_lines_bottom_center(img, lines, font, 14, fn)
    return img


def _simple_outline(img, lines, font, fill, stroke, sw) -> Image.Image:
    def fn(draw, x, y, line, f):
        _draw_outlined_text(draw, (x, y), line, f,
                            fill=fill, stroke_fill=stroke, stroke_width=sw)
    _draw_lines_bottom_center(img, lines, font, 14, fn)
    return img


def _bubble(img: Image.Image, lines: list[str], font) -> Image.Image:
    """Draw text (possibly 2 lines) inside a speech bubble at the bottom."""
    w, h = img.size
    dummy_draw = ImageDraw.Draw(img)
    pad = 12
    tail = 13
    lh = _line_height(dummy_draw, font)
    gap = 3

    # Bubble dimensions: wide enough for longest line, tall enough for all lines
    max_tw = max(dummy_draw.textbbox((0, 0), line, font=font)[2]
                 - dummy_draw.textbbox((0, 0), line, font=font)[0]
                 for line in lines)
    total_text_h = lh * len(lines) + gap * (len(lines) - 1)

    bw = max_tw + pad * 2
    bh = total_text_h + pad * 2
    bx = (w - bw) // 2
    by = h - bh - 10   # sits at bottom; tail goes UP above

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    r = min(bh // 2, 14)
    ld.rounded_rectangle(
        [bx, by, bx + bw, by + bh],
        radius=r,
        fill=(255, 255, 255, 235),
        outline=(0, 0, 0, 255),
        width=3,
    )
    # Tail points UPWARD toward the character above
    tcx = bx + bw // 2
    ld.polygon(
        [(tcx - 9, by + 1), (tcx + 9, by + 1), (tcx, by - tail)],
        fill=(255, 255, 255, 235),
    )
    ld.line([(tcx - 9, by), (tcx, by - tail)], fill=(0, 0, 0, 255), width=3)
    ld.line([(tcx + 9, by), (tcx, by - tail)], fill=(0, 0, 0, 255), width=3)

    img = Image.alpha_composite(img, layer)
    draw2 = ImageDraw.Draw(img)

    for i, line in enumerate(lines):
        b = draw2.textbbox((0, 0), line, font=font)
        tw = b[2] - b[0]
        tx = bx + pad + (bw - pad * 2 - tw) // 2
        ty = by + pad + i * (lh + gap)
        _draw_outlined_text(draw2, (tx, ty), line, font,
                            fill=(15, 15, 15, 255),
                            stroke_fill=(255, 255, 255, 180),
                            stroke_width=2)
    return img
