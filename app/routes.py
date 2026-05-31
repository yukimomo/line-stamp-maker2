"""Flask routes for LINE stamp web app."""

from __future__ import annotations
from io import BytesIO
from pathlib import Path

from flask import (
    Blueprint, abort, current_app, jsonify, redirect,
    render_template, request, send_file, url_for,
)

from .db import get_db
from .services.photo_loader import load_adopted_photos
from .services.stamp_generator import (
    StampItemSpec, generate_stamp_set, regenerate_item, finalize_set, render_preview,
)
from .services.validator import validate_stamp_set
from .services.stamp_templates import TEMPLATES, auto_select_template
from .services.stamp_themes import THEMES, assign_captions_to_photos
from .services.text_styles import TEXT_STYLES
from .db import ALLOWED_COUNTS
import io
import json

bp = Blueprint("stamps", __name__)

CAPTION_TEMPLATES = {
    "日常":   ["了解", "ありがとう", "おつかれ", "OK", "ごめん", "いってきます", "おやすみ", "最高"],
    "仕事":   ["確認します", "承知しました", "お願いします", "ありがとうございます", "よろしく", "お疲れ様", "頑張ります", "了解です"],
    "家族":   ["いってきます", "ただいま", "おつかれ", "ありがとう", "大好き", "一緒に行こう", "おやすみ", "いただきます"],
}
ALL_TEMPLATES = list({t for ts in CAPTION_TEMPLATES.values() for t in ts})


def _get_photos() -> list[dict]:
    return load_adopted_photos(
        current_app.config["PHOTO_SELECTOR_MANIFEST"],
        current_app.config["PHOTO_SELECTOR_SELECTED_DIR"],
    )


def _touch(db, set_id: int) -> None:
    db.execute(
        "UPDATE stamp_sets SET updated_at = datetime('now','localtime') WHERE id = ?",
        (set_id,),
    )


# ---------------------------------------------------------------------------
# List / create
# ---------------------------------------------------------------------------

@bp.route("/")
def index():
    db = get_db()
    rows = db.execute(
        "SELECT id, name, description, created_at, updated_at, status, zip_path, theme "
        "FROM stamp_sets ORDER BY updated_at DESC"
    ).fetchall()
    return render_template("index.html", stamp_sets=rows, THEMES=THEMES)


@bp.route("/stamps/new")
def new_set():
    return render_template(
        "new.html",
        photos=_get_photos(),
        THEMES=THEMES,
        ALLOWED_COUNTS=ALLOWED_COUNTS,
    )


@bp.route("/stamps", methods=["POST"])
def create_set():
    """
    Create a set from a chosen theme, stamp count (8/16/24/32/40), and photos.
    Photos shorter than the count are cycled. Templates and captions are
    auto-assigned; the user refines them on the detail (set-preview) page.
    """
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    theme = request.form.get("theme", "simple_icon")
    if theme not in THEMES:
        theme = "simple_icon"
    count = request.form.get("stamp_count", type=int) or 8
    if count not in ALLOWED_COUNTS:
        count = 8
    cfg = THEMES[theme]

    # Collect however many photos were chosen (max = count)
    selected_paths: list[str] = []
    for i in range(1, count + 1):
        path = request.form.get(f"photo_{i}", "").strip()
        if path:
            selected_paths.append(path)

    error = None
    if not name:
        error = "セット名を入力してください"
    elif len(selected_paths) == 0:
        error = "写真を1枚以上選択してください"

    if error:
        return (
            render_template("new.html", photos=_get_photos(),
                            THEMES=THEMES, ALLOWED_COUNTS=ALLOWED_COUNTS, error=error),
            400,
        )

    all_photos = {p["path"]: p for p in _get_photos()}
    # Cycle the chosen photos up to `count`
    chosen = [all_photos.get(p, {"path": p}) for p in selected_paths]
    slot_photos = [chosen[i % len(chosen)] for i in range(count)]
    captions = assign_captions_to_photos(slot_photos, theme, count=count)

    templates: list[str] = []
    for i, photo in enumerate(slot_photos):
        risks = (photo.get("analysis") or {}).get("risks") or {}
        auto = auto_select_template(photo, is_dark=bool(risks.get("dark")))
        templates.append(auto if auto != "simple_circle" else cfg.templates[i % len(cfg.templates)])

    db = get_db()
    cur = db.execute(
        "INSERT INTO stamp_sets (name, description, status, theme, style, text_style, "
        "stamp_count, updated_at) VALUES (?,?,?,?,?,?,?, datetime('now','localtime'))",
        (name, description, "draft", theme, cfg.templates[0], cfg.text_style, count),
    )
    set_id = cur.lastrowid

    for i, photo in enumerate(slot_photos):
        db.execute(
            "INSERT INTO stamp_items (set_id, position, photo_path, caption, item_template) "
            "VALUES (?,?,?,?,?)",
            (set_id, i + 1, photo["path"], captions[i], templates[i]),
        )
    db.commit()
    return redirect(url_for("stamps.detail", set_id=set_id))


