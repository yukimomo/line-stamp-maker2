"""Tests for the LINE spec validator."""

from __future__ import annotations
from pathlib import Path

import pytest
from PIL import Image

from app.services.validator import (
    MAX_FILE_BYTES,
    MAIN_H,
    MAIN_W,
    REQUIRED_COUNT,
    STICKER_MAX_H,
    STICKER_MAX_W,
    TAB_H,
    TAB_W,
    validate_stamp_set,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _write_png(path: Path, size: tuple[int, int], mode: str = "RGBA") -> None:
    Image.new(mode, size, (100, 150, 200, 255) if mode == "RGBA" else (100, 150, 200)).save(path, "PNG")


def _build_valid_set(output_dir: Path) -> Path:
    """Create a complete valid stamp set and return output_dir."""
    stickers = output_dir / "stickers"
    stickers.mkdir(parents=True)
    for i in range(1, 9):
        _write_png(stickers / f"stamp_{i:02d}.png", (STICKER_MAX_W, STICKER_MAX_H))
    _write_png(output_dir / "main.png", (MAIN_W, MAIN_H))
    _write_png(output_dir / "tab.png", (TAB_W, TAB_H))
    return output_dir


# ---------------------------------------------------------------------------
# Tests: valid set
# ---------------------------------------------------------------------------

class TestValidSet:
    def test_is_valid(self, tmp_path):
        _build_valid_set(tmp_path)
        report = validate_stamp_set(tmp_path)
        assert report.is_valid
        assert report.errors == []

    def test_no_warnings_when_rgba(self, tmp_path):
        _build_valid_set(tmp_path)
        report = validate_stamp_set(tmp_path)
        assert report.warnings == []


# ---------------------------------------------------------------------------
# Tests: stamp count
# ---------------------------------------------------------------------------

class TestStampCount:
    def test_fewer_than_8_is_error(self, tmp_path):
        stickers = tmp_path / "stickers"
        stickers.mkdir()
        for i in range(1, 5):  # only 4
            _write_png(stickers / f"stamp_{i:02d}.png", (300, 280))
        _write_png(tmp_path / "main.png", (MAIN_W, MAIN_H))
        _write_png(tmp_path / "tab.png", (TAB_W, TAB_H))

        report = validate_stamp_set(tmp_path)
        assert not report.is_valid
        assert any(str(REQUIRED_COUNT) in e for e in report.errors)

    def test_empty_stickers_dir(self, tmp_path):
        (tmp_path / "stickers").mkdir()
        _write_png(tmp_path / "main.png", (MAIN_W, MAIN_H))
        _write_png(tmp_path / "tab.png", (TAB_W, TAB_H))

        report = validate_stamp_set(tmp_path)
        assert not report.is_valid


# ---------------------------------------------------------------------------
# Tests: main.png / tab.png presence
# ---------------------------------------------------------------------------

class TestMetaImages:
    def test_missing_main(self, tmp_path):
        stickers = tmp_path / "stickers"
        stickers.mkdir()
        for i in range(1, 9):
            _write_png(stickers / f"stamp_{i:02d}.png", (300, 280))
        _write_png(tmp_path / "tab.png", (TAB_W, TAB_H))
        # main.png intentionally missing

        report = validate_stamp_set(tmp_path)
        assert not report.is_valid
        assert any("main.png" in e for e in report.errors)

    def test_missing_tab(self, tmp_path):
        stickers = tmp_path / "stickers"
        stickers.mkdir()
        for i in range(1, 9):
            _write_png(stickers / f"stamp_{i:02d}.png", (300, 280))
        _write_png(tmp_path / "main.png", (MAIN_W, MAIN_H))
        # tab.png intentionally missing

        report = validate_stamp_set(tmp_path)
        assert not report.is_valid
        assert any("tab.png" in e for e in report.errors)


# ---------------------------------------------------------------------------
# Tests: dimension checks
# ---------------------------------------------------------------------------

class TestDimensions:
    def test_sticker_over_max_is_error(self, tmp_path):
        _build_valid_set(tmp_path)
        # overwrite stamp_01 with oversized image
        _write_png(tmp_path / "stickers" / "stamp_01.png", (STICKER_MAX_W + 10, STICKER_MAX_H + 10))

        report = validate_stamp_set(tmp_path)
        assert not report.is_valid

    def test_main_wrong_size_is_error(self, tmp_path):
        _build_valid_set(tmp_path)
        _write_png(tmp_path / "main.png", (200, 200))  # wrong (not 240x240)

        report = validate_stamp_set(tmp_path)
        assert not report.is_valid

    def test_tab_wrong_size_is_error(self, tmp_path):
        _build_valid_set(tmp_path)
        _write_png(tmp_path / "tab.png", (80, 60))  # wrong

        report = validate_stamp_set(tmp_path)
        assert not report.is_valid


# ---------------------------------------------------------------------------
# Tests: file size
# ---------------------------------------------------------------------------

class TestFileSize:
    def test_oversized_file_is_error(self, tmp_path):
        _build_valid_set(tmp_path)
        # Write a huge PNG (fill with random-ish data to defeat compression)
        import struct, zlib
        # Create a large valid RGBA PNG manually
        big_img = Image.new("RGBA", (370, 320), (200, 100, 50, 255))
        # Inflate file size by embedding a large comment in PNG metadata
        # Easiest: save and then re-write with padding to exceed 1MB
        sticker_path = tmp_path / "stickers" / "stamp_01.png"
        # Write the file as PNG then append dummy bytes (PNG ignores trailing data for our check)
        big_img.save(sticker_path, "PNG")
        with open(sticker_path, "ab") as f:
            f.write(b"\x00" * (MAX_FILE_BYTES + 1))

        report = validate_stamp_set(tmp_path)
        assert not report.is_valid


# ---------------------------------------------------------------------------
# Tests: transparency warning
# ---------------------------------------------------------------------------

class TestTransparencyWarning:
    def test_rgb_stamp_generates_warning(self, tmp_path):
        _build_valid_set(tmp_path)
        # overwrite stamp_01 with RGB (no alpha)
        _write_png(tmp_path / "stickers" / "stamp_01.png", (300, 280), mode="RGB")

        report = validate_stamp_set(tmp_path)
        # Should pass (no errors), but warn about missing transparency
        assert len(report.warnings) >= 1
        assert any("透過" in w for w in report.warnings)
