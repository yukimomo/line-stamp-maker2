"""Integration tests for routes: theme-based set creation and inline editing."""

from __future__ import annotations
import json
from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def app_with_photos(tmp_path):
    """Flask app whose photo-selector dir contains 8 real photos."""
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


def _create_set(client, photo_paths, theme="family_pop", name="テストセット"):
    data = {"name": name, "description": "説明", "theme": theme}
    for i, p in enumerate(photo_paths, start=1):
        data[f"photo_{i}"] = p
    return client.post("/stamps", data=data, follow_redirects=False)


class TestCreateSetWithTheme:
    def test_create_redirects(self, client, app_with_photos):
        r = _create_set(client, app_with_photos._photo_paths)
        assert r.status_code == 302

    def test_create_assigns_captions(self, client, app_with_photos):
        _create_set(client, app_with_photos._photo_paths, theme="business_casual")
        with app_with_photos.app_context():
            from app.db import get_db
            db = get_db()
            items = db.execute("SELECT caption, item_template FROM stamp_items ORDER BY position").fetchall()
            assert len(items) == 8
            # All captions filled, all from business_casual theme
            from app.services.stamp_themes import THEMES
            theme_caps = set(THEMES["business_casual"].captions)
            for it in items:
                assert it["caption"] in theme_caps
                assert it["item_template"] is not None

    def test_create_stores_theme(self, client, app_with_photos):
        _create_set(client, app_with_photos._photo_paths, theme="celebration")
        with app_with_photos.app_context():
            from app.db import get_db
            row = get_db().execute("SELECT theme FROM stamp_sets").fetchone()
            assert row["theme"] == "celebration"

    def test_missing_name_returns_400(self, client, app_with_photos):
        data = {"name": "", "theme": "family_pop"}
        for i, p in enumerate(app_with_photos._photo_paths, start=1):
            data[f"photo_{i}"] = p
        r = client.post("/stamps", data=data)
        assert r.status_code == 400

    def test_fewer_photos_cycle_to_fill(self, client, app_with_photos):
        # Fewer photos than count is now allowed — they cycle to fill 8 slots
        r = _create_set(client, app_with_photos._photo_paths[:3])
        assert r.status_code == 302
        with app_with_photos.app_context():
            from app.db import get_db
            n = get_db().execute("SELECT COUNT(*) c FROM stamp_items").fetchone()["c"]
            assert n == 8

    def test_zero_photos_returns_400(self, client, app_with_photos):
        r = _create_set(client, [])
        assert r.status_code == 400

    def test_invalid_theme_falls_back(self, client, app_with_photos):
        _create_set(client, app_with_photos._photo_paths, theme="bogus")
        with app_with_photos.app_context():
            from app.db import get_db
            row = get_db().execute("SELECT theme FROM stamp_sets").fetchone()
            assert row["theme"] == "simple_icon"


