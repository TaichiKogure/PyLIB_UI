"""Explicitly saved immutable run snapshots."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class RunRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, run):
        with self.connect() as connection:
            connection.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, ?)",
                               (run["id"], run["created_at"], json.dumps(run, ensure_ascii=False, allow_nan=False)))

    def get(self, run_id):
        with self.connect() as connection:
            row = connection.execute("SELECT payload FROM runs WHERE id = ?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self):
        with self.connect() as connection:
            rows = connection.execute("SELECT payload FROM runs ORDER BY created_at DESC LIMIT 100").fetchall()
        return [{key: value for key, value in json.loads(row[0]).items() if key != "points"} for row in rows]
