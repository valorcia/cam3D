"""SQLite metadata store (thread-safe, stdlib only)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'empty',
    archived INTEGER NOT NULL DEFAULT 0,
    photo_count INTEGER NOT NULL DEFAULT 0,
    profile TEXT,
    model_faces INTEGER,
    model_size_bytes INTEGER,
    calibration TEXT,
    last_job_id TEXT
);
CREATE TABLE IF NOT EXISTS photos (
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    width INTEGER, height INTEGER,
    sharpness REAL, brightness REAL,
    warnings TEXT,
    created_at REAL NOT NULL,
    PRIMARY KEY (project_id, name)
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    profile TEXT,
    formats TEXT,
    resume INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    started_at REAL, finished_at REAL,
    current_stage TEXT,
    error TEXT, error_stage TEXT,
    num_images INTEGER,
    duration_s REAL,
    stages TEXT
);
CREATE TABLE IF NOT EXISTS devices (
    token_hash TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    last_seen REAL
);
CREATE INDEX IF NOT EXISTS jobs_project ON jobs(project_id);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def update(self, table: str, key: dict[str, Any], values: dict[str, Any]) -> None:
        if not values:
            return
        sets = ", ".join(f"{k} = :v_{k}" for k in values)
        where = " AND ".join(f"{k} = :k_{k}" for k in key)
        params = {f"v_{k}": (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in values.items()}
        params.update({f"k_{k}": v for k, v in key.items()})
        self.execute(f"UPDATE {table} SET {sets} WHERE {where}", params)

    def insert(self, table: str, values: dict[str, Any]) -> None:
        cols = ", ".join(values)
        ph = ", ".join(f":{k}" for k in values)
        params = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in values.items()}
        self.execute(f"INSERT INTO {table} ({cols}) VALUES ({ph})", params)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def now() -> float:
    return time.time()