class TestInlineEditing:
    def _make_set(self, client, app):
        _create_set(client, app._photo_paths)
        with app.app_context():
            from app.db import get_db
            return get_db().execute("SELECT id FROM stamp_sets").fetchone()["id"]

    def test_edit_captions(self, client, app_with_photos):
        set_id = self._make_set(client, app_with_photos)
        data = {"name": "更新名", "description": "新説明", "text_style": "pop"}
        for i in range(1, 9):
            data[f"caption_{i}"] = f"セリフ{i}"
            data[f"template_{i}"] = "heart"
        r = client.post(f"/stamps/{set_id}/edit", data=data)
        assert r.status_code == 302

        with app_with_photos.app_context():
            from app.db import get_db
            db = get_db()
            s = db.execute("SELECT name, text_style FROM stamp_sets WHERE id=?", (set_id,)).fetchone()
            assert s["name"] == "更新名"
            assert s["text_style"] == "pop"
            items = db.execute("SELECT caption, item_template FROM stamp_items WHERE set_id=? ORDER BY position", (set_id,)).fetchall()
            assert items[0]["caption"] == "セリフ1"
            assert items[0]["item_template"] == "heart"

    def test_swap_photo(self, client, app_with_photos):
        set_id = self._make_set(client, app_with_photos)
        new_photo = app_with_photos._photo_paths[7]
        r = client.post(f"/stamps/{set_id}/swap_photo",
                        data={"position": 1, "photo_path": new_photo})
        assert r.status_code == 200
        assert r.get_json()["ok"] is True
        with app_with_photos.app_context():
            from app.db import get_db
            row = get_db().execute(
                "SELECT photo_path FROM stamp_items WHERE set_id=? AND position=1", (set_id,)
            ).fetchone()
            assert row["photo_path"] == new_photo

    def test_reorder(self, client, app_with_photos):
        set_id = self._make_set(client, app_with_photos)
        # Capture original captions by position
        with app_with_photos.app_context():
            from app.db import get_db
            before = {r["position"]: r["caption"] for r in get_db().execute(
                "SELECT position, caption FROM stamp_items WHERE set_id=?", (set_id,)).fetchall()}

        # Reverse order
        order = list(range(8, 0, -1))
        r = client.post(f"/stamps/{set_id}/reorder",
                        data=json.dumps({"order": order}),
                        content_type="application/json")
        assert r.status_code == 200
        with app_with_photos.app_context():
            from app.db import get_db
            after = {r["position"]: r["caption"] for r in get_db().execute(
                "SELECT position, caption FROM stamp_items WHERE set_id=?", (set_id,)).fetchall()}
        # New slot 1 should hold what was old slot 8
        assert after[1] == before[8]

    def test_reorder_invalid_permutation_rejected(self, client, app_with_photos):
        set_id = self._make_set(client, app_with_photos)
        r = client.post(f"/stamps/{set_id}/reorder",
                        data=json.dumps({"order": [1, 2, 3]}),
                        content_type="application/json")
        assert r.status_code == 400


class TestNewPageRendersThemes:
    def test_new_page_lists_themes(self, client):
        r = client.get("/stamps/new")
        assert r.status_code == 200
        html = r.data.decode("utf-8")
        for theme in ("family_pop", "business_casual", "celebration"):
            assert theme in html


class TestAiFinishRoute:
    def _make_generated_set(self, client, app):
        _create_set(client, app._photo_paths)
        with app.app_context():
            from app.db import get_db
            db = get_db()
            set_id = db.execute("SELECT id FROM stamp_sets").fetchone()["id"]
            out = Path(app.config["OUTPUT_DIR"]) / f"set_{set_id:04d}"
            out.mkdir(parents=True)
            Image.new("RGBA", (240, 240), (120, 160, 200, 255)).save(out / "main.png", "PNG")
            db.execute(
                "UPDATE stamp_sets SET status='generated', output_dir=? WHERE id=?",
                (str(out), set_id),
            )
            db.commit()
        return set_id, out

    def test_ai_finish_uses_generated_main_png(self, client, app_with_photos, monkeypatch):
        set_id, out = self._make_generated_set(client, app_with_photos)
        called = {}

        def fake_finish(input_path, output_dir):
            called["input_path"] = input_path
            called["output_dir"] = output_dir
            output_dir.mkdir(parents=True)
            for name in ("natural", "storybook", "premium"):
                Image.new("RGBA", (1024, 1024), (255, 255, 255, 255)).save(output_dir / f"{name}.png", "PNG")
            return []

        import app.routes as routes
        monkeypatch.setattr(routes, "finish_icon_with_ai", fake_finish)

        r = client.post(f"/stamps/{set_id}/ai_finish", follow_redirects=True)

        assert r.status_code == 200
        assert called["input_path"] == out / "main.png"
        assert called["output_dir"] == out / "ai_finish"
        assert (out / "ai_finish" / "natural.png").exists()
        assert "AI仕上げ".encode("utf-8") in r.data

    def test_ai_finish_requires_generated_icon(self, client, app_with_photos):
        _create_set(client, app_with_photos._photo_paths)
        with app_with_photos.app_context():
            from app.db import get_db
            set_id = get_db().execute("SELECT id FROM stamp_sets").fetchone()["id"]

        r = client.post(f"/stamps/{set_id}/ai_finish", follow_redirects=True)

        assert r.status_code == 200
        assert "アイコン生成後".encode("utf-8") in r.data
