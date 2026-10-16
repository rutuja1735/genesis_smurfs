"""Small SQLite ledger for spend, eval cursors, and deterministic LLM caching."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class LogStore:
    def __init__(self, path: str | Path = "logs/index.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS spend (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    run_id TEXT,
                    role TEXT NOT NULL,
                    model TEXT NOT NULL,
                    tokens_in INTEGER NOT NULL,
                    tokens_out INTEGER NOT NULL,
                    cost_usd REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS eval_cursors (
                    key TEXT PRIMARY KEY,
                    cursor INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS response_cache (
                    cache_key TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    def total_spend(self) -> float:
        with self._connect() as db:
            row = db.execute("SELECT COALESCE(SUM(cost_usd), 0) AS total FROM spend").fetchone()
            return float(row["total"])

    def record_spend(self, *, role: str, model: str, tokens_in: int, tokens_out: int,
                     cost_usd: float, run_id: str | None = None) -> None:
        if cost_usd < 0:
            raise ValueError("cost_usd cannot be negative")
        with self._connect() as db:
            db.execute("""INSERT INTO spend(ts, run_id, role, model, tokens_in, tokens_out, cost_usd)
                          VALUES (?, ?, ?, ?, ?, ?, ?)""",
                       (datetime.now(timezone.utc).isoformat(), run_id, role, model,
                        int(tokens_in), int(tokens_out), float(cost_usd)))

    def get_cursor(self, key: str) -> int:
        with self._connect() as db:
            row = db.execute("SELECT cursor FROM eval_cursors WHERE key=?", (key,)).fetchone()
            return int(row["cursor"]) if row else 0

    def set_cursor(self, key: str, cursor: int) -> None:
        if cursor < 0:
            raise ValueError("cursor cannot be negative")
        with self._connect() as db:
            db.execute("""INSERT INTO eval_cursors(key, cursor, updated_at) VALUES (?, ?, ?)
                          ON CONFLICT(key) DO UPDATE SET cursor=excluded.cursor, updated_at=excluded.updated_at""",
                       (key, cursor, datetime.now(timezone.utc).isoformat()))

    def get_cached(self, cache_key: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT response_json FROM response_cache WHERE cache_key=?", (cache_key,)).fetchone()
            return json.loads(row["response_json"]) if row else None

    def put_cached(self, cache_key: str, response: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute("""INSERT OR REPLACE INTO response_cache(cache_key, response_json, created_at)
                          VALUES (?, ?, ?)""",
                       (cache_key, json.dumps(response, sort_keys=True), datetime.now(timezone.utc).isoformat()))
