"""Prepare generated icons for manual ChatGPT image editing."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


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

VARIANTS = tuple(SOURCE_FILENAMES.keys())
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


@dataclass(frozen=True)
class ChatGptReadyResult:
    output_dir: str
    prompt_path: str
    source_paths: list[str]
    clipboard_copied: bool


@dataclass(frozen=True)
class FinishedVariant:
    key: str
    finished_path: str
    preview_path: str


@dataclass(frozen=True)
class FinishedImportResult:
    output_dir: str
    variants: list[FinishedVariant]


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


def chatgpt_ready_dir(output_root: Path) -> Path:
    return output_root / "chatgpt-ready"


def get_finished_variants(output_root: Path) -> list[FinishedVariant]:
    output_dir = chatgpt_ready_dir(output_root)
    variants: list[FinishedVariant] = []
    for key in VARIANTS:
        finished = output_dir / f"icon_{key}_finished.png"
        preview = output_dir / f"icon_{key}_circle_preview.png"
        if finished.exists():
            if not preview.exists():
                _write_circle_preview(finished, preview)
            variants.append(FinishedVariant(key=key, finished_path=str(finished), preview_path=str(preview)))
    return variants


def import_finished_images(output_root: Path) -> FinishedImportResult:
    """Normalize user-saved ChatGPT outputs into finished image files."""
    output_dir = chatgpt_ready_dir(output_root)
    if not output_dir.is_dir():
        raise RuntimeError("output/chatgpt-ready が見つかりません。先にChatGPT仕上げ用に出力してください。")

    variants: list[FinishedVariant] = []
    for key in VARIANTS:
        candidate = _find_finished_candidate(output_dir, key)
        if candidate is None:
            continue
        finished = output_dir / f"icon_{key}_finished.png"
        _normalize_png(candidate, finished)
        preview = output_dir / f"icon_{key}_circle_preview.png"
        _write_circle_preview(finished, preview)
        variants.append(FinishedVariant(key=key, finished_path=str(finished), preview_path=str(preview)))

    if not variants:
        raise RuntimeError("natural / storybook / premium の仕上げ画像が見つかりませんでした。ファイル名に案名を含めて保存してください。")

    return FinishedImportResult(output_dir=str(output_dir), variants=variants)


def save_final_icon(output_root: Path, variant: str) -> str:
    """Save the selected finished image as final_icon.png."""
    if variant not in VARIANTS:
        raise RuntimeError("不明な仕上げ案です。")
    output_dir = chatgpt_ready_dir(output_root)
    finished = output_dir / f"icon_{variant}_finished.png"
    if not finished.is_file():
        raise RuntimeError(f"{variant} の仕上げ画像が見つかりません。先に取り込んでください。")

    final_path = output_dir / "final_icon.png"
    shutil.copy2(finished, final_path)
    _write_circle_preview(final_path, output_dir / "final_icon_circle_preview.png")
    return str(final_path)


def _find_finished_candidate(output_dir: Path, variant: str) -> Path | None:
    preferred = [
        output_dir / f"icon_{variant}_finished.png",
        output_dir / f"{variant}_finished.png",
        output_dir / f"finished_{variant}.png",
        output_dir / f"{variant}.png",
    ]
    for path in preferred:
        if path.is_file():
            return path

    matches = []
    for path in output_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
            continue
        name = path.name.lower()
        if variant not in name:
            continue
        if any(skip in name for skip in ("source", "circle_preview", "final_icon")):
            continue
        matches.append(path)
    return sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[0] if matches else None


def _normalize_png(src: Path, dest: Path) -> None:
    if src.resolve() == dest.resolve():
        return
    with Image.open(src) as img:
        img.convert("RGBA").save(dest, "PNG")


def _write_circle_preview(src: Path, dest: Path, size: int = 512) -> None:
    with Image.open(src) as img:
        square = ImageOps.fit(img.convert("RGBA"), (size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    preview = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    preview.paste(square, (0, 0), mask)
    dest.parent.mkdir(parents=True, exist_ok=True)
    preview.save(dest, "PNG")


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
