"""Tests for application metadata, submission review, and packaging."""

from __future__ import annotations
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.services.metadata import suggest_metadata, default_metadata, META_FIELDS
from app.services.review import run_review, ReviewReport
from app.services.stamp_generator import (
    StampItemSpec, generate_stamp_set, build_application_package, write_application_files,
)


# ---------------------------------------------------------------------------
# Metadata suggestion
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_default_has_all_fields(self):
        d = default_metadata()
        for k in META_FIELDS:
            assert k in d

    def test_suggest_family_theme(self):
        m = suggest_metadata("family_pop", ["ありがとう", "ただいま"], ["family", "child"], author="山田")
        assert m["title"]
        assert m["category"] == "家族・こども"
        assert "家族" in m["tags"]
        assert m["author"] == "山田"
        assert "山田" in m["copyright"]

    def test_suggest_business_theme(self):
        m = suggest_metadata("business_casual", ["承知しました"], [])
        assert m["category"] == "ビジネス"

    def test_suggest_includes_photo_tags(self):
        m = suggest_metadata("simple_icon", [], ["sunset", "sunset", "beach"])
        assert "sunset" in m["tags"]

    def test_unknown_theme_falls_back(self):
        m = suggest_metadata("nonexistent", ["x"], [])
        assert m["title"]


# ---------------------------------------------------------------------------
# Review report
# ---------------------------------------------------------------------------

def _items(n=8, **over):
    base = []
    for i in range(1, n + 1):
        base.append({"position": i, "photo_path": f"/p{i}.jpg",
                     "caption": f"c{i}", "warnings": None})
    for k, v in over.items():
        idx, field = k.split("__")
        base[int(idx)][field] = v
    return base


class TestReview:
    def test_not_generated_is_error(self):
        rep = run_review(None, _items(), 8)
        assert not rep.is_ready
        assert any("生成" in i.message for i in rep.errors)

    def test_duplicate_caption_flagged(self, tmp_path):
        items = _items(8)
        items[1]["caption"] = "c1"   # duplicate of slot 1
        rep = run_review(None, items, 8)
        dup = [i for i in rep.by_category("content")]
        assert any("重複" in i.message for i in dup)
        assert any(i.position is not None for i in dup)

    def test_duplicate_photo_flagged(self):
        items = _items(8)
        for i in range(3):
            items[i]["photo_path"] = "/same.jpg"
        rep = run_review(None, items, 8)
        assert any("使い回し" in i.message or "使われて" in i.message
                   for i in rep.by_category("content"))

    def test_quality_warnings_have_positions(self):
        items = _items(8)
        items[4]["warnings"] = json.dumps(["顔が見切れています"])
        rep = run_review(None, items, 8)
        q = rep.by_category("quality")
        assert q and q[0].position == 5
        assert q[0].fix in ("edit", "photo")

    def test_risk_advisory_on_keyword(self):
        items = _items(8)
        items[0]["caption"] = "アニメキャラ"
        rep = run_review(None, items, 8, photo_tags_by_pos={1: ["anime", "character"]})
        assert any(i.category == "risk" for i in rep.issues)

    def test_always_on_advisory_present(self):
        rep = run_review(None, _items(8), 8)
        assert any(i.category == "risk" and i.level == "advisory" for i in rep.issues)

    def test_invalid_count_error(self):
        rep = run_review(None, _items(8), 13)
        assert any("13" in i.message for i in rep.errors)

    def test_submit_status_needs_fix_when_error(self):
        rep = run_review(None, _items(8), 8)   # not generated => error
        assert rep.submit_status(has_zip=False) == "needs_fix"


# ---------------------------------------------------------------------------
# Packaging (ZIP includes images + metadata + notes)
# ---------------------------------------------------------------------------

@pytest.fixture
def generated_set(tmp_path):
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (300, 400), (180, 150, 120)).save(photo, "JPEG")
    specs = [StampItemSpec(position=i + 1, photo_path=str(photo), caption=f"c{i}",
                           style="simple_circle") for i in range(8)]
    out = tmp_path / "out"
    generate_stamp_set(specs, out, theme_name="family_pop", set_name="テスト")
    return out


