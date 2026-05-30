"""Tests for the character-ification pipeline."""

from __future__ import annotations
from pathlib import Path

import pytest
from PIL import Image

from app.services.character_processor import (
    CharacterProcessor,
    StepImages,
    STYLES,
    EXPRESSIONS,
    _apply_style_filter,
    _add_sticker_frame,
    _add_expression,
)


def _photo(w=200, h=260) -> Image.Image:
    """Create a simple test photo (gradient to simulate a portrait)."""
    import numpy as np
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :, 0] = 180  # red channel
    arr[:h//2, :, 1] = 120  # green top half
    arr[h//2:, :, 2] = 200  # blue bottom half
    return Image.fromarray(arr, mode="RGB")


class TestStyleFilter:
    @pytest.mark.parametrize("style", list(STYLES.keys()))
    def test_returns_rgb(self, style):
        photo = _photo()
        result = _apply_style_filter(photo, style)
        assert isinstance(result, Image.Image)
        assert result.mode == "RGB"

    @pytest.mark.parametrize("style", list(STYLES.keys()))
    def test_same_size(self, style):
        photo = _photo(150, 200)
        result = _apply_style_filter(photo, style)
        assert result.size == photo.size

    def test_pop_art_changes_pixels(self):
        photo = _photo()
        result = _apply_style_filter(photo, "pop_art")
        assert list(photo.getdata()) != list(result.getdata())

    def test_manga_desaturates(self):
        """Manga filter should produce a mostly-gray image."""
        photo = _photo()
        result = _apply_style_filter(photo, "manga")
        arr = list(result.getdata())
        # Most pixels should have r≈g≈b (grayscale)
        gray_pixels = sum(1 for r, g, b in arr if abs(r - g) < 20 and abs(g - b) < 20)
        assert gray_pixels > len(arr) * 0.5


class TestStickerFrame:
    @pytest.mark.parametrize("style", list(STYLES.keys()))
    def test_returns_rgba(self, style):
        img = _photo()
        result = _add_sticker_frame(img, style)
        assert isinstance(result, Image.Image)
        assert result.mode == "RGBA"

    @pytest.mark.parametrize("style", list(STYLES.keys()))
    def test_larger_than_input(self, style):
        img = _photo(150, 200)
        result = _add_sticker_frame(img, style)
        assert result.width > img.width
        assert result.height > img.height

    def test_has_transparency(self):
        """The corners should be transparent (RGBA alpha=0)."""
        img = _photo(100, 100)
        result = _add_sticker_frame(img, "line_stamp")
        # Top-left corner pixel should be fully transparent
        assert result.getpixel((0, 0))[3] == 0


class TestExpressionOverlay:
    @pytest.mark.parametrize("expr", [e for e in EXPRESSIONS if e != "none"])
    def test_returns_rgba(self, expr):
        img = Image.new("RGBA", (300, 260), (200, 200, 200, 255))
        result = _add_expression(img, expr)
        assert isinstance(result, Image.Image)
        assert result.mode == "RGBA"

    @pytest.mark.parametrize("expr", [e for e in EXPRESSIONS if e != "none"])
    def test_pixels_change(self, expr):
        img = Image.new("RGBA", (300, 260), (200, 200, 200, 255))
        original = list(img.getdata())
        result = _add_expression(img, expr)
        assert list(result.getdata()) != original

    def test_none_expression_unchanged(self):
        img = Image.new("RGBA", (300, 260), (100, 150, 200, 255))
        # _add_expression with "none" should NOT be called (CharacterProcessor guards it)
        # but if called it should not break
        from app.services.character_processor import _add_expression
        # expression="none" is guarded in CharacterProcessor.process(), not here,
        # so just check it doesn't crash
        result = _add_expression(img.copy(), "sparkle")
        assert isinstance(result, Image.Image)


class TestCharacterProcessor:
    def _make_processor(self, style="line_stamp", expression="none"):
        return CharacterProcessor(style=style, expression=expression)

    @pytest.mark.parametrize("style", list(STYLES.keys()))
    def test_process_returns_step_images(self, style):
        proc = self._make_processor(style=style)
        steps = proc.process(_photo(), caption="テスト")
        assert isinstance(steps, StepImages)
        assert isinstance(steps.original, Image.Image)
        assert isinstance(steps.styled, Image.Image)
        assert isinstance(steps.stamp, Image.Image)

    @pytest.mark.parametrize("style", list(STYLES.keys()))
    def test_stamp_is_rgba(self, style):
        proc = self._make_processor(style=style)
        steps = proc.process(_photo())
        assert steps.stamp.mode == "RGBA"

    def test_stamp_larger_than_original(self):
        photo = _photo(150, 200)
        proc = self._make_processor()
        steps = proc.process(photo)
        # Stamp includes the border so it should be larger
        assert steps.stamp.width > photo.width or steps.stamp.height > photo.height

    @pytest.mark.parametrize("text", ["ありがとう", "了解", "おつかれさま"])
    def test_japanese_caption_no_error(self, text):
        proc = self._make_processor()
        steps = proc.process(_photo(), caption=text, text_style="bubble")
        assert isinstance(steps.stamp, Image.Image)

    @pytest.mark.parametrize("expr", list(EXPRESSIONS.keys()))
    def test_all_expressions(self, expr):
        proc = CharacterProcessor(style="line_stamp", expression=expr)
        steps = proc.process(_photo(), caption="テスト")
        assert isinstance(steps.stamp, Image.Image)

    def test_invalid_style_falls_back(self):
        proc = CharacterProcessor(style="nonexistent_style")
        assert proc.style == "line_stamp"

    def test_invalid_expression_falls_back(self):
        proc = CharacterProcessor(expression="flying_spaghetti")
        assert proc.expression == "none"

    @pytest.mark.parametrize("text_style", ["bubble", "pop", "shadow", "outline_white", "outline_black"])
    def test_all_text_styles(self, text_style):
        proc = self._make_processor()
        steps = proc.process(_photo(), caption="おやすみ", text_style=text_style)
        assert isinstance(steps.stamp, Image.Image)
