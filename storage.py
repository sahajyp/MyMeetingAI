"""SQLite persistence for meeting notes (standard library only)."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    title_custom INTEGER NOT NULL DEFAULT 0,
    filename     TEXT NOT NULL,
    audio_name   TEXT,
    context      TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'queued',
    stage        TEXT NOT NULL DEFAULT 'Queued',
    progress     REAL NOT NULL DEFAULT 0,
    error        TEXT,
    created_at   TEXT NOT NULL,
    duration     REAL,
    language     TEXT,
    word_count   INTEGER NOT NULL DEFAULT 0,
    transcript   TEXT,
    notes        TEXT,
    search_text  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at DESC);
"""

UPDATABLE = {
    "title", "title_custom", "status", "stage", "progress", "error", "duration",
    "language", "word_count", "transcript", "notes", "search_text",
}
JSON_FIELDS = {"transcript", "notes"}
LIST_COLUMNS = (
    "id, title, filename, status, stage, progress, error, created_at, "
    "duration, language, word_count"
)


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    """Tiny data layer. A fresh connection per call keeps it thread-safe."""

    def __init__(self, db_path):
        self.db_path = str(db_path)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------ create
    def create(self, note_id, *, title, filename, audio_name, context=""):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO notes (id, title, filename, audio_name, context, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (note_id, title, filename, audio_name, context, utcnow()),
            )
        return self.get(note_id, full=True)

    # -------------------------------------------------------------------- read
    def get(self, note_id, full=False):
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data.pop("search_text", None)
        if full:
            data["transcript"] = json.loads(data["transcript"]) if data["transcript"] else []
            data["notes"] = json.loads(data["notes"]) if data["notes"] else None
        else:
            data.pop("transcript", None)
            data.pop("notes", None)
        return data

    def list(self, query=""):
        sql = f"SELECT {LIST_COLUMNS} FROM notes"
        params = []
        query = (query or "").strip()
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            sql += " WHERE title LIKE ? ESCAPE '\\' OR search_text LIKE ? ESCAPE '\\'"
            params = [f"%{escaped}%"] * 2
        sql += " ORDER BY created_at DESC, rowid DESC"
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    # ------------------------------------------------------------------ update
    def update(self, note_id, **fields):
        """Update columns. Returns False when the note no longer exists."""
        unknown = set(fields) - UPDATABLE
        if unknown:
            raise ValueError(f"Cannot update: {', '.join(sorted(unknown))}")
        if not fields:
            return True
        assignments, values = [], []
        for key, value in fields.items():
            if key in JSON_FIELDS and value is not None:
                value = json.dumps(value, ensure_ascii=False)
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(note_id)
        with self._conn() as conn:
            cur = conn.execute(f"UPDATE notes SET {', '.join(assignments)} WHERE id = ?", values)
            return cur.rowcount > 0

    def delete(self, note_id):
        """Delete a note. Returns (existed, audio_name)."""
        with self._conn() as conn:
            row = conn.execute("SELECT audio_name FROM notes WHERE id = ?", (note_id,)).fetchone()
            if row is None:
                return False, None
            conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return True, row["audio_name"]

    def mark_interrupted(self):
        """Notes still queued/processing at startup were cut off by a restart."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE notes SET status = 'failed', stage = 'Interrupted', "
                "error = 'The app restarted while this recording was being processed. "
                "Select Retry to process it again.' "
                "WHERE status IN ('queued', 'processing')"
            )
