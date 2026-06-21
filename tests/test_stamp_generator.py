"""Tests for stamp_generator service."""

from __future__ import annotations
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.services.stamp_generator import (
    GenerationResult,
    GenerationSummary,
    StampItemSpec,
    _build_zip,
    _generate_themed_main_tab,
    generate_stamp_set,
    MAIN_H,
    MAIN_W,
    STICKER_MAX_H,
    STICKER_MAX_W,
    TAB_H,
    TAB_W,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_png(tmp_path: Path):
    def _make(name="test.png", size=(200, 200)) -> Path:
        img = Image.new("RGB", size, (80, 160, 200))
        p = tmp_path / name
        img.save(p, "PNG")
        return p
    return _make


def _make_8_specs(photo: Path) -> list[StampItemSpec]:
    return [
        StampItemSpec(position=i, photo_path=str(photo), caption=f"テスト{i}")
        for i in range(1, 9)
    ]


# ---------------------------------------------------------------------------
# Unit: _build_zip
# ---------------------------------------------------------------------------

class TestBuildZip:
    def _sticker(self, stickers_dir: Path, pos: int) -> GenerationResult:
        p = stickers_dir / f"stamp_{pos:02d}.png"
        Image.new("RGBA", (100, 100), (255, 0, 0, 255)).save(p, "PNG")
        return GenerationResult(position=pos, success=True, sticker_path=str(p))

    def test_zip_created(self, tmp_path):
        stickers_dir = tmp_path / "stickers"
        stickers_dir.mkdir()
        results = [self._sticker(stickers_dir, i) for i in range(1, 9)]
        Image.new("RGBA", (240, 240)).save(tmp_path / "main.png", "PNG")
        Image.new("RGBA", (96, 74)).save(tmp_path / "tab.png", "PNG")
        assert _build_zip(tmp_path, stickers_dir, results).exists()

    def test_contains_all_files(self, tmp_path):
        stickers_dir = tmp_path / "stickers"
        stickers_dir.mkdir()
        results = [self._sticker(stickers_dir, i) for i in range(1, 9)]
        Image.new("RGBA", (240, 240)).save(tmp_path / "main.png", "PNG")
        Image.new("RGBA", (96, 74)).save(tmp_path / "tab.png", "PNG")
        zp = _build_zip(tmp_path, stickers_dir, results)
        with zipfile.ZipFile(zp) as zf:
            names = set(zf.namelist())
        assert "main.png" in names and "tab.png" in names
        for i in range(1, 9):
            assert f"stamp_{i:02d}.png" in names

    def test_failed_items_excluded(self, tmp_path):
        stickers_dir = tmp_path / "stickers"
        stickers_dir.mkdir()
        results = [self._sticker(stickers_dir, i) for i in range(1, 8)]
        results.append(GenerationResult(position=8, success=False, error="fail"))
        Image.new("RGBA", (240, 240)).save(tmp_path / "main.png", "PNG")
        Image.new("RGBA", (96, 74)).save(tmp_path / "tab.png", "PNG")
        zp = _build_zip(tmp_path, stickers_dir, results)
        with zipfile.ZipFile(zp) as zf:
            assert "stamp_08.png" not in zf.namelist()


# ---------------------------------------------------------------------------
# Unit: _generate_themed_main_tab
# ---------------------------------------------------------------------------

class TestThemedMainTab:
    def _stickers(self, tmp_path: Path, n: int) -> list[Path]:
        paths = []
        sdir = tmp_path / "stickers"
        sdir.mkdir(exist_ok=True)
        for i in range(1, n + 1):
            p = sdir / f"stamp_{i:02d}.png"
            Image.new("RGBA", (300, 280), (200, 150, 100, 255)).save(p, "PNG")
            paths.append(p)
        return paths

    def test_creates_main_and_tab(self, tmp_path):
        stickers = self._stickers(tmp_path, 8)
        _generate_themed_main_tab(stickers, "family_pop", "テストセット", tmp_path)
        assert (tmp_path / "main.png").exists()
        assert (tmp_path / "tab.png").exists()

    def test_main_exact_size(self, tmp_path):
        stickers = self._stickers(tmp_path, 8)
        _generate_themed_main_tab(stickers, "celebration", "お祝い", tmp_path)
        assert Image.open(tmp_path / "main.png").size == (MAIN_W, MAIN_H)

    def test_tab_exact_size(self, tmp_path):
        stickers = self._stickers(tmp_path, 8)
        _generate_themed_main_tab(stickers, "simple_icon", "アイコン", tmp_path)
        assert Image.open(tmp_path / "tab.png").size == (TAB_W, TAB_H)

    def test_main_is_rgba(self, tmp_path):
        stickers = self._stickers(tmp_path, 8)
        _generate_themed_main_tab(stickers, "cute_daily", "かわいい", tmp_path)
        assert Image.open(tmp_path / "main.png").mode == "RGBA"

    def test_works_with_single_sticker(self, tmp_path):
        stickers = self._stickers(tmp_path, 1)
        _generate_themed_main_tab(stickers, "baby_kids", "ベビー", tmp_path)
        assert (tmp_path / "main.png").exists()

    def test_empty_stickers_noop(self, tmp_path):
        _generate_themed_main_tab([], "family_pop", "空", tmp_path)
        assert not (tmp_path / "main.png").exists()

    def test_unknown_theme_still_works(self, tmp_path):
        stickers = self._stickers(tmp_path, 8)
        _generate_themed_main_tab(stickers, "nonexistent", "テスト", tmp_path)
        assert (tmp_path / "main.png").exists()


# ---------------------------------------------------------------------------
# Integration: generate_stamp_set
# ---------------------------------------------------------------------------

class TestGenerateStampSet:
    def test_all_8_succeed(self, tmp_path, sample_png):
        photo = sample_png("photo.png", (200, 250))
        summary = generate_stamp_set(_make_8_specs(photo), tmp_path / "out")
        assert summary.success_count == 8
        assert summary.failed_positions == []

    def test_sticker_files_exist(self, tmp_path, sample_png):
        photo = sample_png("photo.png", (200, 250))
        summary = generate_stamp_set(_make_8_specs(photo), tmp_path / "out")
        out = Path(summary.set_output_dir)
        for i in range(1, 9):
            assert (out / "stickers" / f"stamp_{i:02d}.png").exists()

    def test_main_tab_created(self, tmp_path, sample_png):
        photo = sample_png("photo.png", (200, 250))
        summary = generate_stamp_set(_make_8_specs(photo), tmp_path / "out")
        out = Path(summary.set_output_dir)
        assert (out / "main.png").exists()
        assert (out / "tab.png").exists()

    def test_zip_created(self, tmp_path, sample_png):
        photo = sample_png("photo.png", (200, 250))
        summary = generate_stamp_set(_make_8_specs(photo), tmp_path / "out")
        assert summary.zip_path and Path(summary.zip_path).exists()

    def test_preview_images_created(self, tmp_path, sample_png):
        photo = sample_png("photo.png", (200, 250))
        summary = generate_stamp_set(_make_8_specs(photo), tmp_path / "out")
        for r in summary.results:
            if r.success:
                assert r.preview_path and Path(r.preview_path).exists()

    def test_sticker_fits_spec(self, tmp_path, sample_png):
        photo = sample_png("photo.png", (200, 250))
        summary = generate_stamp_set(_make_8_specs(photo), tmp_path / "out")
        for r in summary.results:
            if r.success:
                img = Image.open(r.sticker_path)
                assert img.width <= STICKER_MAX_W and img.height <= STICKER_MAX_H

    def test_missing_photo_recorded_as_error(self, tmp_path, sample_png):
        photo = sample_png("photo.png")
        specs = _make_8_specs(photo)
        specs[4] = StampItemSpec(position=5, photo_path="/no/such/file.png", caption="?")
        summary = generate_stamp_set(specs, tmp_path / "out")
        assert 5 in summary.failed_positions
        assert summary.success_count == 7

    @pytest.mark.parametrize("style", ["simple_circle", "pop_star", "heart",
                                       "birthday", "seasonal_sakura", "cool_badge", "speech_bubble"])
    def test_all_templates(self, tmp_path, sample_png, style):
        photo = sample_png("photo.png")
        specs = [StampItemSpec(position=i, photo_path=str(photo), caption="テスト", style=style)
                 for i in range(1, 9)]
        summary = generate_stamp_set(specs, tmp_path / f"out_{style}")
        assert summary.success_count == 8

    def test_themed_main_uses_theme_color(self, tmp_path, sample_png):
        photo = sample_png("photo.png")
        specs = _make_8_specs(photo)
        summary = generate_stamp_set(specs, tmp_path / "out",
                                     theme_name="celebration", set_name="お祝いセット")
        out = Path(summary.set_output_dir)
        assert (out / "main.png").exists()
        # celebration main_bg is orange-ish; sample a corner pixel
        from app.services.stamp_themes import THEMES
        main = Image.open(out / "main.png").convert("RGBA")
        corner = main.getpixel((2, 2))
        assert corner == THEMES["celebration"].main_bg

    def test_japanese_caption_in_sticker(self, tmp_path, sample_png):
        photo = sample_png("photo.png")
        specs = [
            StampItemSpec(position=i, photo_path=str(photo), caption=cap)
            for i, cap in enumerate(
                ["ありがとう", "了解", "おつかれさま", "OK", "ごめん",
                 "いってきます", "おやすみ", "最高"], start=1
            )
        ]
        summary = generate_stamp_set(specs, tmp_path / "out")
        assert summary.success_count == 8, f"Failed: {summary.failed_positions}"


# ---------------------------------------------------------------------------
# GenerationSummary properties
# ---------------------------------------------------------------------------

class TestGenerationSummary:
    def _summary(self, ok, fail):
        results = (
            [GenerationResult(p, success=True) for p in ok]
            + [GenerationResult(p, success=False, error="err") for p in fail]
        )
        return GenerationSummary(set_output_dir="/x", zip_path=None, results=results)

    def test_success_count(self):
        assert self._summary([1, 2, 3], [4]).success_count == 3

    def test_failed_positions(self):
        assert sorted(self._summary([1, 3], [2, 4]).failed_positions) == [2, 4]

    def test_all_ok(self):
        s = self._summary(list(range(1, 9)), [])
        assert s.success_count == 8 and s.failed_positions == []