# ---------------------------------------------------------------------------
# Detail / set preview
# ---------------------------------------------------------------------------

@bp.route("/stamps/<int:set_id>")
def detail(set_id: int):
    db = get_db()
    stamp_set = db.execute("SELECT * FROM stamp_sets WHERE id = ?", (set_id,)).fetchone()
    if stamp_set is None:
        abort(404)

    rows = db.execute(
        "SELECT * FROM stamp_items WHERE set_id = ? ORDER BY position", (set_id,)
    ).fetchall()
    # Parse per-item warnings JSON into a list for the template
    items = []
    for r in rows:
        d = dict(r)
        try:
            d["warning_list"] = json.loads(r["warnings"]) if r["warnings"] else []
        except (ValueError, TypeError):
            d["warning_list"] = []
        items.append(d)

    validation = None
    if stamp_set["status"] in ("generated", "partial") and stamp_set["output_dir"]:
        try:
            report = validate_stamp_set(
                Path(stamp_set["output_dir"]), items=items,
                required_count=stamp_set["stamp_count"] or 8,
            )
            validation = {"is_valid": report.is_valid,
                          "errors": report.errors, "warnings": report.warnings}
        except Exception:
            pass

    return render_template(
        "detail.html",
        stamp_set=stamp_set,
        items=items,
        validation=validation,
        ALLOWED_COUNTS=ALLOWED_COUNTS,
        TEMPLATES=TEMPLATES,
        TEXT_STYLES=TEXT_STYLES,
        THEMES=THEMES,
        caption_templates=CAPTION_TEMPLATES,
    )


# ---------------------------------------------------------------------------
# Inline editing (set preview)
# ---------------------------------------------------------------------------

@bp.route("/stamps/<int:set_id>/edit", methods=["POST"])
def edit_set(set_id: int):
    """Save inline edits: captions, per-item templates, set name/description/text_style."""
    db = get_db()
    stamp_set = db.execute("SELECT id FROM stamp_sets WHERE id = ?", (set_id,)).fetchone()
    if stamp_set is None:
        abort(404)

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    text_style = request.form.get("text_style", "bubble")
    if text_style not in TEXT_STYLES:
        text_style = "bubble"
    if name:
        db.execute(
            "UPDATE stamp_sets SET name=?, description=?, text_style=? WHERE id=?",
            (name, description, text_style, set_id),
        )

    items = db.execute(
        "SELECT id, position FROM stamp_items WHERE set_id = ?", (set_id,)
    ).fetchall()
    for item in items:
        pos = item["position"]
        caption = request.form.get(f"caption_{pos}", "").strip()
        tmpl = request.form.get(f"template_{pos}", "")
        if tmpl not in TEMPLATES:
            tmpl = "simple_circle"
        zoom = _clamp(request.form.get(f"zoom_{pos}", type=float), 0.5, 2.5, 1.0)
        ox = _clamp(request.form.get(f"offset_x_{pos}", type=float), -0.5, 0.5, 0.0)
        oy = _clamp(request.form.get(f"offset_y_{pos}", type=float), -0.5, 0.5, 0.0)
        bri = _clamp(request.form.get(f"brightness_{pos}", type=float), -1.0, 1.0, 0.0)
        db.execute(
            "UPDATE stamp_items SET caption=?, item_template=?, zoom=?, offset_x=?, "
            "offset_y=?, brightness=? WHERE id=?",
            (caption, tmpl, zoom, ox, oy, bri, item["id"]),
        )
    _touch(db, set_id)
    db.commit()
    return redirect(url_for("stamps.detail", set_id=set_id))


