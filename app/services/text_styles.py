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
    Returns a new RGBA image.
    """
    if not text or not text.strip():
        return img

    w, _ = img.size
    font_size = auto_font_size(text, w - 24)
    font = load_font(font_size)

    dispatch = {
        "bubble":        _bubble,
        "pop":           _pop,
        "shadow":        _shadow,
        "outline_white": lambda i, t, f: _simple_outline(i, t, f,
                             fill=(255, 255, 255, 255), stroke=(0, 0, 0, 255), sw=5),
        "outline_black": lambda i, t, f: _simple_outline(i, t, f,
                             fill=(20, 20, 20, 255), stroke=(255, 255, 255, 255), sw=5),
    }
    fn = dispatch.get(style, _pop)
    return fn(img, text, font)


def _pop(img: Image.Image, text: str, font) -> Image.Image:
    draw = ImageDraw.Draw(img)
    x, y = _bottom_center_xy(draw, text, font, *img.size)
    _draw_outlined_text(draw, (x, y), text, font,
                        fill=(255, 255, 255, 255),
                        stroke_fill=(0, 0, 0, 255),
                        stroke_width=6)
    return img


def _shadow(img: Image.Image, text: str, font) -> Image.Image:
    draw = ImageDraw.Draw(img)
    x, y = _bottom_center_xy(draw, text, font, *img.size)
    draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0, 150))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    return img


def _simple_outline(img, text, font, fill, stroke, sw) -> Image.Image:
    draw = ImageDraw.Draw(img)
    x, y = _bottom_center_xy(draw, text, font, *img.size)
    _draw_outlined_text(draw, (x, y), text, font,
                        fill=fill, stroke_fill=stroke, stroke_width=sw)
    return img


def _bubble(img: Image.Image, text: str, font) -> Image.Image:
    """Draw text inside a speech bubble at the bottom."""
    w, h = img.size
    draw = ImageDraw.Draw(img)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad = 12
    bw = tw + pad * 2
    bh = th + pad * 2
    tail = 13

    bx = (w - bw) // 2
    by = h - bh - tail - 10

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
    # Tail
    cx = bx + bw // 2
    ld.polygon(
        [(cx - 9, by + bh - 1), (cx + 9, by + bh - 1), (cx, by + bh + tail)],
        fill=(255, 255, 255, 235),
    )
    ld.line([(cx - 9, by + bh), (cx, by + bh + tail)], fill=(0, 0, 0, 255), width=3)
    ld.line([(cx + 9, by + bh), (cx, by + bh + tail)], fill=(0, 0, 0, 255), width=3)

    img = Image.alpha_composite(img, layer)
    draw2 = ImageDraw.Draw(img)
    tx = bx + pad + (bw - pad * 2 - tw) // 2
    ty = by + pad
    _draw_outlined_text(draw2, (tx, ty), text, font,
                        fill=(15, 15, 15, 255),
                        stroke_fill=(255, 255, 255, 180),
                        stroke_width=2)
    return img
