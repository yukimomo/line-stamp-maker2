"""
Photo auto-correction for stamp legibility.

Pure Pillow + NumPy. Applies brightness / contrast / saturation / sharpness
correction, lifts shadows for backlit or dark photos, and keeps skin tones
from going too dark.

Manual overrides (brightness delta) are layered on top via `adjust`.
"""

from __future__ import annotations
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


@dataclass
class EnhanceStats:
    mean_brightness: float       # 0-255 of the original
    was_dark: bool
    was_backlit: bool


def auto_enhance(
    img: Image.Image,
    brightness_delta: float = 0.0,
) -> tuple[Image.Image, EnhanceStats]:
    """
    Auto-correct *img* for stamp use.

    Args:
        img:              source image (any mode)
        brightness_delta: manual brightness offset, -1.0..+1.0 (added on top)

    Returns:
        (enhanced RGB image, EnhanceStats)
    """
    rgb = img.convert("RGB")
    stats = _measure(rgb)

    # 1. Lift shadows on dark / backlit photos
    if stats.was_dark or stats.was_backlit:
        rgb = _lift_shadows(rgb, strength=0.6 if stats.was_backlit else 0.4)

    # 2. Normalize overall tone (mild autocontrast keeps it natural)
    rgb = ImageOps.autocontrast(rgb, cutoff=1)

    # 3. Brightness — push up if still dark
    target = 1.0
    if stats.mean_brightness < 90:
        target = 1.25
    elif stats.mean_brightness < 115:
        target = 1.12
    target += brightness_delta
    target = max(0.4, min(2.0, target))
    rgb = ImageEnhance.Brightness(rgb).enhance(target)

    # 4. Contrast / saturation / sharpness for pop
    rgb = ImageEnhance.Contrast(rgb).enhance(1.08)
    rgb = ImageEnhance.Color(rgb).enhance(1.18)
    rgb = ImageEnhance.Sharpness(rgb).enhance(1.4)

    # 5. Protect skin tones from being crushed dark
    rgb = _protect_skin(rgb)

    return rgb, stats


def adjust_brightness(img: Image.Image, delta: float) -> Image.Image:
    """Standalone manual brightness tweak (delta -1..+1)."""
    factor = max(0.4, min(2.0, 1.0 + delta))
    return ImageEnhance.Brightness(img.convert("RGB")).enhance(factor)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _measure(rgb: Image.Image) -> EnhanceStats:
    arr = np.asarray(rgb).astype(np.float32)
    luma = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    mean = float(luma.mean())

    was_dark = mean < 100

    # Backlit: bright background (high top-percentile) but dark subject (low mean)
    p90 = float(np.percentile(luma, 90))
    p20 = float(np.percentile(luma, 20))
    was_backlit = (p90 > 200) and (p20 < 70) and (mean < 130)

    return EnhanceStats(mean_brightness=mean, was_dark=was_dark, was_backlit=was_backlit)


def _lift_shadows(rgb: Image.Image, strength: float) -> Image.Image:
    """
    Brighten dark regions while preserving highlights (gamma-style curve on
    the dark end). strength 0..1.
    """
    arr = np.asarray(rgb).astype(np.float32) / 255.0
    # Lift shadows: x^gamma with gamma<1 brightens darks; weight by darkness
    gamma = 1.0 - 0.5 * strength          # e.g. strength .6 -> gamma .7
    lifted = np.power(arr, gamma)
    # Blend more in shadows, less in highlights
    luma = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    weight = np.clip(1.0 - luma, 0, 1)[:, :, None]   # darker -> stronger
    out = arr * (1 - weight) + lifted * weight
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8))


def _protect_skin(rgb: Image.Image) -> Image.Image:
    """Slightly brighten skin-tone pixels that are too dark."""
    arr = np.asarray(rgb).astype(np.int32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    skin = (r > 60) & (g > 30) & (b > 15) & (r > g) & (r > b) & (np.abs(r - g) > 10)
    dark_skin = skin & (((r + g + b) / 3) < 110)
    if dark_skin.sum() == 0:
        return rgb
    arr_f = arr.astype(np.float32)
    for c in range(3):
        chan = arr_f[:, :, c]
        chan[dark_skin] = np.clip(chan[dark_skin] * 1.18, 0, 255)
    return Image.fromarray(arr_f.astype(np.uint8))
