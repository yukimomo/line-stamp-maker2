"""Tests for stamp_generator service (fallback path, no line-stamp-maker)."""

from __future__ import annotations
import zipfile
from pathlib import Path

import pytest
from PIL import Image

import app.services.stamp_generator as sg
from app.services.stamp_generator import (
    GenerationResult,
    GenerationSummary,
    StampItemSpec,
    _add_caption_pil,
    _build_zip,
    _save_fitted,
    generate_stamp_set,
)


# Force fallback (pure-Pillow) path for all tests in this module
@pytest.fixture(autouse=True)
def force_fallback(monkeypatch):
    monkeypatch.setattr(sg, "_HAS_LSM", False)


# ---------------------------------------------------------------------------
# Unit: helper functions
# ---------------------------------------------------------------------------

class TestAddCaptionPil:
    def test_returns_image(self):
        img = Image.new("RGBA", (200, 200), (255, 0, 0, 255))
        result = _add_caption_pil(img, "テスト")
        assert isinstance(result, Image.Image)
        assert result.mode == "RGBA"

    def test_same_size(self):
        img = Image.new("RGBA", (300, 250), (0, 255, 0, 255))
        result = _add_caption_pil(img, "OK")
        assert result.size == (300, 250)

    def test_empty_caption_not_called(self):
        # Caller responsibility: only call when caption is truthy.
        # Passing empty string should still return valid image.
        img = Image.new("RGBA", (100, 100), (0, 0, 255, 255))
        result = _add_caption_pil(img, "")
        assert isinstance(result, Image.Image)


class TestSaveFitted:
    def test_creates_file(self, tmp_path, make_png):
        src = make_png("src.png", (400, 300))
        img = Image.open(src).convert("RGBA")
        out = tmp_path / "main.png"
        _save_fitted(img, out, 240, 240)
        assert out.exists()

    def test_exact_canvas_size(self, tmp_path, make_png):
        src = make_png("src.png", (400, 300))
        img = Image.open(src).convert("RGBA")
        out = tmp_path / "tab.png"
        _save_fitted(img, out, 96, 74)
        saved = Image.open(out)
        assert saved.size == (96, 74)


class TestBuildZip:
    def _make_sticker(self, stickers_dir: Path, pos: int) -> GenerationResult:
        p = stickers_dir / f"stamp_{pos:02d}.png"
        Image.new("RGBA", (100, 100), (255, 0, 0, 255)).save(p, "PNG")
        return GenerationResult(position=pos, success=True, sticker_path=str(p))

    def test_zip_created(self, tmp_path):
        stickers_dir = tmp_path / "stickers"
        stickers_dir.mkdir()
        results = [self._make_sticker(stickers_dir, i) for i in range(1, 9)]
        # add main/tab
        Image.new("RGBA", (240, 240)).save(tmp_path / "main.png", "PNG")
        Image.new("RGBA", (96, 74)).save(tmp_path / "tab.png", "PNG")

        zip_path = _build_zip(tmp_path, stickers_dir, results)
        assert zip_path.exists()

    def test_zip_contains_stickers_and_meta(self, tmp_path):
        stickers_dir = tmp_path / "stickers"
        stickers_dir.mkdir()
        results = [self._make_sticker(stickers_dir, i) for i in range(1, 9)]
        Image.new("RGBA", (240, 240)).save(tmp_path / "main.png", "PNG")
        Image.new("RGBA", (96, 74)).save(tmp_path / "tab.png", "PNG")

        zip_path = _build_zip(tmp_path, stickers_dir, results)
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
        assert "main.png" in names
        assert "tab.png" in names
        for i in range(1, 9):
            assert f"stamp_{i:02d}.png" in names

    def test_failed_items_not_in_zip(self, tmp_path):
        stickers_dir = tmp_path / "stickers"
        stickers_dir.mkdir()
        results = [self._make_sticker(stickers_dir, i) for i in range(1, 8)]
        results.append(GenerationResult(position=8, success=False, error="oops"))
        Image.new("RGBA", (240, 240)).save(tmp_path / "main.png", "PNG")
        Image.new("RGBA", (96, 74)).save(tmp_path / "tab.png", "PNG")

        zip_path = _build_zip(tmp_path, stickers_dir, results)
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        assert "stamp_08.png" not in names


# ---------------------------------------------------------------------------
# Integration: generate_stamp_set (fallback path)
# ---------------------------------------------------------------------------

class TestGenerateStampSet:
    def _make_8_specs(self, photo: Path) -> list[StampItemSpec]:
        return [
            StampItemSpec(position=i, photo_path=str(photo), caption=f"テスト{i}")
            for i in range(1, 9)
        ]

    def test_all_succeed(self, tmp_path, make_png):
        photo = make_png("photo.png", (300, 400))
        specs = self._make_8_specs(photo)
        summary = generate_stamp_set(specs, tmp_path / "out")

        assert summary.success_count == 8
        assert summary.failed_positions == []

    def test_sticker_files_created(self, tmp_path, make_png):
        photo = make_png("photo.png", (300, 400))
        specs = self._make_8_specs(photo)
        summary = generate_stamp_set(specs, tmp_path / "out")

        out = Path(summary.set_output_dir)
        for i in range(1, 9):
            assert (out / "stickers" / f"stamp_{i:02d}.png").exists()

    def test_main_and_tab_created(self, tmp_path, make_png):
        photo = make_png("photo.png", (300, 400))
        specs = self._make_8_specs(photo)
        summary = generate_stamp_set(specs, tmp_path / "out")

        out = Path(summary.set_output_dir)
        assert (out / "main.png").exists()
        assert (out / "tab.png").exists()

    def test_zip_created(self, tmp_path, make_png):
        photo = make_png("photo.png", (300, 400))
        specs = self._make_8_specs(photo)
        summary = generate_stamp_set(specs, tmp_path / "out")

        assert summary.zip_path is not None
        assert Path(summary.zip_path).exists()

    def test_missing_photo_recorded_as_error(self, tmp_path, make_png):
        photo = make_png("photo.png")
        specs = self._make_8_specs(photo)
        # Replace slot 5 with a non-existent path
        specs[4] = StampItemSpec(position=5, photo_path="/no/such/file.png", caption="?")

        summary = generate_stamp_set(specs, tmp_path / "out")
        assert 5 in summary.failed_positions
        assert summary.success_count == 7


# ---------------------------------------------------------------------------
# GenerationSummary properties
# ---------------------------------------------------------------------------

class TestGenerationSummary:
    def _summary(self, successes: list[int], failures: list[int]) -> GenerationSummary:
        results = (
            [GenerationResult(p, success=True) for p in successes]
            + [GenerationResult(p, success=False, error="err") for p in failures]
        )
        return GenerationSummary(set_output_dir="/tmp/x", zip_path=None, results=results)

    def test_success_count(self):
        s = self._summary([1, 2, 3], [4])
        assert s.success_count == 3

    def test_failed_positions(self):
        s = self._summary([1, 3, 5, 7], [2, 4, 6, 8])
        assert sorted(s.failed_positions) == [2, 4, 6, 8]

    def test_all_ok(self):
        s = self._summary(list(range(1, 9)), [])
        assert s.success_count == 8
        assert s.failed_positions == []
