"""One SQLite file: portfolio, preferences, cached responses and read state."""

import json
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires REAL)"
            )

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            yield db

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute(
                "SELECT value, expires FROM kv WHERE key=?", (key,)
            ).fetchone()
        if not row or (row[1] is not None and row[1] <= time.time()):
            return default
        return json.loads(row[0])

    def set(self, key, value, ttl=None):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO kv VALUES (?, ?, ?)",
                (
                    key,
                    json.dumps(value, allow_nan=False),
                    time.time() + ttl if ttl else None,
                ),
            )

    def append_unique(self, key, value):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            items = json.loads(row[0]) if row else []
            if value not in items:
                items.append(value)
            db.execute(
                "INSERT OR REPLACE INTO kv VALUES (?, ?, NULL)",
                (key, json.dumps(items)),
            )

    def set_membership(self, key, values, present):
        """Add or remove values from a saved list in one transaction."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            items = json.loads(row[0]) if row else []
            selected = set(values)
            if present:
                existing = set(items)
                for value in values:
                    if value not in existing:
                        items.append(value)
                        existing.add(value)
            else:
                items = [value for value in items if value not in selected]
            db.execute(
                "INSERT OR REPLACE INTO kv VALUES (?, ?, NULL)",
                (key, json.dumps(items)),
            )

    def patch(self, key, fields):
        """Merge a partial record atomically so saving a note cannot undo a bookmark."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            value = {**(json.loads(row[0]) if row else {}), **fields}
            db.execute(
                "INSERT OR REPLACE INTO kv VALUES (?, ?, NULL)",
                (key, json.dumps(value)),
            )
        return value

    def records(self, prefix):
        with self.connect() as db:
            rows = db.execute(
                "SELECT key, value FROM kv WHERE substr(key, 1, ?) = ? "
                "AND (expires IS NULL OR expires > ?)",
                (len(prefix), prefix, time.time()),
            ).fetchall()
        return {key[len(prefix) :]: json.loads(value) for key, value in rows}

    def purge_expired(self):
        with self.connect() as db:
            db.execute("DELETE FROM kv WHERE expires <= ?", (time.time(),))

    def update(self, key, default, transform):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            value = transform(json.loads(row[0]) if row else default)
            db.execute(
                "INSERT OR REPLACE INTO kv VALUES (?, ?, NULL)",
                (key, json.dumps(value, allow_nan=False)),
            )
            return value
