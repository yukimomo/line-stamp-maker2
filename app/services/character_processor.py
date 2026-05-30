"""
Character-ification pipeline for LINE stamps.

Pipeline:
  photo
    → auto-enhance (brightness/contrast/backlight)
    → face detection
    → face-centered circular crop (per-template zoom + manual adjustments)
    → template decorations + text
    → stamp

cv2 is used for face detection when available; otherwise a NumPy skin-tone
heuristic is used. Everything else is pure Pillow + NumPy.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from PIL import Image

from .circle_crop import circular_crop_smart
from .face_detect import FaceInfo, detect_faces
from .photo_enhance import auto_enhance, EnhanceStats
from .stamp_templates import (
    TEMPLATES, apply_template, auto_select_template, zoom_preset, CIRCLE_DIAM,
)
from .text_styles import TEXT_STYLES

# Re-export for backward compat (routes still reference STYLES)
STYLES = TEMPLATES
EXPRESSIONS: dict[str, str] = {"none": "なし"}


@dataclass
class Adjustments:
    """Manual per-item overrides applied on top of auto-correction."""
    zoom: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    brightness: float = 0.0     # -1..+1
    enhance: bool = True        # apply auto-enhance


@dataclass
class StepImages:
    original: Image.Image
    styled: Image.Image                       # face-centered circle (pre-decoration)
    stamp: Image.Image
    face_info: FaceInfo | None = None
    enhance_stats: EnhanceStats | None = None


class CharacterProcessor:
    """Convert a photo to a LINE stamp via enhance + face-crop + template."""

    def __init__(self, style: str = "simple_circle", expression: str = "none"):
        self.template = style if style in TEMPLATES else "simple_circle"
        self.expression = expression

    def process(
        self,
        img: Image.Image,
        caption: str = "",
        text_style: str = "pop",
        adjustments: Adjustments | None = None,
    ) -> StepImages:
        adj = adjustments or Adjustments()
        original = img.convert("RGBA")

        # 1. Auto-enhance (brightness / contrast / backlight) + manual brightness
        if adj.enhance:
            enhanced, stats = auto_enhance(img, brightness_delta=adj.brightness)
        else:
            from .photo_enhance import adjust_brightness
            enhanced = adjust_brightness(img, adj.brightness) if adj.brightness else img.convert("RGB")
            stats = None

        # 2. Face detection (on the enhanced image)
        face_info = detect_faces(enhanced)

        # 3. Face-centered circular crop with per-template zoom + manual overrides
        preset = zoom_preset(self.template)
        circle = circular_crop_smart(
            enhanced,
            size=CIRCLE_DIAM,
            face_info=face_info,
            target_face_frac=preset["target_face_frac"],
            zoom=preset["zoom"] * adj.zoom,
            offset_x=adj.offset_x,
            offset_y=adj.offset_y,
        )

        # 4. Template decorations + text
        stamp = apply_template(circle, self.template, caption, text_style, seed=0)

        return StepImages(
            original=original,
            styled=circle,
            stamp=stamp,
            face_info=face_info,
            enhance_stats=stats,
        )
