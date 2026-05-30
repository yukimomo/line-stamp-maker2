"""
Character-ification pipeline for LINE stamps.

Converts a photo into a sticker-worthy character image using pure Pillow + NumPy.
No OpenCV or MediaPipe required (though they are used opportunistically if available).

Pipeline:
  photo → style filter → sticker frame (rounded corners + white border + black outline)
        → expression overlay → caption → final stamp
"""

from __future__ import annotations
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from .text_styles import add_caption

# ---------------------------------------------------------------------------
# Constants / presets
# ---------------------------------------------------------------------------

STYLES: dict[str, str] = {
    "line_stamp": "LINEスタンプ風（太フチ・ポップ）",
    "yuru_chara": "ゆるキャラ風（柔らか・丸み）",
    "pop_art":    "ポップアート風（色鮮やか）",
    "manga":      "マンガ風（白黒・効果線）",
    "sticker":    "シール風（白縁・影付き）",
}

EXPRESSIONS: dict[str, str] = {
    "none":    "なし",
    "sparkle": "キラキラ ✦",
    "heart":   "ハート ♥",
    "sweat":   "汗 💧",
    "angry":   "怒り 💢",
    "tears":   "涙 😢",
}

# Frame parameters per style
_FRAME_PARAMS: dict[str, dict] = {
    "line_stamp": dict(corner_r=16, white_px=14, black_px=4, shadow_px=5, shadow_alpha=60),
    "yuru_chara": dict(corner_r=30, white_px=12, black_px=0, shadow_px=4, shadow_alpha=40,
                       border_color=(255, 200, 220)),
    "pop_art":    dict(corner_r=8,  white_px=12, black_px=5, shadow_px=6, shadow_alpha=80),
    "manga":      dict(corner_r=4,  white_px=10, black_px=6, shadow_px=4, shadow_alpha=90),
    "sticker":    dict(corner_r=22, white_px=16, black_px=3, shadow_px=8, shadow_alpha=45),
}


@dataclass
class StepImages:
    """Intermediate images for step-by-step preview (all RGBA)."""
    original: Image.Image   # original photo (resized for display)
    styled: Image.Image     # after style filter, before frame
    stamp: Image.Image      # final sticker image


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class CharacterProcessor:
    def __init__(self, style: str = "line_stamp", expression: str = "none"):
        self.style = style if style in STYLES else "line_stamp"
        self.expression = expression if expression in EXPRESSIONS else "none"

    def process(
        self,
        img: Image.Image,
        caption: str = "",
        text_style: str = "bubble",
    ) -> StepImages:
        """
        Convert *img* to a LINE stamp image.

        Returns StepImages with original, styled, and final stamp.
        """
        original = img.convert("RGBA")

        # 1. Apply style filter (color / tone effects)
        styled = _apply_style_filter(img, self.style)

        # 2. Add sticker frame (rounded corners, white border, outline, shadow)
        framed = _add_sticker_frame(styled, self.style)

        # 3. Add expression overlay
        if self.expression != "none":
            framed = _add_expression(framed, self.expression)

        # 4. Add caption
        if caption and caption.strip():
            framed = add_caption(framed, caption, style=text_style)

        return StepImages(
            original=original,
            styled=styled.convert("RGBA"),
            stamp=framed,
        )


# ---------------------------------------------------------------------------
# Style filters (pure Pillow)
# ---------------------------------------------------------------------------

def _apply_style_filter(img: Image.Image, style: str) -> Image.Image:
    rgb = img.convert("RGB")

    if style == "line_stamp":
        # Smooth + vivid colors
        rgb = rgb.filter(ImageFilter.SMOOTH)
        rgb = ImageEnhance.Color(rgb).enhance(1.55)
        rgb = ImageEnhance.Contrast(rgb).enhance(1.2)
        rgb = ImageEnhance.Brightness(rgb).enhance(1.05)

    elif style == "yuru_chara":
        # Heavy smooth + warm, soft pastel
        for _ in range(2):
            rgb = rgb.filter(ImageFilter.SMOOTH_MORE)
        rgb = ImageEnhance.Color(rgb).enhance(0.85)
        rgb = ImageEnhance.Brightness(rgb).enhance(1.1)
        # Warm tint (slight red-yellow push)
        arr = np.array(rgb, dtype=np.float32)
        arr[:, :, 0] = np.clip(arr[:, :, 0] * 1.06, 0, 255)
        arr[:, :, 2] = np.clip(arr[:, :, 2] * 0.94, 0, 255)
        rgb = Image.fromarray(arr.astype(np.uint8))

    elif style == "pop_art":
        # Color quantize → cartoon look
        try:
            rgb = rgb.quantize(colors=8, method=Image.Quantize.MEDIANCUT).convert("RGB")
        except Exception:
            pass
        rgb = ImageEnhance.Color(rgb).enhance(2.2)
        rgb = ImageEnhance.Contrast(rgb).enhance(1.3)

    elif style == "manga":
        # Grayscale + strong edge overlay
        gray = rgb.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edges = ImageEnhance.Contrast(edges).enhance(6.0)
        # Invert edges (lines become dark)
        edge_dark = edges.point(lambda x: max(0, 255 - x * 5))
        gray_rgb = gray.convert("RGB")
        # Paste black where edges are strong
        gray_rgb.paste(Image.new("RGB", gray_rgb.size, (0, 0, 0)),
                       mask=edge_dark)
        rgb = gray_rgb

    elif style == "sticker":
        # Clean, slightly brightened
        rgb = rgb.filter(ImageFilter.SMOOTH)
        rgb = ImageEnhance.Color(rgb).enhance(1.3)
        rgb = ImageEnhance.Brightness(rgb).enhance(1.08)
        rgb = ImageEnhance.Contrast(rgb).enhance(1.1)

    return rgb


