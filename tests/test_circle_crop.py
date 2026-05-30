"""Tests for circular crop and border functions."""

from __future__ import annotations
import pytest
from PIL import Image
import numpy as np

from app.services.circle_crop import circular_crop, add_circle_border


def _photo(w: int = 400, h: int = 500, color=(180, 140, 110)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


class TestCircularCrop:
    def test_output_is_square(self):
        result = circular_crop(_photo(), size=200)
        assert result.width == result.height == 200

    def test_output_mode_rgba(self):
        result = circular_crop(_photo(), size=200)
        assert result.mode == "RGBA"

    def test_corners_transparent(self):
        result = circular_crop(_photo(), size=200)
        # Top-left corner should be fully transparent
        assert result.getpixel((0, 0))[3] == 0
        assert result.getpixel((199, 0))[3] == 0

    def test_center_opaque(self):
        result = circular_crop(_photo(), size=200)
        cx, cy = 100, 100
        assert result.getpixel((cx, cy))[3] == 255

    def test_landscape_photo(self):
        result = circular_crop(_photo(600, 300), size=150)
        assert result.size == (150, 150)
        assert result.getpixel((0, 0))[3] == 0       # corner transparent
        assert result.getpixel((75, 75))[3] == 255   # center opaque

    def test_portrait_photo(self):
        result = circular_crop(_photo(300, 600), size=150)
        assert result.size == (150, 150)

    def test_square_photo(self):
        result = circular_crop(_photo(400, 400), size=200)
        assert result.size == (200, 200)

    def test_rgba_input_handled(self):
        img = Image.new("RGBA", (300, 300), (200, 150, 100, 200))
        result = circular_crop(img, size=150)
        assert result.mode == "RGBA"
        assert result.size == (150, 150)

    def test_portrait_bias_crops_upper(self):
        """Upper-center bias: upper half should dominate the cropped area."""
        # Create image with distinct upper (red) and lower (blue) halves
        img = Image.new("RGB", (300, 600), (0, 0, 255))
        red_half = Image.new("RGB", (300, 300), (255, 0, 0))
        img.paste(red_half, (0, 0))
        result = circular_crop(img, size=200, portrait_bias=0.0)
        # With bias=0 (top), center pixel should be reddish
        cx, cy = 100, 100
        r, g, b, _ = result.getpixel((cx, cy))
        assert r > b, "With portrait_bias=0, upper (red) part should dominate"


class TestAddCircleBorder:
    def test_output_larger_than_input(self):
        circle = circular_crop(_photo(), size=200)
        decorated, pad = add_circle_border(circle, white_px=14, black_px=3)
        assert decorated.width > 200
        assert decorated.height > 200

    def test_output_is_rgba(self):
        circle = circular_crop(_photo(), size=200)
        decorated, _ = add_circle_border(circle)
        assert decorated.mode == "RGBA"

    def test_corners_transparent(self):
        circle = circular_crop(_photo(), size=200)
        decorated, _ = add_circle_border(circle, shadow=False)
        assert decorated.getpixel((0, 0))[3] == 0

    def test_no_black_border(self):
        circle = circular_crop(_photo(), size=200)
        decorated, pad = add_circle_border(circle, white_px=10, black_px=0, shadow=False)
        assert isinstance(decorated, Image.Image)

    def test_colored_border(self):
        circle = circular_crop(_photo(), size=200)
        decorated, _ = add_circle_border(
            circle, white_px=12, black_px=0, shadow=False,
            border_color=(255, 100, 150)
        )
        assert decorated.mode == "RGBA"
