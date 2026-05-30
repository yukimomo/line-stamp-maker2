"""
Character-ification pipeline for LINE stamps.

New approach:
  photo → circular crop (upper-center bias) → template decorations → stamp

Uses only Pillow + NumPy. No OpenCV / MediaPipe required.
"""

from __future__ import annotations
from dataclasses import dataclass

from PIL import Image

from .circle_crop import circular_crop
from .stamp_templates import TEMPLATES, apply_template, auto_select_template, CIRCLE_DIAM
from .text_styles import TEXT_STYLES

# Re-export for backward compat (routes still reference STYLES)
STYLES = TEMPLATES
EXPRESSIONS: dict[str, str] = {
    "none": "なし",
}


@dataclass
class StepImages:
    """Intermediate images for step-by-step preview (all RGBA)."""
    original: Image.Image   # resized source photo
    styled: Image.Image     # circle-cropped (before decorations)
    stamp: Image.Image      # final stamp with decorations + text


class CharacterProcessor:
    """Convert a photo to a LINE stamp via circular crop + template."""

    def __init__(
        self,
        style: str = "simple_circle",   # maps to template name
        expression: str = "none",        # kept for API compat, unused
    ):
        self.template = style if style in TEMPLATES else "simple_circle"
        self.expression = expression  # reserved for future use

    def process(
        self,
        img: Image.Image,
        caption: str = "",
        text_style: str = "pop",
    ) -> StepImages:
        """
        Convert *img* to a LINE stamp.

        Returns StepImages with:
          - original: source photo as RGBA
          - styled:   circle-cropped photo (transparent background)
          - stamp:    final stamp image with decorations + text
        """
        original = img.convert("RGBA")

        # Step 1: circular crop with upper-center bias
        circle = circular_crop(img, size=CIRCLE_DIAM)

        # Step 2: apply template (background, decorations, border, text)
        stamp = apply_template(circle, self.template, caption, text_style, seed=0)

        return StepImages(original=original, styled=circle, stamp=stamp)
