"""Tests for quality / framing warnings."""

from __future__ import annotations
import numpy as np
import pytest
from PIL import Image

from app.services.face_detect import FaceInfo
from app.services.quality_check import analyze_quality


def _photo(w=800, h=800, color=(160, 160, 160)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


def _noisy_photo(w=800, h=800) -> Image.Image:
    """Sharp, well-lit photo (random noise => high sharpness, mid brightness)."""
    rng = np.random.default_rng(0)
    arr = rng.integers(80, 200, (h, w, 3), dtype=np.uint8)
    return Image.fromarray(arr, "RGB")


class TestAnalyzeQuality:
    def test_returns_list(self):
        result = analyze_quality(_noisy_photo(), None)
        assert isinstance(result, list)

    def test_dark_photo_warns(self):
        dark = _photo(color=(30, 30, 30))
        warns = analyze_quality(dark, None)
        assert any("暗" in w for w in warns)

    def test_lowres_photo_warns(self):
        small = _noisy_photo(200, 200)
        warns = analyze_quality(small, None)
        assert any("粗" in w for w in warns)

    def test_blurry_photo_warns(self):
        # Flat image => zero high-frequency => blurry warning
        flat = _photo(900, 900, color=(150, 150, 150))
        warns = analyze_quality(flat, None)
        assert any("ピント" in w or "ブレ" in w for w in warns)

    def test_face_too_small_warns(self):
        img = _noisy_photo(800, 800)
        # face 40x40 in 800x800 -> fraction 0.0025 < threshold
        fi = FaceInfo(boxes=[(380, 380, 40, 40)], image_size=(800, 800), method="haar")
        warns = analyze_quality(img, fi)
        assert any("顔が小さ" in w for w in warns)

    def test_face_cutoff_warns(self):
        img = _noisy_photo(800, 800)
        # face at the very left edge
        fi = FaceInfo(boxes=[(0, 300, 200, 200)], image_size=(800, 800), method="haar")
        warns = analyze_quality(img, fi)
        assert any("見切れ" in w for w in warns)

    def test_multi_person_cutoff_warns(self):
        img = _noisy_photo(800, 800)
        fi = FaceInfo(
            boxes=[(0, 300, 150, 150), (600, 300, 150, 150)],   # touches both edges
            image_size=(800, 800), method="haar",
        )
        warns = analyze_quality(img, fi)
        assert any("複数人" in w for w in warns)

    def test_no_face_default_method_warns(self):
        img = _noisy_photo(800, 800)
        fi = FaceInfo(boxes=[], image_size=(800, 800), method="default")
        warns = analyze_quality(img, fi)
        assert any("顔を検出できません" in w for w in warns)

    def test_good_photo_centered_face_no_face_warnings(self):
        img = _noisy_photo(800, 800)
        # Large, centered face -> no face-size/cutoff warnings
        fi = FaceInfo(boxes=[(280, 250, 240, 240)], image_size=(800, 800), method="haar")
        warns = analyze_quality(img, fi, caption="ありがとう", text_style="bubble")
        assert not any("顔が小さ" in w for w in warns)
        assert not any("見切れ" in w for w in warns)