def _clamp(val, lo: float, hi: float, default: float) -> float:
    if val is None:
        return default
    return max(lo, min(hi, val))


@bp.route("/stamps/<int:set_id>/swap_photo", methods=["POST"])
def swap_photo(set_id: int):
    """Replace the photo of a single slot (AJAX)."""
    db = get_db()
    position = request.form.get("position", type=int)
    new_path = request.form.get("photo_path", "").strip()
    if not position or not new_path:
        return jsonify({"ok": False, "error": "invalid params"}), 400

    db.execute(
        "UPDATE stamp_items SET photo_path=? WHERE set_id=? AND position=?",
        (new_path, set_id, position),
    )
    _touch(db, set_id)
    db.commit()
    return jsonify({"ok": True})


@bp.route("/stamps/<int:set_id>/reorder", methods=["POST"])
def reorder(set_id: int):
    """Reorder slots. Expects JSON {"order": [old_pos,...]} (a permutation)."""
    db = get_db()
    data = request.get_json(silent=True) or {}
    order = data.get("order", [])

    rows = db.execute(
        "SELECT * FROM stamp_items WHERE set_id=?", (set_id,)
    ).fetchall()
    valid = sorted(r["position"] for r in rows)
    if sorted(order) != valid or not valid:
        return jsonify({"ok": False, "error": "order must be a permutation of existing slots"}), 400

    by_pos = {r["position"]: dict(r) for r in rows}
    # Two-phase to avoid UNIQUE(set_id, position) collisions:
    # 1) move everything to negative temp positions
    for r in rows:
        db.execute("UPDATE stamp_items SET position=? WHERE id=?",
                   (-r["position"], r["id"]))
    # 2) write final positions (carry all per-item fields via id)
    for new_pos, old_pos in enumerate(order, start=1):
        db.execute("UPDATE stamp_items SET position=? WHERE id=?",
                   (new_pos, by_pos[old_pos]["id"]))
    _touch(db, set_id)
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

@bp.route("/stamps/<int:set_id>/generate", methods=["POST"])
def generate(set_id: int):
    db = get_db()
    stamp_set = db.execute("SELECT * FROM stamp_sets WHERE id = ?", (set_id,)).fetchone()
    if stamp_set is None:
        abort(404)

    items = db.execute(
        "SELECT * FROM stamp_items WHERE set_id = ? ORDER BY position", (set_id,)
    ).fetchall()

    text_style = stamp_set["text_style"] or "bubble"
    theme = stamp_set["theme"] or "simple_icon"
    default_tmpl = stamp_set["style"] or "simple_circle"

    output_dir = Path(current_app.config["OUTPUT_DIR"]) / f"set_{set_id:04d}"
    specs = [
        StampItemSpec(
            position=i["position"],
            photo_path=i["photo_path"],
            caption=i["caption"],
            style=(i["item_template"] or default_tmpl),
            text_style=text_style,
            zoom=i["zoom"] if i["zoom"] is not None else 1.0,
            offset_x=i["offset_x"] if i["offset_x"] is not None else 0.0,
            offset_y=i["offset_y"] if i["offset_y"] is not None else 0.0,
            brightness=i["brightness"] if i["brightness"] is not None else 0.0,
        )
        for i in items
    ]

    db.execute(
        "UPDATE stamp_sets SET status = 'generating', output_dir = ? WHERE id = ?",
        (str(output_dir), set_id),
    )
    db.commit()

    try:
        summary = generate_stamp_set(
            specs, output_dir, theme_name=theme, set_name=stamp_set["name"]
        )
    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {exc}"
        for item in items:
            db.execute(
                "UPDATE stamp_items SET error_message = ? WHERE set_id = ? AND position = ? AND sticker_path IS NULL",
                (err_msg, set_id, item["position"]),
            )
        db.execute("UPDATE stamp_sets SET status = 'error' WHERE id = ?", (set_id,))
        db.commit()
        return redirect(url_for("stamps.detail", set_id=set_id))

    for result in summary.results:
        warnings_json = json.dumps(result.warnings, ensure_ascii=False) if result.warnings else None
        db.execute(
            "UPDATE stamp_items SET sticker_path=?, preview_path=?, warnings=?, error_message=? "
            "WHERE set_id=? AND position=?",
            (
                result.sticker_path,
                result.preview_path,
                warnings_json,
                result.error if not result.success else None,
                set_id, result.position,
            ),
        )

    need = stamp_set["stamp_count"] or len(items)
    new_status = "generated" if summary.success_count >= need else "partial"
    db.execute(
        "UPDATE stamp_sets SET status=?, zip_path=? WHERE id=?",
        (new_status, summary.zip_path, set_id),
    )
    _touch(db, set_id)
    db.commit()
    return redirect(url_for("stamps.detail", set_id=set_id))