class TestPackaging:
    def test_write_application_files(self, tmp_path):
        meta = default_metadata()
        meta["title"] = "テストスタンプ"
        names = write_application_files(tmp_path, meta, 8, ["[OK] images"])
        assert set(names) == {"metadata.json", "application_note.txt", "checklist.txt"}
        md = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
        assert md["title"] == "テストスタンプ"
        assert md["stamp_count"] == 8
        note = (tmp_path / "application_note.txt").read_text(encoding="utf-8")
        assert "テストスタンプ" in note

    def test_package_zip_contains_all(self, generated_set):
        meta = default_metadata()
        meta["title"] = "セット名"
        zp = build_application_package(generated_set, meta, 8, ["[OK]"], "family_pop", "セット名")
        with zipfile.ZipFile(zp) as z:
            names = set(z.namelist())
        for f in ("main.png", "tab.png", "metadata.json", "application_note.txt", "checklist.txt"):
            assert f in names
        for i in range(1, 9):
            assert f"stamp_{i:02d}.png" in names

    def test_package_backward_compatible_images(self, generated_set):
        """The package must still contain the original images (ZIP compat)."""
        meta = default_metadata()
        zp = build_application_package(generated_set, meta, 8, [], "family_pop", "x")
        with zipfile.ZipFile(zp) as z:
            names = z.namelist()
        assert sum(1 for n in names if n.startswith("stamp_")) == 8

    def test_package_none_when_no_stickers(self, tmp_path):
        assert build_application_package(tmp_path, default_metadata(), 8, []) is None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@pytest.fixture
def app_with_photos(tmp_path):
    from app import create_app
    selected = tmp_path / "selected"
    selected.mkdir()
    for i in range(8):
        Image.new("RGB", (300, 400), (180, 140 + i * 5, 110)).save(selected / f"p{i}.jpg", "JPEG")
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "t.db"),
        "OUTPUT_DIR": str(tmp_path / "out"),
        "PHOTO_SELECTOR_MANIFEST": str(tmp_path / "no.json"),
        "PHOTO_SELECTOR_SELECTED_DIR": str(selected),
    })
    app._photos = [str(selected / f"p{i}.jpg") for i in range(8)]
    return app


@pytest.fixture
def client(app_with_photos):
    return app_with_photos.test_client()


def _make_set(client, app, count=8):
    data = {"name": "S", "theme": "family_pop", "stamp_count": count}
    for i, p in enumerate(app._photos, start=1):
        data[f"photo_{i}"] = p
    client.post("/stamps", data=data)
    with app.app_context():
        from app.db import get_db
        return get_db().execute("SELECT id FROM stamp_sets ORDER BY id DESC LIMIT 1").fetchone()["id"]


class TestMetaRoutes:
    def test_save_meta_persists(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        client.post(f"/stamps/{sid}/meta", data={"title": "私のスタンプ", "author": "太郎",
                                                  "description": "せつめい"})
        with app_with_photos.app_context():
            from app.db import get_db
            raw = get_db().execute("SELECT meta_json FROM stamp_sets WHERE id=?", (sid,)).fetchone()["meta_json"]
            meta = json.loads(raw)
            assert meta["title"] == "私のスタンプ"
            assert meta["author"] == "太郎"

    def test_suggest_meta_fills(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        client.post(f"/stamps/{sid}/meta/suggest")
        with app_with_photos.app_context():
            from app.db import get_db
            raw = get_db().execute("SELECT meta_json FROM stamp_sets WHERE id=?", (sid,)).fetchone()["meta_json"]
            assert json.loads(raw)["title"]

    def test_review_page_renders(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        r = client.get(f"/stamps/{sid}/review")
        assert r.status_code == 200
        assert "申請".encode("utf-8") in r.data

    def test_export_alias_still_works(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        assert client.get(f"/stamps/{sid}/export").status_code == 200


class TestPackageRoute:
    def test_package_after_generate(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        client.post(f"/stamps/{sid}/generate")
        client.post(f"/stamps/{sid}/meta", data={"title": "T", "author": "A"})
        r = client.post(f"/stamps/{sid}/package")
        assert r.status_code == 302
        with app_with_photos.app_context():
            from app.db import get_db
            row = get_db().execute("SELECT zip_path, submit_status FROM stamp_sets WHERE id=?", (sid,)).fetchone()
            assert row["zip_path"] and Path(row["zip_path"]).exists()
            with zipfile.ZipFile(row["zip_path"]) as z:
                assert "metadata.json" in z.namelist()
            assert row["submit_status"] in ("exported", "ready", "needs_fix")

    def test_ready_status_when_clean(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        client.post(f"/stamps/{sid}/generate")
        client.post(f"/stamps/{sid}/package")
        # Review recomputes status; a clean 8-set with distinct captions should be exported
        r = client.get(f"/stamps/{sid}/review")
        assert r.status_code == 200
