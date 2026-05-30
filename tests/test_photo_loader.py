"""Tests for photo_loader service."""

from __future__ import annotations
import json
from pathlib import Path

import pytest

from app.services.photo_loader import load_adopted_photos, _from_manifest, _from_directory


class TestFromManifest:
    def test_returns_only_selected(self, manifest_file, tmp_path):
        photos = _from_manifest(manifest_file)
        assert len(photos) == 2  # photo_b has selected=False

    def test_sorted_by_score_desc(self, manifest_file):
        photos = _from_manifest(manifest_file)
        scores = [p["score"] for p in photos]
        assert scores == sorted(scores, reverse=True)

    def test_fields_present(self, manifest_file):
        photos = _from_manifest(manifest_file)
        for p in photos:
            assert "path" in p
            assert "score" in p
            assert "caption" in p
            assert "tags" in p

    def test_accepts_score_key(self, manifest_file):
        # photo_c uses "score" instead of "overall_score"
        photos = _from_manifest(manifest_file)
        paths = [Path(p["path"]).name for p in photos]
        assert "photo_c.heic" in paths

    def test_empty_manifest(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text(json.dumps({"photos": []}), encoding="utf-8")
        assert _from_manifest(path) == []

    def test_no_selected_field(self, tmp_path):
        # items without 'selected' key should be excluded (falsy)
        data = {"photos": [{"path": "/x.jpg", "analysis": {"overall_score": 0.5}}]}
        path = tmp_path / "m.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert _from_manifest(path) == []


class TestFromDirectory:
    def test_returns_image_files(self, tmp_path):
        for name in ("a.jpg", "b.PNG", "c.heic", "d.txt", "e.mp4"):
            (tmp_path / name).write_bytes(b"dummy")
        photos = _from_directory(tmp_path)
        names = {Path(p["path"]).name for p in photos}
        assert "a.jpg" in names
        assert "b.PNG" in names
        assert "c.heic" in names
        assert "d.txt" not in names
        assert "e.mp4" not in names

    def test_empty_dir(self, tmp_path):
        assert _from_directory(tmp_path) == []


class TestLoadAdoptedPhotos:
    def test_prefers_manifest(self, manifest_file, tmp_path):
        result = load_adopted_photos(manifest_file, tmp_path / "selected")
        assert len(result) == 2  # from manifest

    def test_falls_back_to_directory(self, tmp_path):
        selected = tmp_path / "selected"
        selected.mkdir()
        (selected / "x.jpg").write_bytes(b"dummy")
        result = load_adopted_photos(tmp_path / "missing.json", selected)
        assert len(result) == 1

    def test_returns_empty_when_both_missing(self, tmp_path):
        result = load_adopted_photos(tmp_path / "no.json", tmp_path / "no_dir")
        assert result == []
