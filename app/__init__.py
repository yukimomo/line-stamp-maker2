"""Flask app factory for LINE stamp web app."""

from __future__ import annotations
import urllib.parse
from pathlib import Path
from flask import Flask

from .db import init_db


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates")

    _root = Path(__file__).resolve().parent.parent

    app.config.update(
        SECRET_KEY="dev-key-change-in-production",
        DATABASE=str(_root / "stamps.db"),
        OUTPUT_DIR=str(_root / "output"),
        # photo-selector output paths (adjust if your install differs)
        PHOTO_SELECTOR_MANIFEST=str(
            Path.home() / "photo-selector" / "output" / "scores" / "manifest.photos.json"
        ),
        PHOTO_SELECTOR_SELECTED_DIR=str(
            Path.home() / "photo-selector" / "output" / "selected"
        ),
        STAMP_COUNT=8,
    )

    if config:
        app.config.update(config)

    Path(app.config["OUTPUT_DIR"]).mkdir(parents=True, exist_ok=True)

    init_db(app)
    _reset_stale_generating(app)

    # Jinja2 helper: convert absolute path to /photo?path=... URL
    @app.template_filter("photourl")
    def photo_url_filter(path: str | None) -> str:
        if not path:
            return ""
        return f"/photo?path={urllib.parse.quote(str(path), safe='')}"

    # Jinja2 helper: [r,g,b] -> "#rrggbb" (for <input type=color> defaults)
    @app.template_filter("rgbhex")
    def rgbhex_filter(rgb, default: str = "#000000") -> str:
        try:
            r, g, b = (int(x) for x in list(rgb)[:3])
            return f"#{r:02x}{g:02x}{b:02x}"
        except (TypeError, ValueError):
            return default

    from .routes import bp
    app.register_blueprint(bp)

    return app


def _reset_stale_generating(app: Flask) -> None:
    """Reset any 'generating' status left over from a crashed previous run."""
    import sqlite3
    db_path = app.config["DATABASE"]
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE stamp_sets SET status = 'error' WHERE status = 'generating'"
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
