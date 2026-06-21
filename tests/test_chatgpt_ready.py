from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.services import chatgpt_ready


def test_prepare_chatgpt_ready_writes_sources_and_prompt(monkeypatch, tmp_path):
    source = tmp_path / "main.png"
    Image.new("RGBA", (240, 240), (80, 120, 160, 255)).save(source, "PNG")
    monkeypatch.setattr(chatgpt_ready, "copy_prompt_to_clipboard", lambda prompt: True)

    result = chatgpt_ready.prepare_chatgpt_ready(source, tmp_path / "output")

    out = Path(result.output_dir)
    assert out == tmp_path / "output" / "chatgpt-ready"
    assert Path(result.prompt_path).read_text(encoding="utf-8") == chatgpt_ready.CHATGPT_READY_PROMPT
    assert result.clipboard_copied is True
    assert sorted(Path(p).name for p in result.source_paths) == [
        "icon_natural_source.png",
        "icon_premium_source.png",
        "icon_storybook_source.png",
    ]
    for path in result.source_paths:
        assert Image.open(path).size == (240, 240)


def test_prepare_chatgpt_ready_requires_generated_icon(tmp_path):
    with pytest.raises(RuntimeError, match="入力画像"):
        chatgpt_ready.prepare_chatgpt_ready(tmp_path / "missing.png", tmp_path / "output")


def test_prompt_contains_requested_chatgpt_instructions():
    prompt = chatgpt_ready.CHATGPT_READY_PROMPT

    assert "子供の顔・表情・髪型・服装は変更しない" in prompt
    assert "背景だけをおしゃれに整える" in prompt
    assert "自然光、やわらかい背景ボケ" in prompt
    assert "過度なアニメ化、別人化、顔の補正は禁止" in prompt
    assert "1. natural" in prompt
    assert "2. storybook" in prompt
    assert "3. premium" in prompt
