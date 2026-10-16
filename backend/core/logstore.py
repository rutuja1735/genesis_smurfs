"""Small SQLite ledger for spend, eval cursors, and deterministic LLM caching."""

from __future__ import annotations

import json
import argparse
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
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, command TEXT NOT NULL,
                    defense TEXT, attack TEXT, injection_goal TEXT, confirm_policy TEXT,
                    model TEXT, status TEXT NOT NULL, conversation_id TEXT, track TEXT NOT NULL DEFAULT 'mock',
                    summary_json TEXT NOT NULL DEFAULT '{}', jsonl_path TEXT, eval_id TEXT, case_id TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, seq INTEGER NOT NULL,
                    ts TEXT NOT NULL, event TEXT NOT NULL, node_id TEXT, agent TEXT, tool TEXT,
                    payload_json TEXT NOT NULL, UNIQUE(run_id, seq)
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ts TEXT NOT NULL,
                    node_id TEXT, agent TEXT, tool TEXT, args_json TEXT NOT NULL DEFAULT '{}',
                    arg_origins_json TEXT NOT NULL DEFAULT '{}', decision TEXT, rule TEXT,
                    reason TEXT, reason_human TEXT, source_of_attempt TEXT, severity TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, title TEXT NOT NULL,
                    data_state_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
                    content TEXT NOT NULL, run_id TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evals (
                    eval_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, params_json TEXT NOT NULL,
                    status TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
                    asr REAL, utility REAL
                );
                CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq);
                CREATE INDEX IF NOT EXISTS idx_decision_decision ON decisions(decision);
                CREATE INDEX IF NOT EXISTS idx_decision_run ON decisions(run_id);
            """)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    def create_run(self, run_id: str, command: str, **fields: Any) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute("""INSERT INTO runs(run_id,created_at,command,defense,attack,injection_goal,
                confirm_policy,model,status,conversation_id,track,summary_json,jsonl_path,eval_id,case_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, now, command, fields.get("defense", "ours"), fields.get("attack"),
                 fields.get("injection_goal"), fields.get("confirm_policy", "deny"), fields.get("model"),
                 fields.get("status", "pending"), fields.get("conversation_id"), fields.get("track", "mock"),
                 self._json(fields.get("summary", {})), fields.get("jsonl_path"), fields.get("eval_id"), fields.get("case_id")))

    def update_run(self, run_id: str, *, status: str | None = None, summary: dict[str, Any] | None = None) -> None:
        with self._connect() as db:
            if status is not None and summary is not None:
                db.execute("UPDATE runs SET status=?,summary_json=? WHERE run_id=?", (status, self._json(summary), run_id))
            elif status is not None:
                db.execute("UPDATE runs SET status=? WHERE run_id=?", (status, run_id))
            elif summary is not None:
                db.execute("UPDATE runs SET summary_json=? WHERE run_id=?", (self._json(summary), run_id))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        result = self._dict(row)
        if result:
            result["summary"] = json.loads(result.pop("summary_json"))
        return result

    def list_runs(self, limit: int = 100, defense: str | None = None, attack: str | None = None,
                  status: str | None = None) -> list[dict[str, Any]]:
        clauses, args = [], []
        for column, value in (("defense", defense), ("attack", attack), ("status", status)):
            if value is not None:
                clauses.append(f"{column}=?"); args.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as db:
            rows = db.execute(f"SELECT * FROM runs{where} ORDER BY created_at DESC LIMIT ?", (*args, max(1, min(limit, 500)))).fetchall()
        out=[]
        for row in rows:
            item=dict(row); item["summary"]=json.loads(item.pop("summary_json")); out.append(item)
        return out

    def index_event(self, record: dict[str, Any]) -> None:
        run_id = str(record.get("run_id", ""))
        if not run_id:
            return
        event = str(record.get("event", "UNKNOWN"))
        with self._connect() as db:
            seq = int(db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (run_id,)).fetchone()[0])
            db.execute("INSERT INTO events(run_id,seq,ts,event,node_id,agent,tool,payload_json) VALUES(?,?,?,?,?,?,?,?)",
                       (run_id, seq, record.get("ts", datetime.now(timezone.utc).isoformat()), event,
                        record.get("node"), record.get("agent"), record.get("tool"), self._json(record)))
            if event in {"GATE_DECISION", "FINAL_ANSWER_FILTER"}:
                db.execute("""INSERT INTO decisions(run_id,ts,node_id,agent,tool,args_json,arg_origins_json,
                    decision,rule,reason,reason_human,source_of_attempt,severity,payload_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (run_id, record.get("ts", ""), record.get("node"),
                     "final_answer" if event == "FINAL_ANSWER_FILTER" else record.get("agent", str(record.get("tool", "")).split(".",1)[0] or None), record.get("tool"),
                     self._json(record.get("args", {})), self._json(record.get("arg_origins", {})),
                     record.get("decision"), record.get("rule"), record.get("reason"), record.get("reason_human"),
                     record.get("source_of_attempt", record.get("source")), record.get("severity"), self._json(record)))

    def events_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows=db.execute("SELECT payload_json FROM events WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_decisions(self, *, decision: str | None = None, rule: str | None = None,
                       agent: str | None = None, tool: str | None = None,
                       run_id: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        clauses=[]; args=[]
        for column,value in (("decision",decision),("rule",rule),("agent",agent),("tool",tool),("run_id",run_id)):
            if value is not None: clauses.append(f"{column}=?"); args.append(value)
        where=" WHERE "+" AND ".join(clauses) if clauses else ""
        with self._connect() as db:
            rows=db.execute(f"SELECT * FROM decisions{where} ORDER BY id DESC LIMIT ? OFFSET ?",(*args,max(1,min(limit,500)),max(offset,0))).fetchall()
        out=[]
        for row in rows:
            item=dict(row); item["args"]=json.loads(item.pop("args_json")); item["arg_origins"]=json.loads(item.pop("arg_origins_json")); item["payload"]=json.loads(item.pop("payload_json")); out.append(item)
        return out

    def create_conversation(self, conversation_id: str, title: str = "New conversation") -> dict[str, Any]:
        now=datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute("INSERT INTO conversations(id,created_at,title,data_state_json) VALUES(?,?,?,'{}')",(conversation_id,now,title))
        return {"id":conversation_id,"created_at":now,"title":title}

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row=db.execute("SELECT * FROM conversations WHERE id=?",(conversation_id,)).fetchone()
            messages=db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at",(conversation_id,)).fetchall()
        result=self._dict(row)
        if result:
            result["data_state"]=json.loads(result.pop("data_state_json")); result["messages"]=[dict(m) for m in messages]
        return result

    def list_conversations(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows=db.execute("SELECT id,created_at,title FROM conversations ORDER BY created_at DESC LIMIT ?",(max(1,min(limit,500)),)).fetchall()
        return [dict(row) for row in rows]

    def add_message(self, message_id: str, conversation_id: str, role: str, content: str, run_id: str | None = None) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO messages(id,conversation_id,role,content,run_id,created_at) VALUES(?,?,?,?,?,?)",
                       (message_id,conversation_id,role,content,run_id,datetime.now(timezone.utc).isoformat()))

    def delete_conversation(self, conversation_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM messages WHERE conversation_id=?",(conversation_id,)); db.execute("DELETE FROM conversations WHERE id=?",(conversation_id,))

    def reset_conversation_data(self, conversation_id: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE conversations SET data_state_json='{}' WHERE id=?",(conversation_id,))

    def update_conversation_state(self, conversation_id: str, state: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute("UPDATE conversations SET data_state_json=? WHERE id=?",(self._json(state),conversation_id))

    def stats(self) -> dict[str, Any]:
        with self._connect() as db:
            counts=db.execute("SELECT decision,COUNT(*) n FROM decisions GROUP BY decision").fetchall()
            rules=db.execute("SELECT rule,COUNT(*) n FROM decisions WHERE rule IS NOT NULL GROUP BY rule").fetchall()
        return {"decisions":{r["decision"]:r["n"] for r in counts},"rules":{r["rule"]:r["n"] for r in rules}}

    def reindex(self, root: str | Path | None = None) -> int:
        """Rebuild event/decision/run indexes from append-only JSONL audit files."""
        base = Path(root) if root else self.path.parent
        files = sorted(base.rglob("*.jsonl")) if base.exists() else []
        with self._connect() as db:
            db.execute("DELETE FROM events")
            db.execute("DELETE FROM decisions")
            db.execute("DELETE FROM runs")
        count = 0
        for path in files:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if not record.get("event"):
                    continue
                if record.get("event") == "RUN_START" and record.get("run_id"):
                    run_id = str(record["run_id"])
                    with self._connect() as db:
                        db.execute("""INSERT OR IGNORE INTO runs(run_id,created_at,command,defense,attack,injection_goal,
                            confirm_policy,model,status,track,jsonl_path) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (run_id, record.get("ts", ""), record.get("command", ""), record.get("defense"),
                             record.get("attack"), record.get("injection_goal"), record.get("confirm_policy", "deny"),
                             record.get("model"), "done", record.get("track", "mock"), str(path)))
                if record.get("run_id"):
                    self.index_event(record)
                    count += 1
        return count


    def total_spend(self) -> float:
        with self._connect() as db:
            row = db.execute("SELECT COALESCE(SUM(cost_usd), 0) AS total FROM spend").fetchone()
            return float(row["total"])

    def usage_totals(self) -> dict[str, float | int]:
        with self._connect() as db:
            row = db.execute("""SELECT COUNT(*) AS calls,
                               COALESCE(SUM(tokens_in), 0) AS tokens_in,
                               COALESCE(SUM(tokens_out), 0) AS tokens_out,
                               COALESCE(SUM(cost_usd), 0) AS cost_usd FROM spend""").fetchone()
            return {"llm_calls": int(row["calls"]), "tokens_in": int(row["tokens_in"]),
                    "tokens_out": int(row["tokens_out"]), "cost_usd": float(row["cost_usd"])}

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Agentgaurd log index maintenance")
    sub = parser.add_subparsers(dest="command", required=True)
    reindex = sub.add_parser("reindex", help="rebuild SQLite index from JSONL")
    reindex.add_argument("--logs", default="logs")
    args = parser.parse_args()
    store = LogStore(Path(args.logs) / "index.db")
    if args.command == "reindex":
        print(json.dumps({"indexed_events": store.reindex(args.logs)}))


if __name__ == "__main__":
    main()
