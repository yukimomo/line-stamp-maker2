"""
Circular crop with smart centering.

`circular_crop` is the legacy upper-center heuristic (kept for compatibility).
`circular_crop_smart` uses face-detection results to center and zoom the crop
on the subject, with manual zoom / offset overrides.

Returns RGBA with transparent corners (outside the circle).
"""

from __future__ import annotations
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .face_detect import FaceInfo, detect_faces


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


def circular_crop_smart(
    img: Image.Image,
    size: int = 220,
    face_info: FaceInfo | None = None,
    target_face_frac: float = 0.42,
    zoom: float = 1.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> Image.Image:
    """
    Face-centered circular crop with zoom control.

    Args:
        img:              Input image.
        size:             Output circle diameter (px).
        face_info:        Pre-computed FaceInfo; if None, detection runs here.
        target_face_frac: Desired largest-face height as a fraction of the
                          crop side (bigger = face appears larger).
        zoom:             Manual zoom multiplier (>1 zooms in). Range ~0.5-2.5.
        offset_x/offset_y:Manual recenter, fraction of image size (-0.5..0.5).

    Returns:
        RGBA circle image, size × size.
    """
    rgb = _to_rgb(img)
    w, h = rgb.size
    if face_info is None:
        face_info = detect_faces(rgb)

    # ── crop center ──────────────────────────────────────────────────────────
    union = face_info.union_box
    if union is not None:
        cx = union[0] + union[2] / 2
        cy = union[1] + union[3] / 2
        # Nudge down slightly so the body/chin is included, not just eyes
        cy += union[3] * 0.15
    else:
        # No face: upper-center default
        cx = w / 2
        cy = h * 0.42

    cx += offset_x * w
    cy += offset_y * h

    # ── crop side ────────────────────────────────────────────────────────────
    base = float(min(w, h))
    if face_info.primary_box is not None:
        face_h = face_info.primary_box[3]
        side = face_h / max(0.15, target_face_frac)
        # Ensure all faces fit (multi-person): cover union box with padding
        if union is not None:
            need = max(union[2], union[3]) * 1.4
            side = max(side, need)
    else:
        side = base * 0.85

    side = side / max(0.4, zoom)
    side = max(40.0, min(side, base))   # never exceed the image's short edge

    # ── clamp center so the square stays inside the image ───────────────────
    half = side / 2
    cx = max(half, min(cx, w - half))
    cy = max(half, min(cy, h - half))

    left = int(round(cx - half))
    top = int(round(cy - half))
    iside = int(round(side))
    left = max(0, min(left, w - iside))
    top = max(0, min(top, h - iside))

    square = rgb.crop((left, top, left + iside, top + iside))
    square = square.resize((size, size), Image.Resampling.LANCZOS)

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
    black_color: tuple[int, int, int] = (0, 0, 0),
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
            fill=(*black_color, 255),
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
