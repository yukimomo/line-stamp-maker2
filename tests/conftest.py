"""Shared pytest fixtures."""

from __future__ import annotations
import json
from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def tmp_output(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def make_png(tmp_path: Path):
    """Factory: create an RGBA PNG at tmp_path/<name> with given size."""
    def _make(name: str = "test.png", size: tuple[int, int] = (200, 200)) -> Path:
        img = Image.new("RGBA", size, (80, 160, 200, 255))
        path = tmp_path / name
        img.save(path, "PNG")
        return path
    return _make


@pytest.fixture
def manifest_file(tmp_path: Path) -> Path:
    """Write a minimal photo-selector manifest.photos.json."""
    photos = [
        {
            "path": str(tmp_path / "photo_a.jpg"),
            "width": 800,
            "height": 600,
            "hash": "aabbcc",
            "selected": True,
            "analysis": {
                "caption": "子どもが遊んでいる",
                "tags": ["child", "outdoor"],
                "overall_score": 0.9,
            },
        },
        {
            "path": str(tmp_path / "photo_b.jpg"),
            "width": 1200,
            "height": 900,
            "hash": "ddeeff",
            "selected": False,  # not selected → should be excluded
            "analysis": {"caption": "犬", "tags": ["dog"], "overall_score": 0.7},
        },
        {
            "path": str(tmp_path / "photo_c.heic"),
            "width": 3000,
            "height": 4000,
            "hash": "001122",
            "selected": True,
            "analysis": {"score": 0.85},  # uses "score" key instead of "overall_score"
        },
    ]
    data = {"photos": photos}
    path = tmp_path / "manifest.photos.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def flask_app(tmp_path: Path):
    """Minimal Flask test app with in-memory-like SQLite."""
    from app import create_app

    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "test_stamps.db"),
            "OUTPUT_DIR": str(tmp_path / "output"),
            "PHOTO_SELECTOR_MANIFEST": str(tmp_path / "missing.json"),
            "PHOTO_SELECTOR_SELECTED_DIR": str(tmp_path / "missing_dir"),
        }
    )
    return app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()
