"""Tests for Japanese text rendering."""

from __future__ import annotations
from pathlib import Path

import pytest
from PIL import Image

from app.services.text_styles import (
    find_japanese_font,
    load_font,
    auto_font_size,
    add_caption,
    TEXT_STYLES,
)

JAPANESE_SAMPLES = ["ありがとう", "了解", "おつかれさま", "OK", "ごめん"]


class TestFontDiscovery:
    def test_find_japanese_font_returns_path_or_none(self):
        result = find_japanese_font()
        # May be None in CI, but should not raise
        assert result is None or isinstance(result, Path)

    def test_find_japanese_font_exists_if_found(self):
        p = find_japanese_font()
        if p is not None:
            assert p.exists(), f"Font path does not exist: {p}"

    def test_load_font_does_not_raise(self):
        font = load_font(32)
        assert font is not None

    def test_load_font_cached(self):
        f1 = load_font(24)
        f2 = load_font(24)
        assert f1 is f2  # same object from cache


class TestAutoFontSize:
    def test_returns_int(self):
        size = auto_font_size("了解", max_width=200)
        assert isinstance(size, int)

    def test_respects_min_size(self):
        # Very long text should fall back to min_size
        size = auto_font_size("あいうえおかきくけこさしすせそたちつてと", max_width=50, min_size=12)
        assert size >= 12

    def test_short_text_gets_large_size(self):
        size = auto_font_size("OK", max_width=300, base_size=60)
        assert size >= 40  # should fit at a decent size


class TestAddCaption:
    """Verify each text style renders without exception and returns correct type."""

    def _blank(self, w=300, h=260) -> Image.Image:
        return Image.new("RGBA", (w, h), (200, 220, 255, 255))

    @pytest.mark.parametrize("text", JAPANESE_SAMPLES)
    @pytest.mark.parametrize("style", list(TEXT_STYLES.keys()))
    def test_render_japanese_no_error(self, text, style):
        img = self._blank()
        result = add_caption(img, text, style=style)
        assert isinstance(result, Image.Image)
        assert result.mode == "RGBA"

    def test_empty_text_returns_original(self):
        img = self._blank()
        result = add_caption(img, "", style="pop")
        assert result is img  # same object, untouched

    def test_whitespace_text_returns_original(self):
        img = self._blank()
        result = add_caption(img, "   ", style="bubble")
        assert result is img

    def test_output_same_size_as_input(self):
        img = self._blank(370, 320)
        result = add_caption(img, "ありがとう", style="bubble")
        assert result.size == (370, 320)

    def test_pixels_change_after_render(self):
        """Rendering text should modify at least some pixels."""
        img = Image.new("RGBA", (300, 260), (200, 200, 200, 255))
        original_pixels = list(img.getdata())
        result = add_caption(img.copy(), "了解", style="pop")
        new_pixels = list(result.getdata())
        assert original_pixels != new_pixels, "Text render changed no pixels"

    @pytest.mark.parametrize("style", list(TEXT_STYLES.keys()))
    def test_all_styles_with_arigatou(self, style):
        img = self._blank()
        result = add_caption(img, "ありがとう", style=style)
        assert isinstance(result, Image.Image)
