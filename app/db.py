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
    status      TEXT    NOT NULL DEFAULT 'draft',
    style       TEXT    NOT NULL DEFAULT 'line_stamp',
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
    sticker_path  TEXT,
    preview_path  TEXT,
    error_message TEXT,
    UNIQUE(set_id, position)
);
"""

# Columns added after initial schema – applied via migration
_MIGRATIONS = [
    "ALTER TABLE stamp_sets ADD COLUMN style      TEXT NOT NULL DEFAULT 'line_stamp'",
    "ALTER TABLE stamp_sets ADD COLUMN text_style TEXT NOT NULL DEFAULT 'bubble'",
    "ALTER TABLE stamp_sets ADD COLUMN expression TEXT NOT NULL DEFAULT 'none'",
    "ALTER TABLE stamp_items ADD COLUMN preview_path TEXT",
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
        db.commit()
        db.close()
    app.teardown_appcontext(close_db)