# ---------------------------------------------------------------------------
# Download / reset / delete
# ---------------------------------------------------------------------------

@bp.route("/stamps/<int:set_id>/download")
def download(set_id: int):
    db = get_db()
    stamp_set = db.execute("SELECT zip_path, name FROM stamp_sets WHERE id=?", (set_id,)).fetchone()
    if stamp_set is None:
        abort(404)
    zip_path = stamp_set["zip_path"]
    if not zip_path or not Path(zip_path).exists():
        abort(404)
    return send_file(zip_path, as_attachment=True,
                     download_name=f"line_stamps_{stamp_set['name']}.zip")


@bp.route("/stamps/<int:set_id>/reset", methods=["POST"])
def reset_set(set_id: int):
    db = get_db()
    db.execute(
        "UPDATE stamp_sets SET status='draft' WHERE id=? AND status IN ('generating','error')",
        (set_id,),
    )
    db.commit()
    return redirect(url_for("stamps.detail", set_id=set_id))


@bp.route("/stamps/<int:set_id>/delete", methods=["POST"])
def delete_set(set_id: int):
    db = get_db()
    db.execute("DELETE FROM stamp_sets WHERE id=?", (set_id,))
    db.commit()
    return redirect(url_for("stamps.index"))


# ---------------------------------------------------------------------------
# Count change / item management / bulk edit / regenerate / preview / export
# ---------------------------------------------------------------------------

@bp.route("/stamps/<int:set_id>/count", methods=["POST"])
def change_count(set_id: int):
    """Change the stamp count. Adds slots (cycling photos) or trims extras."""
    db = get_db()
    stamp_set = db.execute("SELECT * FROM stamp_sets WHERE id=?", (set_id,)).fetchone()
    if stamp_set is None:
        abort(404)
    new_count = request.form.get("stamp_count", type=int)
    if new_count not in ALLOWED_COUNTS:
        return redirect(url_for("stamps.detail", set_id=set_id))

    rows = db.execute(
        "SELECT * FROM stamp_items WHERE set_id=? ORDER BY position", (set_id,)
    ).fetchall()
    current = len(rows)
    theme = stamp_set["theme"] or "simple_icon"
    cfg = THEMES.get(theme, THEMES["simple_icon"])

    if new_count > current and rows:
        # Add slots, cycling existing photos + theme captions/templates
        base_photos = [dict(r) for r in rows]
        extra = new_count - current
        captions = assign_captions_to_photos(base_photos, theme, count=new_count)
        for k in range(extra):
            pos = current + k + 1
            src = base_photos[(current + k) % len(base_photos)]
            tmpl = cfg.templates[(pos - 1) % len(cfg.templates)]
            db.execute(
                "INSERT INTO stamp_items (set_id, position, photo_path, caption, item_template) "
                "VALUES (?,?,?,?,?)",
                (set_id, pos, src["photo_path"], captions[pos - 1], tmpl),
            )
    elif new_count < current:
        db.execute("DELETE FROM stamp_items WHERE set_id=? AND position>?",
                   (set_id, new_count))

    # Count change invalidates the generated output
    db.execute("UPDATE stamp_sets SET stamp_count=?, status='draft', zip_path=NULL WHERE id=?",
               (new_count, set_id))
    _touch(db, set_id)
    db.commit()
    return redirect(url_for("stamps.detail", set_id=set_id))


