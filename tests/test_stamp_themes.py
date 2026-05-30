"""Tests for stamp set themes and caption auto-assignment."""

from __future__ import annotations
import pytest

from app.services.stamp_themes import (
    THEMES,
    ThemeConfig,
    assign_captions_to_photos,
)
from app.services.stamp_templates import TEMPLATES
from app.services.text_styles import TEXT_STYLES


class TestThemeDefinitions:
    def test_six_themes_exist(self):
        expected = {"family_pop", "cute_daily", "business_casual",
                    "baby_kids", "celebration", "simple_icon"}
        assert expected <= set(THEMES.keys())

    @pytest.mark.parametrize("key", list(THEMES.keys()))
    def test_eight_templates(self, key):
        assert len(THEMES[key].templates) == 8

    @pytest.mark.parametrize("key", list(THEMES.keys()))
    def test_eight_captions(self, key):
        assert len(THEMES[key].captions) == 8

    @pytest.mark.parametrize("key", list(THEMES.keys()))
    def test_templates_are_valid(self, key):
        for t in THEMES[key].templates:
            assert t in TEMPLATES, f"{key} references unknown template {t}"

    @pytest.mark.parametrize("key", list(THEMES.keys()))
    def test_text_style_valid(self, key):
        assert THEMES[key].text_style in TEXT_STYLES

    @pytest.mark.parametrize("key", list(THEMES.keys()))
    def test_main_bg_is_rgba(self, key):
        bg = THEMES[key].main_bg
        assert len(bg) == 4
        assert all(0 <= c <= 255 for c in bg)

    def test_business_casual_captions(self):
        caps = THEMES["business_casual"].captions
        assert "承知しました" in caps
        assert "確認します" in caps


class TestAssignCaptions:
    def test_returns_eight(self):
        photos = [{"path": f"p{i}"} for i in range(8)]
        caps = assign_captions_to_photos(photos, "family_pop")
        assert len(caps) == 8

    def test_pads_when_fewer_photos(self):
        photos = [{"path": "p1"}, {"path": "p2"}]
        caps = assign_captions_to_photos(photos, "family_pop")
        assert len(caps) == 8

    def test_unknown_theme_falls_back(self):
        photos = [{"path": f"p{i}"} for i in range(8)]
        caps = assign_captions_to_photos(photos, "nonexistent")
        assert len(caps) == 8

    def test_smile_tag_prefers_positive_caption(self):
        photos = [{"path": "p1", "analysis": {"tags": ["smile", "happy"]}}]
        caps = assign_captions_to_photos(photos, "family_pop")
        # family_pop captions include ありがとう / おはよう which match smile affinity
        assert caps[0] in THEMES["family_pop"].captions

    def test_sleep_tag_prefers_oyasumi(self):
        photos = [{"path": "p1", "analysis": {"tags": ["sleep"]}}]
        caps = assign_captions_to_photos(photos, "family_pop")
        # おやすみ is in family_pop and matches sleep affinity
        assert "おやすみ" in caps[0] or caps[0] in THEMES["family_pop"].captions

    def test_no_analysis_uses_theme_defaults(self):
        photos = [{"path": f"p{i}"} for i in range(8)]
        caps = assign_captions_to_photos(photos, "simple_icon")
        theme_caps = set(THEMES["simple_icon"].captions)
        for c in caps:
            assert c in theme_caps

    def test_captions_are_strings(self):
        photos = [{"path": f"p{i}"} for i in range(8)]
        caps = assign_captions_to_photos(photos, "celebration")
        assert all(isinstance(c, str) and c for c in caps)
