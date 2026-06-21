from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.services.ai_finish import VARIANTS, _build_prompt, finish_icon_with_ai


def test_ai_finish_requires_api_key(monkeypatch, tmp_path):
    src = tmp_path / "main.png"
    Image.new("RGBA", (240, 240), (255, 255, 255, 255)).save(src, "PNG")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        finish_icon_with_ai(src, tmp_path / "ai_finish")


def test_ai_finish_prompt_preserves_child_details():
    prompt = _build_prompt("natural light")

    assert "do not change the child's face" in prompt
    assert "facial expression" in prompt
    assert "hairstyle" in prompt
    assert "clothing" in prompt
    assert "1024x1024 PNG" in prompt


def test_ai_finish_variants_are_required_three_patterns():
    assert list(VARIANTS) == ["natural", "storybook", "premium"]