# ---------------------------------------------------------------------------
# Sticker frame: rounded corners + white border + black outline + shadow
# ---------------------------------------------------------------------------

def _add_sticker_frame(img: Image.Image, style: str) -> Image.Image:
    """
    Wrap *img* in a stamp-style frame using ImageDraw.rounded_rectangle.
    Returns an RGBA image larger than the input.
    """
    p = _FRAME_PARAMS.get(style, _FRAME_PARAMS["line_stamp"])
    corner_r: int   = p["corner_r"]
    white_px: int   = p["white_px"]
    black_px: int   = p.get("black_px", 3)
    shadow_px: int  = p.get("shadow_px", 5)
    shadow_a: int   = p.get("shadow_alpha", 50)
    border_color    = p.get("border_color", (255, 255, 255))

    w, h = img.size
    total_pad = white_px + black_px + shadow_px + 4
    cw = w + total_pad * 2
    ch = h + total_pad * 2
    ox, oy = total_pad, total_pad  # where the image is placed

    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    def rect(x0, y0, x1, y1):
        return [x0, y0, x1, y1]

    # --- shadow ---
    if shadow_px > 0:
        sr = corner_r + white_px + black_px
        draw.rounded_rectangle(
            rect(ox - white_px - black_px + shadow_px,
                 oy - white_px - black_px + shadow_px,
                 ox + w + white_px + black_px - 1 + shadow_px,
                 oy + h + white_px + black_px - 1 + shadow_px),
            radius=max(sr, 4),
            fill=(0, 0, 0, shadow_a),
        )

    # --- black outline ---
    if black_px > 0:
        draw.rounded_rectangle(
            rect(ox - white_px - black_px, oy - white_px - black_px,
                 ox + w + white_px + black_px - 1, oy + h + white_px + black_px - 1),
            radius=max(corner_r + white_px + black_px, 4),
            fill=(0, 0, 0, 255),
        )

    # --- white (or tinted) border ---
    draw.rounded_rectangle(
        rect(ox - white_px, oy - white_px,
             ox + w + white_px - 1, oy + h + white_px - 1),
        radius=max(corner_r + white_px, 4),
        fill=(*border_color, 255),
    )

    # --- photo with rounded corners ---
    img_rgba = img.convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1],
                                            radius=corner_r, fill=255)
    img_rgba.putalpha(mask)
    canvas.paste(img_rgba, (ox, oy), img_rgba)

    return canvas


# ---------------------------------------------------------------------------
# Expression overlays
# ---------------------------------------------------------------------------

def _add_expression(img: Image.Image, expression: str) -> Image.Image:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img.size

    if expression == "sparkle":
        positions = [(30, 28), (w - 32, 28), (22, h // 3), (w - 24, h // 3)]
        for i, (cx, cy) in enumerate(positions):
            color = (255, 220, 0, 200) if i % 2 == 0 else (255, 255, 100, 200)
            _star(draw, cx, cy, 14, 5, color)
            _star(draw, cx, cy, 6, 2, (255, 255, 255, 200))

    elif expression == "heart":
        for cx, cy, sz in [(28, 28, 16), (w - 30, 35, 12), (18, 60, 8)]:
            _heart(draw, cx, cy, sz, (255, 80, 120, 210))

    elif expression == "sweat":
        for cx, cy, sz in [(w - 30, 30, 16), (w - 18, 55, 10)]:
            _sweat_drop(draw, cx, cy, sz, (100, 160, 255, 200))

    elif expression == "angry":
        for cx, cy in [(w - 40, 35), (w - 20, 55)]:
            _anger_mark(draw, cx, cy, 14, (220, 30, 30, 230))

    elif expression == "tears":
        for cx, cy, sz in [(w - 26, 38, 12), (w - 14, 58, 8)]:
            _sweat_drop(draw, cx, cy, sz, (140, 200, 255, 200))
        # small circles as sparkle-tears on the other side
        draw.ellipse([18, 38, 28, 48], fill=(180, 220, 255, 180))
        draw.ellipse([10, 55, 18, 63], fill=(180, 220, 255, 160))

    return Image.alpha_composite(img, overlay)


def _star(draw: ImageDraw.ImageDraw, cx, cy, outer_r, inner_r, color, n_points=4):
    pts = []
    for i in range(n_points * 2):
        r = outer_r if i % 2 == 0 else inner_r
        angle = math.pi * i / n_points - math.pi / 2
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(pts, fill=color)


def _heart(draw: ImageDraw.ImageDraw, cx, cy, size, color):
    """Draw a simple heart using two ellipses + triangle."""
    s = size
    draw.ellipse([cx - s, cy - s // 2, cx, cy + s // 2], fill=color)
    draw.ellipse([cx, cy - s // 2, cx + s, cy + s // 2], fill=color)
    draw.polygon([(cx - s, cy + s // 4), (cx + s, cy + s // 4),
                  (cx, cy + s + s // 2)], fill=color)


def _sweat_drop(draw: ImageDraw.ImageDraw, cx, cy, size, color):
    """Draw a teardrop: circle at bottom, pointed at top."""
    r = size // 2
    draw.ellipse([cx - r, cy, cx + r, cy + size], fill=color)
    draw.polygon([(cx - r + 2, cy + r), (cx + r - 2, cy + r),
                  (cx, cy - size // 2)], fill=color)


def _anger_mark(draw: ImageDraw.ImageDraw, cx, cy, size, color):
    """Draw a vein/anger mark (zig-zag)."""
    s = size
    pts = [
        (cx - s, cy),
        (cx - s // 3, cy - s),
        (cx + s // 3, cy + s // 2),
        (cx + s, cy - s // 4),
    ]
    draw.line(pts, fill=color, width=3)
