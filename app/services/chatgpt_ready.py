"""Prepare generated icons for manual ChatGPT image editing."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


CHATGPT_READY_PROMPT = """子供の顔・表情・髪型・服装は変更しない。
LINEプロフィールアイコン向けに、背景だけをおしゃれに整える。
自然光、やわらかい背景ボケ、明るく温かい雰囲気。
丸型アイコンで顔が目立つ構図。
過度なアニメ化、別人化、顔の補正は禁止。
3案作成してください:
1. natural
2. storybook
3. premium
"""

SOURCE_FILENAMES = {
    "natural": "icon_natural_source.png",
    "storybook": "icon_storybook_source.png",
    "premium": "icon_premium_source.png",
}


@dataclass(frozen=True)
class ChatGptReadyResult:
    output_dir: str
    prompt_path: str
    source_paths: list[str]
    clipboard_copied: bool


def prepare_chatgpt_ready(source_icon: Path, output_root: Path) -> ChatGptReadyResult:
    """Copy the generated icon and write a prompt for ChatGPT image editing."""
    if not source_icon.is_file():
        raise RuntimeError("ChatGPT仕上げ用の入力画像が見つかりません。先にアイコンを生成してください。")

    output_dir = output_root / "chatgpt-ready"
    output_dir.mkdir(parents=True, exist_ok=True)

    source_paths: list[str] = []
    for filename in SOURCE_FILENAMES.values():
        dest = output_dir / filename
        shutil.copy2(source_icon, dest)
        source_paths.append(str(dest))

    prompt_path = output_dir / "prompt.txt"
    prompt_path.write_text(CHATGPT_READY_PROMPT, encoding="utf-8")

    return ChatGptReadyResult(
        output_dir=str(output_dir),
        prompt_path=str(prompt_path),
        source_paths=source_paths,
        clipboard_copied=copy_prompt_to_clipboard(CHATGPT_READY_PROMPT),
    )


def copy_prompt_to_clipboard(prompt: str) -> bool:
    """Best-effort clipboard copy without adding a required dependency."""
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(prompt)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False


def open_folder(path: Path) -> None:
    """Open a folder in the user's OS file manager."""
    if not path.is_dir():
        raise RuntimeError("出力フォルダがまだありません。先にChatGPT仕上げ用に出力してください。")

    if sys.platform.startswith("win"):
        import os

        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
        return
    subprocess.Popen(["xdg-open", str(path)])