class TestChatGptReadyRoute:
    def _make_generated_set(self, client, app):
        _create_set(client, app._photo_paths)
        with app.app_context():
            from app.db import get_db
            db = get_db()
            set_id = db.execute("SELECT id FROM stamp_sets").fetchone()["id"]
            out = Path(app.config["OUTPUT_DIR"]) / f"set_{set_id:04d}"
            out.mkdir(parents=True)
            Image.new("RGBA", (240, 240), (120, 160, 200, 255)).save(out / "main.png", "PNG")
            db.execute(
                "UPDATE stamp_sets SET status='generated', output_dir=? WHERE id=?",
                (str(out), set_id),
            )
            db.commit()
        return set_id, out

    def test_chatgpt_ready_exports_generated_main_png(self, client, app_with_photos, monkeypatch):
        self._make_generated_set(client, app_with_photos)
        monkeypatch.setattr("app.services.chatgpt_ready.copy_prompt_to_clipboard", lambda prompt: True)
        with app_with_photos.app_context():
            from app.db import get_db
            set_id = get_db().execute("SELECT id FROM stamp_sets").fetchone()["id"]

        r = client.post(f"/stamps/{set_id}/chatgpt_ready", follow_redirects=True)

        ready = Path(app_with_photos.config["OUTPUT_DIR"]) / "chatgpt-ready"
        assert r.status_code == 200
        assert (ready / "icon_natural_source.png").exists()
        assert (ready / "icon_storybook_source.png").exists()
        assert (ready / "icon_premium_source.png").exists()
        assert "3. premium" in (ready / "prompt.txt").read_text(encoding="utf-8")
        assert Image.open(ready / "icon_natural_source.png").size == (240, 240)

    def test_chatgpt_ready_requires_generated_icon(self, client, app_with_photos):
        _create_set(client, app_with_photos._photo_paths)
        with app_with_photos.app_context():
            from app.db import get_db
            set_id = get_db().execute("SELECT id FROM stamp_sets").fetchone()["id"]

        r = client.post(f"/stamps/{set_id}/chatgpt_ready", follow_redirects=True)

        assert r.status_code == 200
        assert "ChatGPT".encode("utf-8") in r.data

    def test_open_chatgpt_ready_opens_output_folder(self, client, app_with_photos, monkeypatch):
        set_id, _ = self._make_generated_set(client, app_with_photos)
        called = {}

        def fake_open(path):
            called["path"] = path

        import app.routes as routes
        monkeypatch.setattr(routes, "open_folder", fake_open)

        r = client.post(f"/stamps/{set_id}/chatgpt_ready/open")

        assert r.status_code == 302
        assert called["path"] == Path(app_with_photos.config["OUTPUT_DIR"]) / "chatgpt-ready"

    def test_import_chatgpt_finished_and_save_final_icon(self, client, app_with_photos):
        set_id, _ = self._make_generated_set(client, app_with_photos)
        ready = Path(app_with_photos.config["OUTPUT_DIR"]) / "chatgpt-ready"
        ready.mkdir(parents=True)
        Image.new("RGB", (1024, 1024), (240, 220, 200)).save(ready / "natural_chatgpt.jpg", "JPEG")
        Image.new("RGBA", (1024, 1024), (200, 220, 240, 255)).save(ready / "premium_finished.png", "PNG")

        r = client.post(f"/stamps/{set_id}/chatgpt_ready/import", follow_redirects=True)

        assert r.status_code == 200
        assert (ready / "icon_natural_finished.png").exists()
        assert (ready / "icon_natural_circle_preview.png").exists()
        assert (ready / "icon_premium_finished.png").exists()
        assert "final_icon.png".encode("utf-8") in r.data

        r = client.post(
            f"/stamps/{set_id}/chatgpt_ready/final",
            data={"variant": "premium"},
            follow_redirects=True,
        )

        assert r.status_code == 200
        assert (ready / "final_icon.png").exists()
        assert (ready / "final_icon_circle_preview.png").exists()