@bp.route("/stamps/<int:set_id>/item/<int:position>/delete", methods=["POST"])
def delete_item(set_id: int, position: int):
    """Delete one slot and renumber the rest."""
    db = get_db()
    db.execute("DELETE FROM stamp_items WHERE set_id=? AND position=?", (set_id, position))
    _renumber(db, set_id)
    new_count = db.execute(
        "SELECT COUNT(*) c FROM stamp_items WHERE set_id=?", (set_id,)
    ).fetchone()["c"]
    db.execute("UPDATE stamp_sets SET stamp_count=? WHERE id=?", (new_count, set_id))
    _touch(db, set_id)
    db.commit()
    return jsonify({"ok": True, "count": new_count})


@bp.route("/stamps/<int:set_id>/item/<int:position>/duplicate", methods=["POST"])
def duplicate_item(set_id: int, position: int):
    """Duplicate one slot, appended at the end."""
    db = get_db()
    src = db.execute(
        "SELECT * FROM stamp_items WHERE set_id=? AND position=?", (set_id, position)
    ).fetchone()
    if src is None:
        return jsonify({"ok": False}), 404
    maxpos = db.execute(
        "SELECT COALESCE(MAX(position),0) m FROM stamp_items WHERE set_id=?", (set_id,)
    ).fetchone()["m"]
    db.execute(
        "INSERT INTO stamp_items (set_id, position, photo_path, caption, item_template, "
        "zoom, offset_x, offset_y, brightness) VALUES (?,?,?,?,?,?,?,?,?)",
        (set_id, maxpos + 1, src["photo_path"], src["caption"], src["item_template"],
         src["zoom"], src["offset_x"], src["offset_y"], src["brightness"]),
    )
    db.execute("UPDATE stamp_sets SET stamp_count=? WHERE id=?", (maxpos + 1, set_id))
    _touch(db, set_id)
    db.commit()
    return jsonify({"ok": True, "count": maxpos + 1})


def _renumber(db, set_id: int) -> None:
    """Re-pack positions to 1..N with no gaps."""
    rows = db.execute(
        "SELECT id FROM stamp_items WHERE set_id=? ORDER BY position", (set_id,)
    ).fetchall()
    for r in rows:                       # park to negatives to avoid UNIQUE clash
        db.execute("UPDATE stamp_items SET position=-position WHERE id=?", (r["id"],))
    for i, r in enumerate(rows, start=1):
        db.execute("UPDATE stamp_items SET position=? WHERE id=?", (i, r["id"]))


@bp.route("/stamps/<int:set_id>/bulk", methods=["POST"])
def bulk_edit(set_id: int):
    """Apply text_style and/or template to all slots at once."""
    db = get_db()
    text_style = request.form.get("bulk_text_style", "")
    template = request.form.get("bulk_template", "")
    if text_style in TEXT_STYLES:
        db.execute("UPDATE stamp_sets SET text_style=? WHERE id=?", (text_style, set_id))
    if template in TEMPLATES:
        db.execute("UPDATE stamp_items SET item_template=? WHERE set_id=?", (template, set_id))
    _touch(db, set_id)
    db.commit()
    return redirect(url_for("stamps.detail", set_id=set_id))


