"""Tests for variable stamp count, item management, regenerate, preview, export."""

from __future__ import annotations
import json
from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def app_with_photos(tmp_path):
    from app import create_app

    selected = tmp_path / "selected"
    selected.mkdir()
    for i in range(8):
        Image.new("RGB", (300, 400), (180, 140 + i * 5, 110)).save(
            selected / f"photo_{i}.jpg", "JPEG"
        )

    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.db"),
        "OUTPUT_DIR": str(tmp_path / "output"),
        "PHOTO_SELECTOR_MANIFEST": str(tmp_path / "missing.json"),
        "PHOTO_SELECTOR_SELECTED_DIR": str(selected),
    })
    app._photo_paths = [str(selected / f"photo_{i}.jpg") for i in range(8)]
    return app


@pytest.fixture
def client(app_with_photos):
    return app_with_photos.test_client()


def _create(client, app, count=8, photos=None, theme="family_pop"):
    paths = photos if photos is not None else app._photo_paths
    data = {"name": "セット", "description": "", "theme": theme, "stamp_count": count}
    for i, p in enumerate(paths, start=1):
        data[f"photo_{i}"] = p
    client.post("/stamps", data=data)
    with app.app_context():
        from app.db import get_db
        return get_db().execute("SELECT id FROM stamp_sets ORDER BY id DESC LIMIT 1").fetchone()["id"]


def _count_items(app, set_id):
    with app.app_context():
        from app.db import get_db
        return get_db().execute(
            "SELECT COUNT(*) c FROM stamp_items WHERE set_id=?", (set_id,)
        ).fetchone()["c"]


class TestVariableCount:
    @pytest.mark.parametrize("count", [8, 16, 24, 32, 40])
    def test_create_with_count(self, client, app_with_photos, count):
        sid = _create(client, app_with_photos, count=count)
        assert _count_items(app_with_photos, sid) == count

    def test_invalid_count_falls_back_to_8(self, client, app_with_photos):
        data = {"name": "X", "theme": "family_pop", "stamp_count": 13}
        for i, p in enumerate(app_with_photos._photo_paths, start=1):
            data[f"photo_{i}"] = p
        client.post("/stamps", data=data)
        with app_with_photos.app_context():
            from app.db import get_db
            row = get_db().execute("SELECT stamp_count FROM stamp_sets ORDER BY id DESC LIMIT 1").fetchone()
            assert row["stamp_count"] == 8

    def test_positions_are_unique_and_sequential(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=16)
        with app_with_photos.app_context():
            from app.db import get_db
            rows = get_db().execute(
                "SELECT position FROM stamp_items WHERE set_id=? ORDER BY position", (sid,)
            ).fetchall()
            positions = [r["position"] for r in rows]
            assert positions == list(range(1, 17))


class TestChangeCount:
    def test_increase_adds_slots(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=8)
        client.post(f"/stamps/{sid}/count", data={"stamp_count": 24})
        assert _count_items(app_with_photos, sid) == 24

    def test_decrease_trims_slots(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=16)
        client.post(f"/stamps/{sid}/count", data={"stamp_count": 8})
        assert _count_items(app_with_photos, sid) == 8

    def test_change_resets_status(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=8)
        client.post(f"/stamps/{sid}/count", data={"stamp_count": 16})
        with app_with_photos.app_context():
            from app.db import get_db
            row = get_db().execute("SELECT status FROM stamp_sets WHERE id=?", (sid,)).fetchone()
            assert row["status"] == "draft"


