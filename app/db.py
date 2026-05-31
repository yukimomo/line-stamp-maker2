"""SQLite database setup and helpers."""

from __future__ import annotations
import sqlite3
from flask import Flask, g, current_app

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS stamp_sets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    status      TEXT    NOT NULL DEFAULT 'draft',
    theme       TEXT    NOT NULL DEFAULT 'simple_icon',
    style       TEXT    NOT NULL DEFAULT 'simple_circle',
    text_style  TEXT    NOT NULL DEFAULT 'bubble',
    expression  TEXT    NOT NULL DEFAULT 'none',
    stamp_count INTEGER NOT NULL DEFAULT 8,
    meta_json     TEXT,
    submit_status TEXT NOT NULL DEFAULT 'editing',
    preset_key    TEXT,
    output_dir  TEXT,
    zip_path    TEXT
);

-- Note: position is NOT range-checked (LINE allows 8/16/24/32/40 stamps).
CREATE TABLE IF NOT EXISTS stamp_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id        INTEGER NOT NULL REFERENCES stamp_sets(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    photo_path    TEXT    NOT NULL,
    caption       TEXT    NOT NULL DEFAULT '',
    item_template TEXT,
    zoom          REAL    NOT NULL DEFAULT 1.0,
    offset_x      REAL    NOT NULL DEFAULT 0.0,
    offset_y      REAL    NOT NULL DEFAULT 0.0,
    brightness    REAL    NOT NULL DEFAULT 0.0,
    sticker_path  TEXT,
    preview_path  TEXT,
    warnings      TEXT,
    error_message TEXT,
    style_json      TEXT,
    decoration_json TEXT,
    UNIQUE(set_id, position)
);

-- Reusable design presets (font/colors/frame/decoration settings)
CREATE TABLE IF NOT EXISTS design_presets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    style_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""

# Allowed LINE static-sticker set sizes
ALLOWED_COUNTS = (8, 16, 24, 32, 40)

# NOTE: SQLite forbids ALTER TABLE ADD COLUMN with a non-constant default
# (e.g. datetime('now')). updated_at is therefore added as a plain nullable
# column here and back-filled below; new rows get their default from SCHEMA.
_MIGRATIONS = [
    "ALTER TABLE stamp_sets ADD COLUMN style      TEXT NOT NULL DEFAULT 'simple_circle'",
    "ALTER TABLE stamp_sets ADD COLUMN text_style TEXT NOT NULL DEFAULT 'bubble'",
    "ALTER TABLE stamp_sets ADD COLUMN expression TEXT NOT NULL DEFAULT 'none'",
    "ALTER TABLE stamp_sets ADD COLUMN theme      TEXT NOT NULL DEFAULT 'simple_icon'",
    "ALTER TABLE stamp_sets ADD COLUMN updated_at TEXT",
    "ALTER TABLE stamp_items ADD COLUMN preview_path  TEXT",
    "ALTER TABLE stamp_items ADD COLUMN item_template TEXT",
    "ALTER TABLE stamp_items ADD COLUMN zoom       REAL NOT NULL DEFAULT 1.0",
    "ALTER TABLE stamp_items ADD COLUMN offset_x   REAL NOT NULL DEFAULT 0.0",
    "ALTER TABLE stamp_items ADD COLUMN offset_y   REAL NOT NULL DEFAULT 0.0",
    "ALTER TABLE stamp_items ADD COLUMN brightness REAL NOT NULL DEFAULT 0.0",
    "ALTER TABLE stamp_items ADD COLUMN warnings   TEXT",
    "ALTER TABLE stamp_sets  ADD COLUMN stamp_count INTEGER NOT NULL DEFAULT 8",
    "ALTER TABLE stamp_items ADD COLUMN style_json      TEXT",
    "ALTER TABLE stamp_items ADD COLUMN decoration_json TEXT",
    "ALTER TABLE stamp_sets  ADD COLUMN meta_json     TEXT",
    "ALTER TABLE stamp_sets  ADD COLUMN submit_status TEXT NOT NULL DEFAULT 'editing'",
    "ALTER TABLE stamp_sets  ADD COLUMN preset_key    TEXT",
]

# Run after _MIGRATIONS to back-fill nullable columns
_BACKFILLS = [
    "UPDATE stamp_sets SET updated_at = created_at WHERE updated_at IS NULL",
]


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e: object = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app: Flask) -> None:
    with app.app_context():
        db = sqlite3.connect(app.config["DATABASE"])
        db.executescript(SCHEMA)
        # Apply migrations (idempotent – ignore "duplicate column" errors)
        for sql in _MIGRATIONS:
            try:
                db.execute(sql)
            except sqlite3.OperationalError:
                pass
        for sql in _BACKFILLS:
            try:
                db.execute(sql)
            except sqlite3.OperationalError:
                pass
        _drop_position_check(db)
        db.commit()
        db.close()
    app.teardown_appcontext(close_db)


def _drop_position_check(db: sqlite3.Connection) -> None:
    """
    Older DBs created stamp_items with CHECK(position BETWEEN 1 AND 8), which
    blocks 16/24/32/40-stamp sets. Rebuild the table without that constraint.
    """
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='stamp_items'"
    ).fetchone()
    if not row or "BETWEEN 1 AND 8" not in (row[0] or ""):
        return  # already constraint-free

    db.executescript(
        """
        PRAGMA foreign_keys = OFF;
        BEGIN;
        ALTER TABLE stamp_items RENAME TO _stamp_items_old;
        CREATE TABLE stamp_items (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id        INTEGER NOT NULL REFERENCES stamp_sets(id) ON DELETE CASCADE,
            position      INTEGER NOT NULL,
            photo_path    TEXT    NOT NULL,
            caption       TEXT    NOT NULL DEFAULT '',
            item_template TEXT,
            zoom          REAL    NOT NULL DEFAULT 1.0,
            offset_x      REAL    NOT NULL DEFAULT 0.0,
            offset_y      REAL    NOT NULL DEFAULT 0.0,
            brightness    REAL    NOT NULL DEFAULT 0.0,
            sticker_path  TEXT,
            preview_path  TEXT,
            warnings      TEXT,
            error_message TEXT,
            style_json      TEXT,
            decoration_json TEXT,
            UNIQUE(set_id, position)
        );
        INSERT INTO stamp_items
            (id, set_id, position, photo_path, caption, item_template, zoom,
             offset_x, offset_y, brightness, sticker_path, preview_path,
             warnings, error_message, style_json, decoration_json)
        SELECT id, set_id, position, photo_path, caption, item_template, zoom,
               offset_x, offset_y, brightness, sticker_path, preview_path,
               warnings, error_message, style_json, decoration_json
        FROM _stamp_items_old;
        DROP TABLE _stamp_items_old;
        COMMIT;
        PRAGMA foreign_keys = ON;
        """
    )