@bp.route("/stamps/<int:set_id>/item/<int:position>/regenerate", methods=["POST"])
def regenerate_one(set_id: int, position: int):
    """
    Regenerate a single stamp. mode=template rotates to the next template;
    mode=caption re-suggests a theme caption. Photo stays the same.
    """
    db = get_db()
    stamp_set = db.execute("SELECT * FROM stamp_sets WHERE id=?", (set_id,)).fetchone()
    item = db.execute(
        "SELECT * FROM stamp_items WHERE set_id=? AND position=?", (set_id, position)
    ).fetchone()
    if stamp_set is None or item is None:
        abort(404)

    mode = request.form.get("mode", "template")
    text_style = stamp_set["text_style"] or "bubble"
    theme = stamp_set["theme"] or "simple_icon"
    tmpl = item["item_template"] or stamp_set["style"] or "simple_circle"
    caption = item["caption"]

    if mode == "template":
        keys = list(TEMPLATES.keys())
        tmpl = keys[(keys.index(tmpl) + 1) % len(keys)] if tmpl in keys else keys[0]
    elif mode == "caption":
        cfg = THEMES.get(theme, THEMES["simple_icon"])
        pool = [c for c in cfg.captions if c != caption] or cfg.captions
        import random as _r
        caption = _r.choice(pool)

    db.execute("UPDATE stamp_items SET item_template=?, caption=? WHERE id=?",
               (tmpl, caption, item["id"]))

    # If the set was already generated, re-render just this sticker + meta/zip
    if stamp_set["status"] in ("generated", "partial") and stamp_set["output_dir"]:
        spec = StampItemSpec(
            position=position, photo_path=item["photo_path"], caption=caption,
            style=tmpl, text_style=text_style,
            zoom=item["zoom"], offset_x=item["offset_x"],
            offset_y=item["offset_y"], brightness=item["brightness"],
        )
        out = Path(stamp_set["output_dir"])
        result = regenerate_item(spec, out)
        warns = json.dumps(result.warnings, ensure_ascii=False) if result.warnings else None
        db.execute(
            "UPDATE stamp_items SET sticker_path=?, preview_path=?, warnings=?, error_message=? WHERE id=?",
            (result.sticker_path, result.preview_path, warns,
             result.error if not result.success else None, item["id"]),
        )
        zip_path = finalize_set(out, theme_name=theme, set_name=stamp_set["name"])
        db.execute("UPDATE stamp_sets SET zip_path=? WHERE id=?", (zip_path, set_id))

    _touch(db, set_id)
    db.commit()
    return redirect(url_for("stamps.detail", set_id=set_id))


@bp.route("/stamps/<int:set_id>/preview")
def preview_item(set_id: int):
    """
    Live single-stamp preview (PNG), rendered from query params without saving.
    Params: photo, caption, template, text_style, zoom, offset_x, offset_y, brightness.
    """
    photo = request.args.get("photo", "")
    if not photo or not Path(photo).is_file():
        abort(404)
    spec = StampItemSpec(
        position=1,
        photo_path=photo,
        caption=request.args.get("caption", ""),
        style=request.args.get("template", "simple_circle"),
        text_style=request.args.get("text_style", "bubble"),
        zoom=_clamp(request.args.get("zoom", type=float), 0.5, 2.5, 1.0),
        offset_x=_clamp(request.args.get("offset_x", type=float), -0.5, 0.5, 0.0),
        offset_y=_clamp(request.args.get("offset_y", type=float), -0.5, 0.5, 0.0),
        brightness=_clamp(request.args.get("brightness", type=float), -1.0, 1.0, 0.0),
    )
    try:
        img = render_preview(spec)
    except Exception:
        abort(500)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@bp.route("/stamps/<int:set_id>/export")
def export_review(set_id: int):
    """Pre-export confirmation screen with the quality report."""
    db = get_db()
    stamp_set = db.execute("SELECT * FROM stamp_sets WHERE id=?", (set_id,)).fetchone()
    if stamp_set is None:
        abort(404)
    rows = db.execute(
        "SELECT * FROM stamp_items WHERE set_id=? ORDER BY position", (set_id,)
    ).fetchall()
    items = [dict(r) for r in rows]

    report = None
    if stamp_set["output_dir"]:
        rep = validate_stamp_set(
            Path(stamp_set["output_dir"]), items=items,
            required_count=stamp_set["stamp_count"] or 8,
        )
        report = {"is_valid": rep.is_valid, "errors": rep.errors, "warnings": rep.warnings}

    return render_template("export.html", stamp_set=stamp_set, items=items, report=report)


# ---------------------------------------------------------------------------
# Photo serving
# ---------------------------------------------------------------------------

_ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}


@bp.route("/photo")
def serve_photo():
    path_str = request.args.get("path", "")
    if not path_str:
        abort(400)
    p = Path(path_str)
    if not p.is_file() or p.suffix.lower() not in _ALLOWED_EXTS:
        abort(404)
    if p.suffix.lower() in (".heic", ".heif"):
        return _heic_to_jpeg(p)
    return send_file(str(p))


def _heic_to_jpeg(path: Path):
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        abort(500, "pillow-heif not installed")
    from PIL import Image
    img = Image.open(path).convert("RGB")
    buf = BytesIO()
    img.save(buf, "JPEG", quality=80)
    buf.seek(0)
    return send_file(buf, mimetype="image/jpeg")


@bp.route("/api/photos")
def api_photos():
    return jsonify(_get_photos())
