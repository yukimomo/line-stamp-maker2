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
from .services.stamp_generator import StampItemSpec, generate_stamp_set
from .services.validator import validate_stamp_set
from .services.stamp_templates import TEMPLATES, auto_select_template
from .services.stamp_themes import THEMES, assign_captions_to_photos
from .services.text_styles import TEXT_STYLES

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
    )


@bp.route("/stamps", methods=["POST"])
def create_set():
    """
    Create a set from a chosen theme + 8 photos.
    Templates and captions are auto-assigned from the theme; the user
    refines them on the detail (set-preview) page.
    """
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    theme = request.form.get("theme", "simple_icon")
    if theme not in THEMES:
        theme = "simple_icon"
    cfg = THEMES[theme]

    selected_paths: list[str] = []
    for i in range(1, 9):
        path = request.form.get(f"photo_{i}", "").strip()
        if path:
            selected_paths.append(path)

    error = None
    if not name:
        error = "セット名を入力してください"
    elif len(selected_paths) < 8:
        error = f"写真を8枚選択してください（現在 {len(selected_paths)} 枚）"

    if error:
        return (
            render_template("new.html", photos=_get_photos(),
                            THEMES=THEMES, error=error),
            400,
        )

    # Build photo dicts (with analysis metadata) for caption auto-assignment
    all_photos = {p["path"]: p for p in _get_photos()}
    selected_photos = [all_photos.get(p, {"path": p}) for p in selected_paths[:8]]
    captions = assign_captions_to_photos(selected_photos, theme)

    db = get_db()
    cur = db.execute(
        "INSERT INTO stamp_sets (name, description, status, theme, style, text_style, updated_at) "
        "VALUES (?,?,?,?,?,?, datetime('now','localtime'))",
        (name, description, "draft", theme, cfg.templates[0], cfg.text_style),
    )
    set_id = cur.lastrowid

    for i, photo in enumerate(selected_photos):
        db.execute(
            "INSERT INTO stamp_items (set_id, position, photo_path, caption, item_template) "
            "VALUES (?,?,?,?,?)",
            (set_id, i + 1, photo["path"], captions[i], cfg.templates[i]),
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

    items = db.execute(
        "SELECT * FROM stamp_items WHERE set_id = ? ORDER BY position", (set_id,)
    ).fetchall()

    validation = None
    if stamp_set["status"] in ("generated", "partial") and stamp_set["output_dir"]:
        try:
            item_dicts = [dict(i) for i in items]
            report = validate_stamp_set(Path(stamp_set["output_dir"]), items=item_dicts)
            validation = {"is_valid": report.is_valid,
                          "errors": report.errors, "warnings": report.warnings}
        except Exception:
            pass

    return render_template(
        "detail.html",
        stamp_set=stamp_set,
        items=items,
        validation=validation,
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
        db.execute(
            "UPDATE stamp_items SET caption=?, item_template=? WHERE id=?",
            (caption, tmpl, item["id"]),
        )
    _touch(db, set_id)
    db.commit()
    return redirect(url_for("stamps.detail", set_id=set_id))


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
    """Reorder slots. Expects JSON: {"order": [pos1, pos2, ... pos8]}."""
    db = get_db()
    data = request.get_json(silent=True) or {}
    order = data.get("order", [])
    if sorted(order) != list(range(1, 9)):
        return jsonify({"ok": False, "error": "order must be a permutation of 1..8"}), 400

    rows = db.execute(
        "SELECT position, photo_path, caption, item_template FROM stamp_items WHERE set_id=?",
        (set_id,),
    ).fetchall()
    by_pos = {r["position"]: r for r in rows}

    # Assign new positions: order[k] is the OLD position that should become slot k+1
    for new_pos, old_pos in enumerate(order, start=1):
        src = by_pos[old_pos]
        db.execute(
            "UPDATE stamp_items SET photo_path=?, caption=?, item_template=? "
            "WHERE set_id=? AND position=?",
            (src["photo_path"], src["caption"], src["item_template"], set_id, new_pos),
        )
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
        db.execute(
            "UPDATE stamp_items SET sticker_path=?, preview_path=?, error_message=? WHERE set_id=? AND position=?",
            (
                result.sticker_path,
                result.preview_path,
                result.error if not result.success else None,
                set_id, result.position,
            ),
        )

    new_status = "generated" if summary.success_count >= 8 else "partial"
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
