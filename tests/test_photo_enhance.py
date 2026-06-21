"""Tests for photo auto-correction."""

from __future__ import annotations
import numpy as np
import pytest
from PIL import Image

from app.services.photo_enhance import auto_enhance, adjust_brightness, EnhanceStats


def _dark_photo(w=200, h=200, level=40) -> Image.Image:
    return Image.new("RGB", (w, h), (level, level, level))


def _backlit_photo(w=200, h=200) -> Image.Image:
    """Bright sky at top, large dark subject below (classic backlight)."""
    arr = np.full((h, w, 3), 235, dtype=np.uint8)       # bright background
    arr[h // 4:, :] = 40                                  # large dark subject
    return Image.fromarray(arr, "RGB")


def _mean_luma(img: Image.Image) -> float:
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    return float((0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]).mean())


class TestAutoEnhance:
    def test_returns_image_and_stats(self):
        out, stats = auto_enhance(_dark_photo())
        assert isinstance(out, Image.Image)
        assert isinstance(stats, EnhanceStats)

    def test_output_is_rgb(self):
        out, _ = auto_enhance(_dark_photo())
        assert out.mode == "RGB"

    def test_same_size(self):
        out, _ = auto_enhance(_dark_photo(150, 250))
        assert out.size == (150, 250)

    def test_dark_photo_brightened(self):
        dark = _dark_photo(level=40)
        before = _mean_luma(dark)
        out, stats = auto_enhance(dark)
        assert stats.was_dark
        assert _mean_luma(out) > before

    def test_dark_flag(self):
        _, stats = auto_enhance(_dark_photo(level=30))
        assert stats.was_dark is True

    def test_bright_photo_not_flagged_dark(self):
        bright = Image.new("RGB", (200, 200), (200, 200, 200))
        _, stats = auto_enhance(bright)
        assert stats.was_dark is False

    def test_backlit_detected(self):
        _, stats = auto_enhance(_backlit_photo())
        assert stats.was_backlit is True

    def test_manual_brightness_delta(self):
        base = Image.new("RGB", (100, 100), (120, 120, 120))
        up, _ = auto_enhance(base, brightness_delta=0.4)
        down, _ = auto_enhance(base, brightness_delta=-0.4)
        assert _mean_luma(up) > _mean_luma(down)


class TestAdjustBrightness:
    def test_brighten(self):
        base = Image.new("RGB", (100, 100), (100, 100, 100))
        out = adjust_brightness(base, 0.5)
        assert _mean_luma(out) > _mean_luma(base)

    def test_darken(self):
        base = Image.new("RGB", (100, 100), (150, 150, 150))
        out = adjust_brightness(base, -0.5)
        assert _mean_luma(out) < _mean_luma(base)

    def test_zero_delta_unchanged(self):
        base = Image.new("RGB", (100, 100), (120, 120, 120))
        out = adjust_brightness(base, 0.0)
        assert _mean_luma(out) == pytest.approx(_mean_luma(base), abs=1.0)
