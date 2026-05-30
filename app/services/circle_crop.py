"""
Circular crop with smart centering.

Without face detection (no OpenCV/MediaPipe in this env), uses an
upper-center heuristic: portrait photos keep subjects in the upper ~65%,
so we bias the crop center upward.

Returns RGBA with transparent corners (outside the circle).
"""

from __future__ import annotations
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def circular_crop(
    img: Image.Image,
    size: int = 220,
    portrait_bias: float = 0.30,
) -> Image.Image:
    """
    Crop *img* to a circle of *size* px, biased toward the upper-center.

    Args:
        img:           Input image (any mode).
        size:          Output circle diameter in pixels.
        portrait_bias: Relative Y position of the crop center in [0, 1].
                       0.0 = very top, 0.5 = exact center.
                       0.30 works well for portrait / close-up shots.
    Returns:
        RGBA image, *size* × *size*, transparent outside the circle.
    """
    rgb = _to_rgb(img)
    w, h = rgb.size

    # Square crop side = min dimension
    side = min(w, h)

    # Horizontal center
    x0 = (w - side) // 2

    # Vertical: bias toward top for portrait photos
    max_y0 = h - side
    y0 = int(max_y0 * portrait_bias)
    y0 = max(0, min(y0, max_y0))

    square = rgb.crop((x0, y0, x0 + side, y0 + side))
    square = square.resize((size, size), Image.Resampling.LANCZOS)

    # Circular mask
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)

    result = square.convert("RGBA")
    result.putalpha(mask)
    return result


def add_circle_border(
    circle_img: Image.Image,
    white_px: int = 14,
    black_px: int = 3,
    shadow: bool = True,
    shadow_offset: int = 5,
    shadow_blur: int = 8,
    shadow_alpha: int = 70,
    border_color: tuple[int, int, int] = (255, 255, 255),
) -> tuple[Image.Image, int]:
    """
    Add white (or colored) border + optional thin black ring + drop shadow
    around a circular RGBA image.

    Returns:
        (decorated_image, total_added_radius)
        decorated_image is larger than circle_img by the border + shadow padding.
    """
    size = circle_img.width  # assumed square
    total_border = white_px + black_px
    shadow_pad = (shadow_offset + shadow_blur + 2) if shadow else 0
    pad = total_border + shadow_pad + 2

    cw = size + pad * 2
    canvas = Image.new("RGBA", (cw, cw), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    ox = oy = pad  # offset of circle inside canvas

    # ── shadow ──────────────────────────────────────────────────────────────
    if shadow:
        r_shadow = size // 2 + total_border
        sx, sy = ox + size // 2 + shadow_offset, oy + size // 2 + shadow_offset
        shadow_layer = Image.new("RGBA", (cw, cw), (0, 0, 0, 0))
        ImageDraw.Draw(shadow_layer).ellipse(
            [sx - r_shadow, sy - r_shadow, sx + r_shadow - 1, sy + r_shadow - 1],
            fill=(0, 0, 0, shadow_alpha),
        )
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
        canvas = Image.alpha_composite(canvas, shadow_layer)
        draw = ImageDraw.Draw(canvas)

    # ── black outer ring ────────────────────────────────────────────────────
    if black_px > 0:
        r_black = size // 2 + white_px + black_px
        cx = oy + size // 2
        draw.ellipse(
            [ox + size // 2 - r_black, cx - r_black,
             ox + size // 2 + r_black - 1, cx + r_black - 1],
            fill=(0, 0, 0, 255),
        )

    # ── white (or tinted) border ────────────────────────────────────────────
    r_white = size // 2 + white_px
    cx = cy = pad + size // 2
    draw.ellipse(
        [cx - r_white, cy - r_white, cx + r_white - 1, cy + r_white - 1],
        fill=(*border_color, 255),
    )

    # ── paste circle photo ──────────────────────────────────────────────────
    canvas.paste(circle_img, (ox, oy), circle_img)

    return canvas, pad


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_rgb(img: Image.Image) -> Image.Image:
    """Flatten transparency onto white, return RGB."""
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        return bg
    return img.convert("RGB")
