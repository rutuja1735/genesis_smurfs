"""Agentgaurd local REST and SSE API. Start with uvicorn api.main:app --host 127.0.0.1."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

from agents import create_mock_environment
from attacks import ATTACKS, GOALS
from core.events import EventBus
from core.llm import OpenRouterClient, OpenRouterConfig
from core.logstore import LogStore
from tasks import TASKS, tasks_for_suite
from .jobs import execute_run
from .schemas import ConversationCreate, ConversationMessage, EvalCreate, RunCreate


def create_app(*, store: LogStore | None = None, logs_dir: str | Path | None = None) -> FastAPI:
    root = Path(logs_dir or os.getenv("AGENTGAURD_LOGS", "logs"))
    root.mkdir(parents=True, exist_ok=True)
    db = store or LogStore(root / "index.db")
    bus = EventBus()
    app = FastAPI(title="Agentgaurd API", version="0.9.0")
    app.state.store, app.state.logs_dir, app.state.event_bus = db, root, bus
    app.state.llm_factory = lambda **kw: OpenRouterClient(config=OpenRouterConfig.from_env(), store=kw["store"], audit=kw["audit"], run_id=kw["run_id"])
    app.state.active_eval = None

    async def start_run(spec: RunCreate, conversation_id: str | None = None, eval_id: str | None = None) -> str:
        run_id = uuid.uuid4().hex[:12]
        try:
            injections_for_validation = __import__("api.jobs", fromlist=["injections_for"]).injections_for
            injections_for_validation(spec.attack, spec.injection_goal)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        conversation = db.get_conversation(conversation_id) if conversation_id else None
        run_record = {"run_id": run_id, **spec.model_dump(), "conversation_id": conversation_id, "eval_id": eval_id,
                      "session_state": conversation.get("data_state", {}) if conversation else {}}
        db.create_run(run_id, spec.command, defense=spec.defense, attack=spec.attack,
                      injection_goal=spec.injection_goal, confirm_policy=spec.confirm_policy,
                      status="pending", conversation_id=conversation_id, track="mock", eval_id=eval_id,
                      jsonl_path=str(root / "runs" / f"{run_id}.jsonl"))
        async def worker() -> None:
            try:
                result = await asyncio.to_thread(execute_run, run_record, store=db, event_bus=bus,
                                                 llm_factory=app.state.llm_factory, logs_dir=root)
                if conversation_id:
                    db.add_message(uuid.uuid4().hex, conversation_id, "assistant", result["answer"], run_id)
                    db.update_conversation_state(conversation_id, result["after"])
            except Exception:
                pass  # RUN_ERROR and status are already persisted by execute_run.
        asyncio.create_task(worker())
        return run_id

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "name": "Agentgaurd"}

    @app.post("/api/conversations")
    def create_conversation(body: ConversationCreate):
        return db.create_conversation(uuid.uuid4().hex, body.title)

    @app.get("/api/conversations")
    def list_conversations(limit: int = Query(100, ge=1, le=500)):
        return db.list_conversations(limit)

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: str):
        result = db.get_conversation(conversation_id)
        if result is None:
            raise HTTPException(404, "conversation not found")
        return result

    @app.delete("/api/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str):
        if db.get_conversation(conversation_id) is None:
            raise HTTPException(404, "conversation not found")
        db.delete_conversation(conversation_id)
        return {"deleted": True}

    @app.post("/api/conversations/{conversation_id}/reset-data")
    def reset_conversation_data(conversation_id: str):
        if db.get_conversation(conversation_id) is None:
            raise HTTPException(404, "conversation not found")
        db.reset_conversation_data(conversation_id)
        return {"reset": True}

    @app.post("/api/conversations/{conversation_id}/messages")
    async def conversation_message(conversation_id: str, body: ConversationMessage):
        if db.get_conversation(conversation_id) is None:
            raise HTTPException(404, "conversation not found")
        prior = [message["content"] for message in db.get_conversation(conversation_id)["messages"] if message["role"] == "user"]
        command = "\n".join([*prior, body.content])
        message_id = uuid.uuid4().hex
        db.add_message(message_id, conversation_id, "user", body.content)
        runs = [await start_run(RunCreate(command=command, agents=body.agents, defense=defense,
                                          attack=body.attack, injection_goal=body.injection_goal,
                                          confirm_policy=body.confirm_policy, neutralize=body.neutralize,
                                          output_filter=body.output_filter), conversation_id)
                for defense in (["ours", "none"] if body.compare else [body.defense])]
        # Expose the message field as content in the response while keeping the
        # shared run schema's command property in storage and worker execution.
        return {"message_id": message_id, "run_ids": runs}

    @app.post("/api/runs")
    async def create_run(body: RunCreate):
        return {"run_id": await start_run(body)}

    @app.get("/api/runs")
    def list_runs(limit: int = Query(100, ge=1, le=500), defense: str | None = None,
                  attack: str | None = None, status: str | None = None):
        return db.list_runs(limit, defense, attack, status)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        run = db.get_run(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        # Result events contain the final delivered text and state diff.
        events = db.events_for_run(run_id)
        result = next((item for item in reversed(events) if item.get("event") == "RUN_RESULT"), None)
        return {**run, "result": result}

    @app.get("/api/runs/{run_id}/events")
    def run_events(run_id: str):
        if db.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        return db.events_for_run(run_id)

    @app.get("/api/runs/{run_id}/state-diff")
    def run_state_diff(run_id: str):
        result = next((item for item in reversed(db.events_for_run(run_id)) if item.get("event") == "RUN_RESULT"), None)
        if result is None:
            raise HTTPException(404, "run result not available")
        return {"state_diff": result.get("state_diff", {}), "attack_succeeded": result.get("attack_succeeded")}

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str):
        run = db.get_run(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        if run["status"] in {"done", "error", "cancelled"}:
            return {"cancelled": False, "status": run["status"]}
        # A synchronous tool/model call cannot be safely interrupted. Marking a
        # cancellation is intentionally unsupported until a cooperative cancel token exists.
        raise HTTPException(409, "run is executing a synchronous model call and cannot be cancelled safely")

    @app.get("/api/runs/{run_id}/stream")
    async def stream_run(run_id: str):
        if db.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        async def stream():
            sent = 0
            while True:
                events = db.events_for_run(run_id)
                for event in events[sent:]:
                    sent += 1
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                run = db.get_run(run_id)
                if run and run["status"] in {"done", "error", "cancelled"} and sent >= len(events):
                    break
                yield ": keep-alive\n\n"
                await asyncio.sleep(0.2)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/decisions")
    def decisions(decision: str | None = None, rule: str | None = None, agent: str | None = None,
                  tool: str | None = None, run_id: str | None = None,
                  limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
        return db.list_decisions(decision=decision, rule=rule, agent=agent, tool=tool,
                                 run_id=run_id, limit=limit, offset=offset)

    @app.get("/api/stats")
    def stats():
        return db.stats()

    @app.post("/api/reindex")
    def reindex():
        return {"indexed_events": db.reindex(root)}

    @app.get("/api/tasks")
    def tasks():
        return [{"id": task.id, "suite": task.suite, "prompt": task.prompt,
                 "expected_output": task.expected_output, "vectors": list(task.vectors)} for task in TASKS]

    @app.get("/api/attacks")
    def attacks():
        return [asdict(item) if is_dataclass(item) else item.model_dump() for item in ATTACKS]

    @app.get("/api/goals")
    def goals():
        return [asdict(item) if is_dataclass(item) else item.model_dump() for item in GOALS]

    @app.get("/api/data/{agent}")
    def data(agent: str, run_id: str | None = None):
        if agent not in {"email", "slack", "banking", "profile"}:
            raise HTTPException(404, "unknown agent")
        if run_id:
            result = next((event for event in reversed(db.events_for_run(run_id)) if event.get("event") == "RUN_RESULT"), None)
            if result is None or agent not in result.get("after", {}):
                raise HTTPException(404, "run data not available")
            return result["after"][agent]
        env = create_mock_environment()
        snapshots = env.snapshot()
        return snapshots[agent] if agent != "profile" else env.profile

    @app.get("/api/config")
    def config():
        from core.llm import LLMError
        try:
            model = OpenRouterConfig.from_env().model
        except LLMError:
            model = None
        return {"model": model, "confirm_policy": "deny", "neutralize": os.getenv("NEUTRALIZE_MODE", "redact"),
                "output_filter": os.getenv("OUTPUT_FILTER", "1") not in {"0", "false"},
                "spent_usd": db.total_spend(), "budget_usd": float(os.getenv("MAX_BUDGET_USD", "4.00")),
                "version": "0.9.0"}

    @app.post("/api/evals")
    async def create_eval(body: EvalCreate):
        if app.state.active_eval:
            raise HTTPException(409, "an evaluation is already active")
        agentdojo_python = None
        if body.track == "agentdojo":
            configured = os.getenv("AGENTDOJO_PYTHON")
            if configured:
                agentdojo_python = Path(configured)
            else:
                env_root = Path(__file__).resolve().parents[1] / ".venv-agentdojo"
                agentdojo_python = env_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            if not agentdojo_python.is_file():
                raise HTTPException(503, "Track B needs its separate environment. Set AGENTDOJO_PYTHON to that environment's Python executable.")
        eval_id = uuid.uuid4().hex[:12]
        params = body.model_dump()
        from datetime import datetime, timezone
        with db._connect() as conn:
            conn.execute("INSERT INTO evals(eval_id,created_at,params_json,status,total) VALUES(?,?,?,?,?)",
                         (eval_id, datetime.now(timezone.utc).isoformat(), db._json(params), "pending", body.batch_size))
        app.state.active_eval = eval_id
        async def eval_worker():
            try:
                if body.track == "agentdojo":
                    cursor_key = f"agentdojo:{body.suite}:{body.attack}:{body.defense}"
                    offset = body.cursor if body.cursor is not None else db.get_cursor(cursor_key)
                    command = [str(agentdojo_python), "-m", "agentdojo_adapter.runner",
                               "--suite", body.suite, "--attack", body.attack,
                               "--defense", body.defense, "--batch-size", str(body.batch_size),
                               "--offset", str(offset), "--eval-id", eval_id]
                    process = await asyncio.to_thread(subprocess.run, command, cwd=Path(__file__).resolve().parents[1],
                                                      capture_output=True, text=True, check=False)
                    if process.returncode != 0:
                        raise RuntimeError(process.stderr[-3000:] or f"Track B exited with code {process.returncode}")
                    report = None
                    for line in reversed(process.stdout.splitlines()):
                        try:
                            report = json.loads(line)
                            break
                        except json.JSONDecodeError:
                            continue
                    if report is None:
                        raise RuntimeError("Track B completed without a results summary")
                    db.set_cursor(cursor_key, offset + int(report.get("cases", 0)))
                    with db._connect() as conn:
                        conn.execute("UPDATE evals SET status=?,done=?,utility=?,asr=? WHERE eval_id=?",
                                     ("done", int(report.get("cases", 0)), report.get("utility"), report.get("asr"), eval_id))
                    return
                from eval.run_eval import attack_pairs
                if body.mode == "benign":
                    pairs = [(task, None, None) for task in tasks_for_suite(body.suite)]
                else:
                    pairs = attack_pairs(body.suite, body.attack, include_heldout=True)
                cursor_key = f"api:mock:{body.suite}:{body.mode}:{body.attack}:{body.defense}"
                offset = body.cursor if body.cursor is not None else db.get_cursor(cursor_key)
                selected = pairs[offset:offset + body.batch_size]
                done = 0
                completed_runs = []
                for task, goal_id, attack_id in selected:
                    spec = RunCreate(command=task.prompt, defense=body.defense, attack=attack_id,
                                     injection_goal=goal_id, confirm_policy=body.confirm_policy,
                                     neutralize=body.neutralize, output_filter=body.output_filter)
                    rid = await start_run(spec, eval_id=eval_id)
                    while (db.get_run(rid) or {}).get("status") in {"pending", "running"}:
                        await asyncio.sleep(0.2)
                    done += 1
                    completed_runs.append(db.get_run(rid) or {})
                    with db._connect() as conn:
                        conn.execute("UPDATE evals SET status=?,done=? WHERE eval_id=?", ("running", done, eval_id))
                db.set_cursor(cursor_key, offset + done)
                summaries = [row.get("summary", {}) for row in completed_runs]
                utilities = [item["utility"] for item in summaries if item.get("utility") is not None]
                attack_rates = [item["attack_succeeded"] for item in summaries if item.get("attack_succeeded") is not None]
                with db._connect() as conn:
                    conn.execute("UPDATE evals SET status=?,done=?,utility=?,asr=? WHERE eval_id=?",
                                 ("done", done, sum(utilities) / len(utilities) if utilities else None,
                                  sum(attack_rates) / len(attack_rates) if attack_rates else None, eval_id))
            except Exception as exc:
                with db._connect() as conn:
                    conn.execute("UPDATE evals SET status=?,params_json=? WHERE eval_id=?", ("error", db._json({**params, "error": str(exc)}), eval_id))
            finally:
                app.state.active_eval = None
        asyncio.create_task(eval_worker())
        return {"eval_id": eval_id, "batch_size": body.batch_size, "cursor": body.cursor}

    @app.get("/api/evals")
    def list_evals():
        with db._connect() as conn:
            rows = conn.execute("SELECT * FROM evals ORDER BY created_at DESC").fetchall()
        return [{**dict(row), "params": json.loads(row["params_json"])} for row in rows]

    @app.get("/api/evals/{eval_id}")
    def get_eval(eval_id: str):
        with db._connect() as conn:
            row = conn.execute("SELECT * FROM evals WHERE eval_id=?", (eval_id,)).fetchone()
        if not row:
            raise HTTPException(404, "evaluation not found")
        return {**dict(row), "params": json.loads(row["params_json"])}

    @app.get("/api/evals/{eval_id}/cases")
    def eval_cases(eval_id: str):
        with db._connect() as conn:
            row = conn.execute("SELECT eval_id FROM evals WHERE eval_id=?", (eval_id,)).fetchone()
        if not row:
            raise HTTPException(404, "evaluation not found")
        with db._connect() as conn:
            runs = conn.execute("SELECT run_id FROM runs WHERE eval_id=? ORDER BY created_at", (eval_id,)).fetchall()
        return [db.get_run(row[0]) for row in runs]

    return app


app = create_app()
