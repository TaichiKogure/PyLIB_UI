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
            connection.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
            connection.execute("INSERT OR IGNORE INTO projects VALUES ('default', '標準プロジェクト')")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL, original BLOB NOT NULL)")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS comparisons (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL)")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS designs (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL)")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS physics_jobs (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL)")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS result_analyses (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, run, original=None):
        self.require_project(run.get("project_id", "default"))
        with self.connect() as connection:
            payload = json.dumps(run, ensure_ascii=False, allow_nan=False)
            if run.get("record_type") == "dataset":
                if original is None:
                    raise ValueError("原本がありません。再度プレビューしてください。")
                connection.execute("INSERT OR IGNORE INTO datasets VALUES (?, ?, ?, ?)",
                                   (run["id"], run["created_at"], payload, original))
            else:
                connection.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, ?)",
                                   (run["id"], run["created_at"], payload))

    def get(self, run_id):
        with self.connect() as connection:
            row = connection.execute("SELECT payload FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                row = connection.execute("SELECT payload FROM datasets WHERE id = ?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, project_id=None):
        with self.connect() as connection:
            rows = connection.execute("SELECT payload FROM runs UNION ALL SELECT payload FROM datasets").fetchall()
        records = [json.loads(row[0]) for row in rows]
        records = [r for r in records if project_id is None or r.get("project_id", "default") == project_id]
        return [{key: value for key, value in r.items() if
                 key not in {"points", "distributions", "result_variables", "progress_events", "citation_export"}}
                for r in sorted(records, key=lambda r: r["created_at"], reverse=True)]

    def save_analysis(self, record):
        self.require_project(record['project_id'])
        with self.connect() as connection:
            connection.execute('INSERT INTO result_analyses VALUES (?, ?, ?)',
                               (record['id'], record['project_id'],
                                json.dumps(record, ensure_ascii=False, allow_nan=False)))
        return record

    def analyses(self, project_id):
        self.require_project(project_id)
        with self.connect() as connection:
            return [dict(id=r['id'], created_at=r['created_at'], record_type=r['record_type'],
                         source_names=[s['name'] for s in r['source_snapshots']])
                    for (payload,) in
                    connection.execute('SELECT payload FROM result_analyses WHERE project_id=? ORDER BY rowid DESC',
                                       (project_id,))
                    for r in [json.loads(payload)]]

    def analysis(self, analysis_id, project_id):
        self.require_project(project_id)
        with self.connect() as connection:
            row = connection.execute('SELECT payload FROM result_analyses WHERE id=? AND project_id=?',
                                     (analysis_id, project_id)).fetchone()
        if row is None: raise ValueError('同じプロジェクトの解析が見つかりません。')
        return json.loads(row[0])

    def original(self, dataset_id):
        with self.connect() as connection:
            row = connection.execute("SELECT original FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        return bytes(row[0]) if row else None

    def projects(self):
        with self.connect() as connection:
            return [dict(zip(("id", "name"), row)) for row in
                    connection.execute("SELECT id, name FROM projects ORDER BY rowid")]

    def require_project(self, project_id):
        if not isinstance(project_id, str) or project_id not in {p["id"] for p in self.projects()}:
            raise ValueError("プロジェクトが見つかりません。選択し直してください。")

    def create_project(self, name):
        from uuid import uuid4
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("プロジェクト名は1〜100文字で入力してください。")
        project = {"id": str(uuid4()), "name": name.strip()}
        with self.connect() as connection:
            connection.execute("INSERT INTO projects VALUES (?, ?)", (project["id"], project["name"]))
        return project

    def duplicate_ids(self, sha256):
        return [r["id"] for r in self.list() if r.get("original", {}).get("sha256") == sha256]

    def save_comparison(self, data):
        from uuid import uuid4
        if not isinstance(data, dict):
            raise ValueError("比較セットの条件を確認してください。")
        project_id = data.get("project_id", "default")
        self.require_project(project_id)
        ids = data.get("dataset_ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 4 or any(not isinstance(i, str) for i in ids) or len(
                set(ids)) != len(ids):
            raise ValueError("保存済みカーブを1〜4件指定してください。")
        for run_id in ids:
            record = self.get(run_id)
            if record is None or record.get("project_id", "default") != project_id:
                raise ValueError("比較対象は同じプロジェクトの保存済みカーブから選択してください。")
        if data.get("x_axis") not in {"time_s", "capacity_ah", "soc"} or data.get("variable") not in {"voltage_v",
                                                                                                      "soc",
                                                                                                      "current_a",
                                                                                                      "temperature_c",
                                                                                                      "positive_reference_v",
                                                                                                      "negative_reference_v"}:
            raise ValueError("比較軸を確認してください。")
        name, notes = data.get("name", "比較セット"), data.get("notes", "")
        if not isinstance(name, str) or not name.strip() or len(name) > 100 or not isinstance(notes, str) or len(
                notes) > 4000:
            raise ValueError("比較名・注釈の長さを確認してください。")
        record = {"id": str(uuid4()), "project_id": project_id, "dataset_ids": ids,
                  "name": name.strip(), "notes": notes, "x_axis": data["x_axis"], "variable": data["variable"],
                  "alignment": "as_recorded", "normalization": "none"}
        with self.connect() as connection:
            connection.execute("INSERT INTO comparisons VALUES (?, ?, ?)",
                               (record["id"], project_id, json.dumps(record, ensure_ascii=False)))
        return record

    def comparisons(self, project_id):
        self.require_project(project_id)
        with self.connect() as connection:
            return [json.loads(r[0]) for r in
                    connection.execute("SELECT payload FROM comparisons WHERE project_id = ? ORDER BY rowid DESC",
                                       (project_id,))]

    def save_design(self, data):
        from datetime import datetime, timezone
        from uuid import uuid4
        from .design import evaluate_design
        if not isinstance(data, dict) or set(data) - {"project_id", "input"}:
            raise ValueError("設計保存の項目を確認してください。")
        project_id = data.get("project_id", "default")
        self.require_project(project_id)
        record = evaluate_design(data.get("input"))
        record.update(id=str(uuid4()), project_id=project_id, created_at=datetime.now(timezone.utc).isoformat())
        with self.connect() as connection:
            connection.execute("INSERT INTO designs VALUES (?, ?, ?)",
                               (record["id"], project_id, json.dumps(record, ensure_ascii=False, allow_nan=False)))
        return record

    def designs(self, project_id):
        self.require_project(project_id)
        with self.connect() as connection:
            return [json.loads(row[0]) for row in connection.execute(
                "SELECT payload FROM designs WHERE project_id = ? ORDER BY rowid DESC", (project_id,))]

    def design(self, design_id, project_id):
        self.require_project(project_id)
        with self.connect() as connection:
            row = connection.execute("SELECT payload FROM designs WHERE id = ? AND project_id = ?",
                                     (design_id, project_id)).fetchone()
        if row is None:
            raise ValueError("同じプロジェクトの保存済み設計を選択してください。")
        return json.loads(row[0])

    def put_job(self, job):
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO physics_jobs VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (job['id'], job['project_id'], json.dumps(job, ensure_ascii=False, allow_nan=False)))

    def jobs(self, project_id=None):
        if project_id is not None:
            self.require_project(project_id)
        with self.connect() as connection:
            if project_id is None:
                rows = connection.execute("SELECT payload FROM physics_jobs ORDER BY rowid DESC").fetchall()
            else:
                rows = connection.execute("SELECT payload FROM physics_jobs WHERE project_id=? ORDER BY rowid DESC",
                                          (project_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]
