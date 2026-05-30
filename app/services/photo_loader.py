"""Load adopted photos from photo-selector output."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any


def load_adopted_photos(
    manifest_path: str | Path,
    selected_dir: str | Path,
) -> list[dict[str, Any]]:
    """
    Return list of adopted photo metadata dicts, sorted by score descending.

    Tries the photo-selector manifest first (richer metadata).
    Falls back to scanning the selected/ directory.

    Each dict has: path, width, height, score, caption, tags.
    """
    manifest_path = Path(manifest_path)
    selected_dir = Path(selected_dir)

    if manifest_path.exists():
        return _from_manifest(manifest_path)
    if selected_dir.exists():
        return _from_directory(selected_dir)
    return []


def _from_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    with manifest_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    photos: list[dict[str, Any]] = []
    for item in data.get("photos", []):
        if not item.get("selected"):
            continue
        analysis = item.get("analysis") or {}
        # photo-selector stores score under overall_score or score
        score = analysis.get("overall_score") or analysis.get("score") or 0
        photos.append(
            {
                "path": item["path"],
                "width": item.get("width", 0),
                "height": item.get("height", 0),
                "score": float(score),
                "caption": analysis.get("caption", ""),
                "tags": analysis.get("tags", []),
            }
        )

    return sorted(photos, key=lambda p: p["score"], reverse=True)


def _from_directory(selected_dir: Path) -> list[dict[str, Any]]:
    _EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
    photos: list[dict[str, Any]] = []
    for f in sorted(selected_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in _EXTS:
            photos.append(
                {
                    "path": str(f),
                    "width": 0,
                    "height": 0,
                    "score": 0.0,
                    "caption": "",
                    "tags": [],
                }
            )
    return photos
