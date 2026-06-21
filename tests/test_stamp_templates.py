"""Tests for stamp template implementations."""

from __future__ import annotations
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.services.circle_crop import circular_crop
from app.services.stamp_templates import (
    TEMPLATES,
    apply_template,
    auto_select_template,
)
from app.services.stamp_generator import StampItemSpec, generate_stamp_set

STICKER_MAX_W = 370
STICKER_MAX_H = 320


def _circle(size: int = 220) -> Image.Image:
    photo = Image.new("RGB", (300, 400), (200, 160, 120))
    return circular_crop(photo, size=size)


class TestApplyTemplate:
    @pytest.mark.parametrize("tmpl", list(TEMPLATES.keys()))
    def test_returns_rgba(self, tmpl):
        result = apply_template(_circle(), tmpl)
        assert result.mode == "RGBA"

    @pytest.mark.parametrize("tmpl", list(TEMPLATES.keys()))
    def test_fits_line_spec(self, tmpl):
        result = apply_template(_circle(), tmpl)
        assert result.width <= STICKER_MAX_W
        assert result.height <= STICKER_MAX_H

    @pytest.mark.parametrize("tmpl", list(TEMPLATES.keys()))
    def test_with_japanese_caption(self, tmpl):
        for text in ["ありがとう", "了解", "おつかれさま"]:
            result = apply_template(_circle(), tmpl, caption=text, text_style="bubble")
            assert isinstance(result, Image.Image)

    @pytest.mark.parametrize("tmpl", list(TEMPLATES.keys()))
    def test_templates_differ(self, tmpl):
        """Each template should produce a visually distinct image."""
        circle = _circle()
        result = apply_template(circle, tmpl, caption="テスト", seed=0)
        simple = apply_template(circle, "simple_circle", caption="テスト", seed=0)
        if tmpl != "simple_circle":
            assert list(result.getdata()) != list(simple.getdata()), \
                f"{tmpl} produced the same pixels as simple_circle"

    def test_unknown_template_falls_back(self):
        """Unknown template should not raise; apply_template uses simple_circle fallback."""
        result = apply_template(_circle(), "nonexistent_tmpl")
        assert isinstance(result, Image.Image)

    @pytest.mark.parametrize("text_style", ["bubble", "pop", "shadow", "outline_white", "outline_black"])
    def test_all_text_styles(self, text_style):
        result = apply_template(_circle(), "simple_circle",
                                caption="おはよう", text_style=text_style)
        assert isinstance(result, Image.Image)

    def test_no_caption(self):
        result = apply_template(_circle(), "pop_star", caption="")
        assert isinstance(result, Image.Image)

    def test_long_caption_fits(self):
        """A long Japanese caption should be wrapped / truncated without overflow."""
        long_text = "ありがとうございますとてもうれしいです"
        result = apply_template(_circle(), "simple_circle", caption=long_text)
        assert result.width <= STICKER_MAX_W

    def test_seed_reproducible(self):
        """Same seed should produce identical output."""
        c = _circle()
        r1 = apply_template(c, "birthday", caption="お祝い", seed=123)
        r2 = apply_template(c, "birthday", caption="お祝い", seed=123)
        assert list(r1.getdata()) == list(r2.getdata())

    def test_speech_bubble_contains_transparent_area(self):
        """speech_bubble template should have transparent pixels (no full-opaque background)."""
        result = apply_template(_circle(), "speech_bubble")
        arr = list(result.getdata())
        transparent = sum(1 for _, _, _, a in arr if a == 0)
        assert transparent > 100, "speech_bubble should have transparent corners"

    def test_transparent_corners_on_simple_circle(self):
        result = apply_template(_circle(), "simple_circle")
        # Top-left corner pixel must be fully transparent
        assert result.getpixel((0, 0))[3] == 0


class TestAutoSelectTemplate:
    def test_no_metadata_returns_simple(self):
        assert auto_select_template(None) == "simple_circle"

    def test_empty_metadata_returns_simple(self):
        assert auto_select_template({}) == "simple_circle"

    def test_birthday_tag_returns_birthday(self):
        meta = {"analysis": {"tags": ["birthday", "cake"]}}
        assert auto_select_template(meta) == "birthday"

    def test_sakura_tag_returns_sakura(self):
        meta = {"analysis": {"tags": ["sakura", "spring"]}}
        assert auto_select_template(meta) == "seasonal_sakura"

    def test_smile_tag_returns_pop_or_heart(self):
        meta = {"analysis": {"tags": ["smile", "happy"]}}
        result = auto_select_template(meta)
        assert result in ("pop_star", "heart")

    def test_group_tag_returns_group_badge(self):
        meta = {"analysis": {"tags": ["group", "family"]}}
        assert auto_select_template(meta) == "group_badge"

    def test_caption_keyword(self):
        meta = {"analysis": {"caption": "誕生日パーティー", "tags": []}}
        assert auto_select_template(meta) == "birthday"


class TestGenerateStampSetIntegration:
    """Integration tests using all templates end-to-end."""

    def _make_specs(self, photo: Path, style: str) -> list[StampItemSpec]:
        return [
            StampItemSpec(position=i, photo_path=str(photo), caption=cap, style=style)
            for i, cap in enumerate(
                ["ありがとう", "了解", "おつかれ", "OK", "ごめん",
                 "いってきます", "おやすみ", "最高"], start=1
            )
        ]

    @pytest.fixture
    def sample_photo(self, tmp_path):
        img = Image.new("RGB", (300, 400), (190, 150, 110))
        p = tmp_path / "photo.jpg"
        img.save(p, "JPEG")
        return p

    @pytest.mark.parametrize("tmpl", list(TEMPLATES.keys()))
    def test_all_templates_8_succeed(self, tmp_path, sample_photo, tmpl):
        specs = self._make_specs(sample_photo, tmpl)
        summary = generate_stamp_set(specs, tmp_path / tmpl)
        assert summary.success_count == 8, \
            f"{tmpl}: failed={summary.failed_positions}"

    def test_zip_contains_required_files(self, tmp_path, sample_photo):
        specs = self._make_specs(sample_photo, "simple_circle")
        summary = generate_stamp_set(specs, tmp_path / "out")
        with zipfile.ZipFile(summary.zip_path) as zf:
            names = set(zf.namelist())
        assert "main.png" in names
        assert "tab.png" in names
        for i in range(1, 9):
            assert f"stamp_{i:02d}.png" in names

    def test_sticker_is_transparent_png(self, tmp_path, sample_photo):
        specs = self._make_specs(sample_photo, "simple_circle")
        summary = generate_stamp_set(specs, tmp_path / "out")
        img = Image.open(summary.results[0].sticker_path)
        assert img.mode == "RGBA"
        # Corners should be transparent for circle stamps
        assert img.getpixel((0, 0))[3] == 0

    def test_preview_images_created(self, tmp_path, sample_photo):
        specs = self._make_specs(sample_photo, "pop_star")
        summary = generate_stamp_set(specs, tmp_path / "out")
        for r in summary.results:
            if r.success:
                assert r.preview_path and Path(r.preview_path).exists()
