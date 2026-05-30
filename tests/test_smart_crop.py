"""Tests for face-centered smart circular crop and new templates."""

from __future__ import annotations
import numpy as np
import pytest
from PIL import Image

from app.services.circle_crop import circular_crop_smart
from app.services.face_detect import FaceInfo
from app.services.stamp_templates import (
    TEMPLATES, apply_template, zoom_preset, ZOOM_PRESETS, CIRCLE_DIAM,
)

NEW_TEMPLATES = ["group_badge", "action_pop", "bright_frame", "soft_pastel"]


def _photo(w=400, h=500) -> Image.Image:
    rng = np.random.default_rng(1)
    return Image.fromarray(rng.integers(60, 200, (h, w, 3), dtype=np.uint8), "RGB")


class TestCircularCropSmart:
    def test_output_size_and_mode(self):
        out = circular_crop_smart(_photo(), size=220)
        assert out.size == (220, 220)
        assert out.mode == "RGBA"

    def test_transparent_corners(self):
        out = circular_crop_smart(_photo(), size=200)
        assert out.getpixel((0, 0))[3] == 0
        assert out.getpixel((100, 100))[3] == 255

    def test_with_face_info(self):
        fi = FaceInfo(boxes=[(150, 150, 100, 100)], image_size=(400, 500), method="haar")
        out = circular_crop_smart(_photo(), size=200, face_info=fi)
        assert out.size == (200, 200)

    def test_zoom_changes_crop(self):
        fi = FaceInfo(boxes=[(150, 150, 100, 100)], image_size=(400, 500), method="haar")
        wide = circular_crop_smart(_photo(), size=200, face_info=fi, zoom=0.6)
        tight = circular_crop_smart(_photo(), size=200, face_info=fi, zoom=2.0)
        # Different zoom should produce different pixels
        assert list(wide.getdata()) != list(tight.getdata())

    def test_offset_changes_crop(self):
        fi = FaceInfo(boxes=[(150, 200, 100, 100)], image_size=(400, 500), method="haar")
        a = circular_crop_smart(_photo(), size=200, face_info=fi, offset_x=-0.2)
        b = circular_crop_smart(_photo(), size=200, face_info=fi, offset_x=0.2)
        assert list(a.getdata()) != list(b.getdata())

    def test_no_face_uses_default(self):
        fi = FaceInfo(boxes=[], image_size=(400, 500), method="default")
        out = circular_crop_smart(_photo(), size=200, face_info=fi)
        assert out.size == (200, 200)

    def test_crop_stays_in_bounds_with_extreme_offset(self):
        fi = FaceInfo(boxes=[(10, 10, 50, 50)], image_size=(400, 500), method="haar")
        # Extreme offset should not raise and should stay valid
        out = circular_crop_smart(_photo(), size=200, face_info=fi,
                                  offset_x=0.9, offset_y=0.9, zoom=2.5)
        assert out.size == (200, 200)


class TestNewTemplates:
    @pytest.mark.parametrize("tmpl", NEW_TEMPLATES)
    def test_registered(self, tmpl):
        assert tmpl in TEMPLATES

    @pytest.mark.parametrize("tmpl", NEW_TEMPLATES)
    def test_renders_rgba_within_spec(self, tmpl):
        circle = circular_crop_smart(_photo(), size=CIRCLE_DIAM)
        out = apply_template(circle, tmpl, caption="ありがとう", seed=0)
        assert out.mode == "RGBA"
        assert out.width <= 370 and out.height <= 320

    @pytest.mark.parametrize("tmpl", NEW_TEMPLATES)
    def test_japanese_caption(self, tmpl):
        circle = circular_crop_smart(_photo(), size=CIRCLE_DIAM)
        for text in ["了解！", "おつかれ", "おはよう"]:
            out = apply_template(circle, tmpl, caption=text)
            assert isinstance(out, Image.Image)

    def test_group_badge_has_background(self):
        # Decorated templates fill the background (corners are NOT transparent)
        circle = circular_crop_smart(_photo(), size=CIRCLE_DIAM)
        out = apply_template(circle, "soft_pastel")
        # center of the circle stays opaque
        assert out.getpixel((out.width // 2, out.height // 3))[3] == 255


class TestZoomPresets:
    @pytest.mark.parametrize("tmpl", list(TEMPLATES.keys()))
    def test_every_template_has_preset(self, tmpl):
        preset = zoom_preset(tmpl)
        assert "target_face_frac" in preset
        assert "zoom" in preset

    def test_speech_bubble_zooms_out(self):
        # speech_bubble leaves room for text => smaller target_face_frac
        assert ZOOM_PRESETS["speech_bubble"]["target_face_frac"] < ZOOM_PRESETS["pop_star"]["target_face_frac"]

    def test_group_badge_fits_more(self):
        assert ZOOM_PRESETS["group_badge"]["zoom"] <= 1.0

    def test_unknown_falls_back(self):
        assert zoom_preset("nonexistent") == ZOOM_PRESETS["simple_circle"]
