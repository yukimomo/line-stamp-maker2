"""Tests for the 5 built-in design presets and set-wide application."""

from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.services.design_presets import (
    BUILTIN_PRESETS, preset_overrides, preset_decorations, preset_main_bg,
)
from app.services.stamp_generator import StampItemSpec, render_preview, generate_stamp_set

PRESET_KEYS = ["pastel_pop", "comic_reaction", "business_clean",
               "sticker_cute", "celebration_party"]


class TestPresetDefinitions:
    def test_five_presets_exist(self):
        assert set(PRESET_KEYS) <= set(BUILTIN_PRESETS.keys())
        assert len(BUILTIN_PRESETS) >= 5

    @pytest.mark.parametrize("key", PRESET_KEYS)
    def test_has_required_attributes(self, key):
        p = BUILTIN_PRESETS[key]
        assert p.bg_color and p.frame_color and p.text_color and p.stroke_color
        assert p.font and p.text_pos and p.align
        assert p.caption_category
        assert len(p.main_bg) == 4

    @pytest.mark.parametrize("key", PRESET_KEYS)
    def test_overrides_shape(self, key):
        ov = preset_overrides(key)
        for k in ("bg_color", "frame_color", "text_color", "stroke_color", "font", "text_pos", "align"):
            assert k in ov

    @pytest.mark.parametrize("key", PRESET_KEYS)
    def test_decorations_valid(self, key):
        from app.services.stamp_templates import DECORATIONS
        for d in preset_decorations(key):
            assert d["type"] in DECORATIONS

    def test_unknown_preset(self):
        assert preset_overrides("nope") is None
        assert preset_decorations("nope") == []
        assert preset_main_bg("nope") is None


class TestPresetRendering:
    @pytest.fixture
    def photo(self, tmp_path):
        p = tmp_path / "p.jpg"
        Image.new("RGB", (300, 400), (170, 150, 120)).save(p, "JPEG")
        return p

    @pytest.mark.parametrize("key", PRESET_KEYS)
    def test_preset_renders(self, key, photo):
        cfg = BUILTIN_PRESETS[key]
        spec = StampItemSpec(position=1, photo_path=str(photo), caption="ありがとう",
                             style=cfg.base_template, text_style=cfg.text_style,
                             overrides=preset_overrides(key), decorations=preset_decorations(key))
        img = render_preview(spec)
        assert img.size == (320, 310) and img.mode == "RGBA"

    def test_presets_differ_from_each_other(self, photo):
        imgs = {}
        for key in PRESET_KEYS:
            cfg = BUILTIN_PRESETS[key]
            spec = StampItemSpec(position=1, photo_path=str(photo), caption="C",
                                 style=cfg.base_template, text_style=cfg.text_style,
                                 overrides=preset_overrides(key), decorations=preset_decorations(key))
            imgs[key] = list(render_preview(spec).getdata())
        # at least pastel vs business should differ
        assert imgs["pastel_pop"] != imgs["business_clean"]

    def test_bg_color_applied(self, photo):
        cfg = BUILTIN_PRESETS["business_clean"]   # solid bg, no gradient
        spec = StampItemSpec(position=1, photo_path=str(photo), caption="",
                             style="simple_circle", text_style="pop",
                             overrides=preset_overrides("business_clean"))
        img = render_preview(spec).convert("RGBA")
        # top-left corner should be the (opaque) preset background, not transparent
        assert img.getpixel((2, 2))[3] == 255

    def test_preview_equals_output(self, photo, tmp_path):
        key = "celebration_party"
        cfg = BUILTIN_PRESETS[key]
        ov, deco = preset_overrides(key), preset_decorations(key)
        spec = StampItemSpec(position=1, photo_path=str(photo), caption="C",
                             style=cfg.base_template, text_style=cfg.text_style,
                             overrides=ov, decorations=deco)
        preview = render_preview(spec)
        specs = [StampItemSpec(position=i + 1, photo_path=str(photo), caption="C",
                               style=cfg.base_template, text_style=cfg.text_style,
                               overrides=ov, decorations=deco) for i in range(8)]
        summary = generate_stamp_set(specs, tmp_path / "out", set_name="X",
                                     main_bg=preset_main_bg(key))
        gen = Image.open(summary.results[0].sticker_path).convert("RGBA")
        diff = np.abs(np.asarray(preview).astype(int) - np.asarray(gen).astype(int)).mean()
        assert diff == 0.0

    def test_main_png_uses_preset_bg(self, photo, tmp_path):
        key = "pastel_pop"
        cfg = BUILTIN_PRESETS[key]
        specs = [StampItemSpec(position=i + 1, photo_path=str(photo), caption="C",
                               style=cfg.base_template, text_style=cfg.text_style,
                               overrides=preset_overrides(key)) for i in range(8)]
        summary = generate_stamp_set(specs, tmp_path / "out", set_name="X",
                                     main_bg=preset_main_bg(key))
        main = Image.open(Path(summary.set_output_dir) / "main.png").convert("RGBA")
        assert main.getpixel((2, 2)) == preset_main_bg(key)


# ---------------------------------------------------------------------------
# Route: apply built-in preset to the whole set
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


class TestApplyBuiltinPreset:
    def test_apply_sets_all_items(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        r = client.post(f"/stamps/{sid}/apply_builtin_preset", data={"preset_key": "pastel_pop"})
        assert r.status_code == 302
        with app_with_photos.app_context():
            from app.db import get_db
            db = get_db()
            rows = db.execute("SELECT style_json, item_template FROM stamp_items WHERE set_id=?", (sid,)).fetchall()
            for row in rows:
                ov = json.loads(row["style_json"])
                assert ov["frame_color"] == list(BUILTIN_PRESETS["pastel_pop"].frame_color)
            s = db.execute("SELECT preset_key, text_style FROM stamp_sets WHERE id=?", (sid,)).fetchone()
            assert s["preset_key"] == "pastel_pop"

    def test_apply_sets_decorations(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        client.post(f"/stamps/{sid}/apply_builtin_preset", data={"preset_key": "celebration_party"})
        with app_with_photos.app_context():
            from app.db import get_db
            row = get_db().execute(
                "SELECT decoration_json FROM stamp_items WHERE set_id=? AND position=1", (sid,)).fetchone()
            decos = json.loads(row["decoration_json"])
            assert decos and decos[0]["type"] == "star"

    def test_invalid_preset_noop(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        r = client.post(f"/stamps/{sid}/apply_builtin_preset", data={"preset_key": "bogus"})
        assert r.status_code == 302
        with app_with_photos.app_context():
            from app.db import get_db
            s = get_db().execute("SELECT preset_key FROM stamp_sets WHERE id=?", (sid,)).fetchone()
            assert s["preset_key"] is None

    def test_generate_with_preset_uses_bg(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        client.post(f"/stamps/{sid}/apply_builtin_preset", data={"preset_key": "business_clean"})
        client.post(f"/stamps/{sid}/generate")
        with app_with_photos.app_context():
            from app.db import get_db
            out = get_db().execute("SELECT output_dir FROM stamp_sets WHERE id=?", (sid,)).fetchone()["output_dir"]
        main = Image.open(Path(out) / "main.png").convert("RGBA")
        assert main.getpixel((2, 2)) == preset_main_bg("business_clean")

    def test_detail_lists_presets(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        html = client.get(f"/stamps/{sid}").data.decode("utf-8")
        for key in PRESET_KEYS:
            assert key in html