class TestItemManagement:
    def test_delete_item_renumbers(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=8)
        client.post(f"/stamps/{sid}/item/3/delete")
        with app_with_photos.app_context():
            from app.db import get_db
            rows = get_db().execute(
                "SELECT position FROM stamp_items WHERE set_id=? ORDER BY position", (sid,)
            ).fetchall()
            assert [r["position"] for r in rows] == list(range(1, 8))

    def test_duplicate_item_appends(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=8)
        client.post(f"/stamps/{sid}/item/2/duplicate")
        assert _count_items(app_with_photos, sid) == 9

    def test_reorder_permutation(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=8)
        with app_with_photos.app_context():
            from app.db import get_db
            before = {r["position"]: r["caption"] for r in get_db().execute(
                "SELECT position, caption FROM stamp_items WHERE set_id=?", (sid,)).fetchall()}
        order = list(range(8, 0, -1))
        r = client.post(f"/stamps/{sid}/reorder", data=json.dumps({"order": order}),
                        content_type="application/json")
        assert r.status_code == 200
        with app_with_photos.app_context():
            from app.db import get_db
            after = {r["position"]: r["caption"] for r in get_db().execute(
                "SELECT position, caption FROM stamp_items WHERE set_id=?", (sid,)).fetchall()}
        assert after[1] == before[8]

    def test_reorder_carries_adjustments(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=8)
        with app_with_photos.app_context():
            from app.db import get_db
            db = get_db()
            db.execute("UPDATE stamp_items SET zoom=1.7 WHERE set_id=? AND position=8", (sid,))
            db.commit()
        client.post(f"/stamps/{sid}/reorder", data=json.dumps({"order": list(range(8, 0, -1))}),
                    content_type="application/json")
        with app_with_photos.app_context():
            from app.db import get_db
            row = get_db().execute(
                "SELECT zoom FROM stamp_items WHERE set_id=? AND position=1", (sid,)).fetchone()
            assert row["zoom"] == pytest.approx(1.7)


class TestBulkEdit:
    def test_bulk_template(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=8)
        client.post(f"/stamps/{sid}/bulk", data={"bulk_template": "heart"})
        with app_with_photos.app_context():
            from app.db import get_db
            tmpls = [r["item_template"] for r in get_db().execute(
                "SELECT item_template FROM stamp_items WHERE set_id=?", (sid,)).fetchall()]
            assert all(t == "heart" for t in tmpls)

    def test_bulk_text_style(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=8)
        client.post(f"/stamps/{sid}/bulk", data={"bulk_text_style": "outline_white"})
        with app_with_photos.app_context():
            from app.db import get_db
            row = get_db().execute("SELECT text_style FROM stamp_sets WHERE id=?", (sid,)).fetchone()
            assert row["text_style"] == "outline_white"


class TestRegenerateItem:
    def test_template_mode_changes_template(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=8)
        with app_with_photos.app_context():
            from app.db import get_db
            before = get_db().execute(
                "SELECT item_template FROM stamp_items WHERE set_id=? AND position=1", (sid,)).fetchone()["item_template"]
        client.post(f"/stamps/{sid}/item/1/regenerate", data={"mode": "template"})
        with app_with_photos.app_context():
            from app.db import get_db
            after = get_db().execute(
                "SELECT item_template FROM stamp_items WHERE set_id=? AND position=1", (sid,)).fetchone()["item_template"]
        assert after != before

    def test_caption_mode_changes_caption(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=8)
        with app_with_photos.app_context():
            from app.db import get_db
            before = get_db().execute(
                "SELECT caption FROM stamp_items WHERE set_id=? AND position=1", (sid,)).fetchone()["caption"]
        client.post(f"/stamps/{sid}/item/1/regenerate", data={"mode": "caption"})
        with app_with_photos.app_context():
            from app.db import get_db
            after = get_db().execute(
                "SELECT caption FROM stamp_items WHERE set_id=? AND position=1", (sid,)).fetchone()["caption"]
        assert after != before


class TestPreview:
    def test_preview_returns_png(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=8)
        photo = app_with_photos._photo_paths[0]
        r = client.get(f"/stamps/{sid}/preview", query_string={
            "photo": photo, "caption": "ありがとう", "template": "pop_star",
            "text_style": "bubble", "zoom": "1.2",
        })
        assert r.status_code == 200
        assert r.mimetype == "image/png"
        assert r.data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_preview_missing_photo_404(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=8)
        r = client.get(f"/stamps/{sid}/preview", query_string={"photo": "/no/file.jpg"})
        assert r.status_code == 404


class TestExportReview:
    def test_export_page_renders(self, client, app_with_photos):
        sid = _create(client, app_with_photos, count=8)
        r = client.get(f"/stamps/{sid}/export")
        assert r.status_code == 200
        assert "エクスポート".encode("utf-8") in r.data
