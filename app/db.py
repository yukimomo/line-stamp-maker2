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
    output_dir  TEXT,
    zip_path    TEXT
);

CREATE TABLE IF NOT EXISTS stamp_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id        INTEGER NOT NULL REFERENCES stamp_sets(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL CHECK(position BETWEEN 1 AND 8),
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
    UNIQUE(set_id, position)
);
"""

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
        db.commit()
        db.close()
    app.teardown_appcontext(close_db)
