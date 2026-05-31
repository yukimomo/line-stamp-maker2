"""Tests for free text/frame/decoration design overrides and presets."""

from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.services.stamp_generator import StampItemSpec, render_preview, generate_stamp_set
from app.services.text_styles import add_caption, FONT_CHOICES
from app.services.stamp_templates import apply_template, DECORATIONS
from app.services.circle_crop import circular_crop_smart


def _photo(tmp_path: Path) -> Path:
    p = tmp_path / "p.jpg"
    rng = np.random.default_rng(3)
    Image.fromarray(rng.integers(60, 200, (400, 320, 3), dtype=np.uint8)).save(p, "JPEG")
    return p


def _circle():
    rng = np.random.default_rng(3)
    img = Image.fromarray(rng.integers(60, 200, (400, 320, 3), dtype=np.uint8))
    return circular_crop_smart(img, size=220)


# ---------------------------------------------------------------------------
# Text overrides
# ---------------------------------------------------------------------------

class TestTextOverrides:
    def _base(self):
        return Image.new("RGBA", (320, 310), (120, 120, 120, 255))

    def test_no_override_matches_preset(self):
        a = add_caption(self._base(), "了解", style="pop")
        b = add_caption(self._base(), "了解", style="pop", overrides=None)
        assert list(a.getdata()) == list(b.getdata())

    def test_text_color_changes_pixels(self):
        a = add_caption(self._base(), "了解", style="pop")
        b = add_caption(self._base(), "了解", style="pop",
                        overrides={"text_color": [255, 0, 200]})
        assert list(a.getdata()) != list(b.getdata())

    def test_stroke_width_override(self):
        thin = add_caption(self._base(), "了解", style="pop", overrides={"stroke_width": 1})
        thick = add_caption(self._base(), "了解", style="pop", overrides={"stroke_width": 12})
        assert list(thin.getdata()) != list(thick.getdata())

    def test_position_top_vs_bottom(self):
        top = add_caption(self._base(), "了解", style="pop", overrides={"text_pos": "top"})
        bot = add_caption(self._base(), "了解", style="pop", overrides={"text_pos": "bottom"})
        assert list(top.getdata()) != list(bot.getdata())

    def test_align_override(self):
        left = add_caption(self._base(), "了解です", style="pop", overrides={"align": "left"})
        right = add_caption(self._base(), "了解です", style="pop", overrides={"align": "right"})
        assert list(left.getdata()) != list(right.getdata())

    def test_font_override_saved_and_used(self):
        # All font choices should render without error
        for fam in FONT_CHOICES:
            img = add_caption(self._base(), "ありがとう", style="pop", overrides={"font": fam})
            assert isinstance(img, Image.Image)

    def test_size_same(self):
        out = add_caption(self._base(), "了解", style="pop",
                          overrides={"text_color": [0, 0, 0], "font_size": 30})
        assert out.size == (320, 310)


# ---------------------------------------------------------------------------
# Frame overrides
# ---------------------------------------------------------------------------

class TestFrameOverrides:
    def test_frame_color_changes_pixels(self):
        c = _circle()
        a = apply_template(c, "simple_circle", caption="", seed=0)
        b = apply_template(c, "simple_circle", caption="", seed=0,
                           overrides={"frame_color": [255, 0, 0]})
        assert list(a.getdata()) != list(b.getdata())

    def test_frame_width_changes_pixels(self):
        c = _circle()
        a = apply_template(c, "simple_circle", caption="", seed=0,
                           overrides={"frame_width": 6})
        b = apply_template(c, "simple_circle", caption="", seed=0,
                           overrides={"frame_width": 28})
        assert list(a.getdata()) != list(b.getdata())

    def test_frame_override_keeps_rgba_and_spec(self):
        c = _circle()
        out = apply_template(c, "cool_badge", caption="OK", seed=0,
                             overrides={"frame_color": [10, 200, 90], "outer_width": 6})
        assert out.mode == "RGBA"
        assert out.width <= 370 and out.height <= 320


# ---------------------------------------------------------------------------
# Decorations
# ---------------------------------------------------------------------------

class TestDecorations:
    @pytest.mark.parametrize("dtype", list(DECORATIONS.keys()))
    def test_each_decoration_renders(self, dtype):
        c = _circle()
        out = apply_template(c, "simple_circle", caption="", seed=0,
                             decorations=[{"type": dtype, "x": 0.5, "y": 0.3,
                                           "size": 30, "rotation": 20, "color": [255, 80, 120]}])
        assert out.mode == "RGBA"

    def test_decoration_changes_pixels(self):
        c = _circle()
        a = apply_template(c, "simple_circle", caption="", seed=0)
        b = apply_template(c, "simple_circle", caption="", seed=0,
                           decorations=[{"type": "heart", "x": 0.5, "y": 0.5, "size": 40}])
        assert list(a.getdata()) != list(b.getdata())

    def test_invisible_decoration_skipped(self):
        c = _circle()
        a = apply_template(c, "simple_circle", caption="", seed=0)
        b = apply_template(c, "simple_circle", caption="", seed=0,
                           decorations=[{"type": "heart", "x": 0.5, "y": 0.5,
                                         "size": 40, "visible": False}])
        assert list(a.getdata()) == list(b.getdata())


