"""Flask routes for LINE stamp web app."""

from __future__ import annotations
import urllib.parse
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
from .services.character_processor import STYLES, EXPRESSIONS
from .services.text_styles import TEXT_STYLES

bp = Blueprint("stamps", __name__)

CAPTION_TEMPLATES = {
    "日常":   ["了解", "ありがとう", "おつかれ", "OK", "ごめん", "いってきます", "おやすみ", "最高"],
    "仕事":   ["確認します", "承知しました", "お願いします", "ありがとうございます", "よろしく", "お疲れ様", "頑張ります", "了解です"],
    "家族":   ["いってきます", "ただいま", "おつかれ", "ありがとう", "大好き", "一緒に行こう", "おやすみ", "いただきます"],
}
# Flat list for datalist
ALL_TEMPLATES = list({t for ts in CAPTION_TEMPLATES.values() for t in ts})


def _get_photos() -> list[dict]:
    return load_adopted_photos(
        current_app.config["PHOTO_SELECTOR_MANIFEST"],
        current_app.config["PHOTO_SELECTOR_SELECTED_DIR"],
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route("/")
def index():
    db = get_db()
    rows = db.execute(
        "SELECT id, name, description, created_at, status, zip_path, style FROM stamp_sets ORDER BY created_at DESC"
    ).fetchall()
    return render_template("index.html", stamp_sets=rows, STYLES=STYLES)


@bp.route("/stamps/new")
def new_set():
    return render_template(
        "new.html",
        photos=_get_photos(),
        caption_templates=CAPTION_TEMPLATES,
        all_templates=ALL_TEMPLATES,
        STYLES=STYLES,
        EXPRESSIONS=EXPRESSIONS,
        TEXT_STYLES=TEXT_STYLES,
    )


@bp.route("/stamps", methods=["POST"])
def create_set():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    style = request.form.get("style", "line_stamp")
    text_style = request.form.get("text_style", "bubble")
    expression = request.form.get("expression", "none")

    items: list[dict] = []
    for i in range(1, 9):
        path = request.form.get(f"photo_{i}", "").strip()
        caption = request.form.get(f"caption_{i}", "").strip()
        if path:
            items.append({"position": i, "photo_path": path, "caption": caption})

    error = None
    if not name:
        error = "セット名を入力してください"
    elif len(items) < 8:
        error = f"写真を8枚選択してください（現在 {len(items)} 枚）"
    if style not in STYLES:
        style = "line_stamp"
    if text_style not in TEXT_STYLES:
        text_style = "bubble"
    if expression not in EXPRESSIONS:
        expression = "none"

    if error:
        return (
            render_template("new.html", photos=_get_photos(),
                            caption_templates=CAPTION_TEMPLATES,
                            all_templates=ALL_TEMPLATES,
                            STYLES=STYLES, EXPRESSIONS=EXPRESSIONS,
                            TEXT_STYLES=TEXT_STYLES, error=error),
            400,
        )

    db = get_db()
    cur = db.execute(
        "INSERT INTO stamp_sets (name, description, status, style, text_style, expression) VALUES (?,?,?,?,?,?)",
        (name, description, "draft", style, text_style, expression),
    )
    set_id = cur.lastrowid
    for item in items:
        db.execute(
            "INSERT INTO stamp_items (set_id, position, photo_path, caption) VALUES (?,?,?,?)",
            (set_id, item["position"], item["photo_path"], item["caption"]),
        )
    db.commit()
    return redirect(url_for("stamps.detail", set_id=set_id))


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
            report = validate_stamp_set(Path(stamp_set["output_dir"]))
            validation = {"is_valid": report.is_valid,
                          "errors": report.errors, "warnings": report.warnings}
        except Exception:
            pass

    return render_template(
        "detail.html",
        stamp_set=stamp_set,
        items=items,
        validation=validation,
        STYLES=STYLES,
        EXPRESSIONS=EXPRESSIONS,
        TEXT_STYLES=TEXT_STYLES,
    )


@bp.route("/stamps/<int:set_id>/generate", methods=["POST"])
def generate(set_id: int):
    db = get_db()
    stamp_set = db.execute("SELECT * FROM stamp_sets WHERE id = ?", (set_id,)).fetchone()
    if stamp_set is None:
        abort(404)

    items = db.execute(
        "SELECT * FROM stamp_items WHERE set_id = ? ORDER BY position", (set_id,)
    ).fetchall()

    style = stamp_set["style"] or "line_stamp"
    text_style = stamp_set["text_style"] or "bubble"
    expression = stamp_set["expression"] or "none"

    output_dir = Path(current_app.config["OUTPUT_DIR"]) / f"set_{set_id:04d}"
    specs = [
        StampItemSpec(
            position=i["position"],
            photo_path=i["photo_path"],
            caption=i["caption"],
            style=style,
            text_style=text_style,
            expression=expression,
        )
        for i in items
    ]

    db.execute(
        "UPDATE stamp_sets SET status = 'generating', output_dir = ? WHERE id = ?",
        (str(output_dir), set_id),
    )
    db.commit()

    try:
        summary = generate_stamp_set(specs, output_dir)
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
    db.commit()
    return redirect(url_for("stamps.detail", set_id=set_id))


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
