"""Tests for CharacterProcessor (circular crop + template pipeline)."""

from __future__ import annotations
import pytest
from PIL import Image

from app.services.character_processor import CharacterProcessor, StepImages, STYLES
from app.services.stamp_templates import TEMPLATES


def _photo(w: int = 200, h: int = 260) -> Image.Image:
    return Image.new("RGB", (w, h), (180, 140, 110))


class TestCharacterProcessor:
    def test_process_returns_step_images(self):
        proc = CharacterProcessor()
        steps = proc.process(_photo())
        assert isinstance(steps, StepImages)
        assert isinstance(steps.original, Image.Image)
        assert isinstance(steps.styled, Image.Image)
        assert isinstance(steps.stamp, Image.Image)

    def test_styled_is_circle(self):
        proc = CharacterProcessor()
        steps = proc.process(_photo(300, 400))
        # styled = circle crop → square, RGBA, transparent corners
        assert steps.styled.mode == "RGBA"
        assert steps.styled.width == steps.styled.height
        assert steps.styled.getpixel((0, 0))[3] == 0

    def test_stamp_is_rgba(self):
        proc = CharacterProcessor()
        steps = proc.process(_photo())
        assert steps.stamp.mode == "RGBA"

    def test_stamp_fits_line_spec(self):
        proc = CharacterProcessor()
        steps = proc.process(_photo())
        assert steps.stamp.width <= 370
        assert steps.stamp.height <= 320

    @pytest.mark.parametrize("tmpl", list(TEMPLATES.keys()))
    def test_all_templates_no_error(self, tmpl):
        proc = CharacterProcessor(style=tmpl)
        steps = proc.process(_photo(), caption="テスト")
        assert isinstance(steps.stamp, Image.Image)

    @pytest.mark.parametrize("text", ["ありがとう", "了解", "おつかれさま"])
    def test_japanese_caption_no_error(self, text):
        proc = CharacterProcessor()
        steps = proc.process(_photo(), caption=text, text_style="bubble")
        assert isinstance(steps.stamp, Image.Image)

    def test_invalid_style_falls_back_to_simple(self):
        proc = CharacterProcessor(style="nonexistent")
        assert proc.template == "simple_circle"

    @pytest.mark.parametrize("text_style", ["bubble", "pop", "shadow", "outline_white", "outline_black"])
    def test_all_text_styles(self, text_style):
        proc = CharacterProcessor()
        steps = proc.process(_photo(), caption="おやすみ", text_style=text_style)
        assert isinstance(steps.stamp, Image.Image)

    def test_styles_dict_matches_templates(self):
        """STYLES (backward compat alias) should equal TEMPLATES."""
        assert STYLES == TEMPLATES