# ---------------------------------------------------------------------------
# preview == output with overrides + decorations
# ---------------------------------------------------------------------------

class TestPreviewMatchesOutput:
    def test_pixel_identical(self, tmp_path):
        photo = _photo(tmp_path)
        ov = {"text_color": [255, 80, 160], "frame_color": [255, 200, 40],
              "frame_width": 20, "stroke_width": 8}
        deco = [{"type": "star", "x": 0.8, "y": 0.2, "size": 26, "rotation": 0,
                 "color": [255, 210, 0]}]
        spec = StampItemSpec(position=1, photo_path=str(photo), caption="C",
                             style="pop_star", text_style="pop",
                             overrides=ov, decorations=deco)
        preview = render_preview(spec)

        out_dir = tmp_path / "out"
        specs = [StampItemSpec(position=i + 1, photo_path=str(photo), caption="C",
                               style="pop_star", text_style="pop",
                               overrides=ov, decorations=deco) for i in range(8)]
        summary = generate_stamp_set(specs, out_dir, theme_name="cute_daily", set_name="X")
        generated = Image.open(summary.results[0].sticker_path).convert("RGBA")

        diff = np.abs(np.asarray(preview).astype(int) - np.asarray(generated).astype(int)).mean()
        assert diff == 0.0, f"preview != output (mean diff {diff})"


# ---------------------------------------------------------------------------
# Routes: per-item design save, bulk design, presets
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


def _make_set(client, app):
    data = {"name": "S", "theme": "family_pop", "stamp_count": 8}
    for i, p in enumerate(app._photos, start=1):
        data[f"photo_{i}"] = p
    client.post("/stamps", data=data)
    with app.app_context():
        from app.db import get_db
        return get_db().execute("SELECT id FROM stamp_sets ORDER BY id DESC LIMIT 1").fetchone()["id"]


class TestDesignRoutes:
    def test_save_design_persists(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        r = client.post(f"/stamps/{sid}/item/1/design", json={
            "overrides": {"text_color": [255, 0, 0]},
            "decorations": [{"type": "heart", "x": 0.5, "y": 0.5, "size": 30}],
        })
        assert r.status_code == 200 and r.get_json()["ok"]
        with app_with_photos.app_context():
            from app.db import get_db
            row = get_db().execute(
                "SELECT style_json, decoration_json FROM stamp_items WHERE set_id=? AND position=1",
                (sid,)).fetchone()
            assert json.loads(row["style_json"])["text_color"] == [255, 0, 0]
            assert json.loads(row["decoration_json"])[0]["type"] == "heart"

    def test_design_bulk_applies_to_all(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        r = client.post(f"/stamps/{sid}/design_bulk", json={"overrides": {"text_color": [0, 128, 255]}})
        assert r.status_code == 200
        with app_with_photos.app_context():
            from app.db import get_db
            rows = get_db().execute(
                "SELECT style_json FROM stamp_items WHERE set_id=?", (sid,)).fetchall()
            assert all(json.loads(r["style_json"])["text_color"] == [0, 128, 255] for r in rows)

    def test_preview_with_overrides_returns_png(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        r = client.get(f"/stamps/{sid}/preview", query_string={
            "photo": app_with_photos._photos[0], "caption": "色", "template": "heart",
            "style": json.dumps({"text_color": [255, 0, 0]}),
            "deco": json.dumps([{"type": "star", "x": 0.5, "y": 0.3, "size": 24}]),
        })
        assert r.status_code == 200 and r.mimetype == "image/png"


class TestPresets:
    def test_save_and_list_preset(self, client, app_with_photos):
        r = client.post("/presets", json={"name": "ピンク", "overrides": {"text_color": [255, 0, 200]}})
        assert r.status_code == 200 and r.get_json()["ok"]
        lst = client.get("/presets").get_json()
        assert any(p["name"] == "ピンク" for p in lst)

    def test_preset_requires_name(self, client, app_with_photos):
        r = client.post("/presets", json={"overrides": {}})
        assert r.status_code == 400

    def test_apply_preset_to_set(self, client, app_with_photos):
        sid = _make_set(client, app_with_photos)
        pid = client.post("/presets", json={"name": "青", "overrides": {"frame_color": [0, 0, 255]}}).get_json()["id"]
        client.post(f"/stamps/{sid}/apply_preset", data={"preset_id": pid})
        with app_with_photos.app_context():
            from app.db import get_db
            rows = get_db().execute("SELECT style_json FROM stamp_items WHERE set_id=?", (sid,)).fetchall()
            assert all(json.loads(r["style_json"])["frame_color"] == [0, 0, 255] for r in rows)


class TestBackCompat:
    def test_existing_text_styles_still_work(self):
        from app.services.text_styles import TEXT_STYLES
        base = Image.new("RGBA", (320, 310), (100, 100, 100, 255))
        for style in TEXT_STYLES:
            out = add_caption(base.copy(), "ありがとう", style=style)
            assert isinstance(out, Image.Image)
