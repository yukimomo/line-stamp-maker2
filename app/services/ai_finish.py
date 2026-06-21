"""AI finishing for generated LINE profile icons."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path


VARIANTS = {
    "natural": "natural light, softly blurred background, warm photorealistic profile photo style",
    "storybook": "storybook illustration style, gentle hand-painted look, soft colors",
    "premium": "Nordic minimal design, refined premium feel, clean composition",
}


@dataclass(frozen=True)
class AiFinishResult:
    variant: str
    path: str


def finish_icon_with_ai(input_path: Path, output_dir: Path) -> list[AiFinishResult]:
    """Create three 1024x1024 PNG profile-icon variants from a generated icon."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Set it before running AI仕上げ.")
    if not input_path.is_file():
        raise RuntimeError("AI仕上げの入力画像が見つかりません。先にアイコンを生成してください。")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai package is not installed. Run `pip install -e .` again.") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    client = OpenAI(api_key=api_key)

    results: list[AiFinishResult] = []
    for variant, style in VARIANTS.items():
        prompt = _build_prompt(style)
        with input_path.open("rb") as image_file:
            response = client.images.edit(
                model="gpt-image-2",
                image=image_file,
                prompt=prompt,
                size="1024x1024",
                quality="medium",
                output_format="png",
            )
        image_base64 = response.data[0].b64_json
        if not image_base64:
            raise RuntimeError(f"{variant} のAI仕上げ結果が空でした。")
        out_path = output_dir / f"{variant}.png"
        out_path.write_bytes(base64.b64decode(image_base64))
        results.append(AiFinishResult(variant=variant, path=str(out_path)))

    return results


def _build_prompt(style: str) -> str:
    return (
        "Edit the provided LINE profile icon into a stylish square profile image. "
        "Preserve the child exactly: do not change the child's face, facial expression, "
        "hairstyle, hair color, clothing, identity, age, or pose. Keep the main subject "
        "recognizable and child-safe. Improve only the background, lighting, framing, "
        "color grading, and overall finish for a polished LINE profile icon. "
        f"Style direction: {style}. "
        "Output a clean 1024x1024 PNG composition."
    )
