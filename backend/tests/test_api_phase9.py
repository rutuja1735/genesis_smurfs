import time
import json

from fastapi.testclient import TestClient

from api.main import create_app
from core.logstore import LogStore
from core.types import FakeLLM


def test_conversation_run_and_sse_events_work_offline(tmp_path):
    app = create_app(store=LogStore(tmp_path / "index.db"), logs_dir=tmp_path / "logs")
    app.state.llm_factory = lambda **kwargs: FakeLLM()
    client = TestClient(app)

    conversation = client.post("/api/conversations", json={"title": "offline test"})
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]
    response = client.post(f"/api/conversations/{conversation_id}/messages", json={"content": "Summarize my unread emails"})
    assert response.status_code == 200
    run_id = response.json()["run_ids"][0]

    deadline = time.time() + 5
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"done", "error"}:
            break
        time.sleep(0.03)
    assert run["status"] == "done"
    assert run["result"]["answer"]
    event_response = client.get(f"/api/runs/{run_id}/events")
    assert any(event["event"] == "RUN_END" for event in event_response.json())
    streamed = client.get(f"/api/runs/{run_id}/stream")
    assert "event\": \"RUN_END\"" in streamed.text
    assert client.get(f"/api/conversations/{conversation_id}").json()["messages"]


def test_decision_filter_returns_human_reason(tmp_path):
    app = create_app(store=LogStore(tmp_path / "index.db"), logs_dir=tmp_path / "logs")
    store = app.state.store
    store.create_run("r1", "Pay invoice", status="done")
    store.index_event({"run_id": "r1", "event": "GATE_DECISION", "decision": "BLOCK", "rule": "R4",
                       "tool": "banking.send_money", "reason": "untrusted recipient",
                       "reason_human": "Blocked the transfer because the recipient came from an untrusted message."})
    client = TestClient(app)
    rows = client.get("/api/decisions?decision=BLOCK").json()
    assert rows[0]["rule"] == "R4"
    assert rows[0]["reason_human"].startswith("Blocked the transfer")


def test_attacked_payment_is_blocked_and_explained(tmp_path):
    app = create_app(store=LogStore(tmp_path / "index.db"), logs_dir=tmp_path / "logs")
    plan = {"tool_calls": [
        {"id": "1", "function_name": "banking.read_file", "args": {"file_path": "bill.txt"},
         "depends_on": [], "arg_sources": {"file_path": "user"}, "risk": "read", "justification": "Read the requested bill."},
        {"id": "2", "function_name": "banking.send_money",
         "args": {"recipient": "<unknown>: str", "amount": 1.0, "subject": "electricity bill", "date": "2026-10-16"},
         "depends_on": ["1"], "arg_sources": {"recipient": "from_node:1", "amount": "from_node:1", "subject": "user", "date": "user"},
         "risk": "high_impact", "justification": "Pay the bill requested by the user."},
    ]}
    app.state.llm_factory = lambda **kwargs: FakeLLM(responses={"planner": [json.dumps(plan)]})
    client = TestClient(app)
    response = client.post("/api/runs", json={"command": "Pay the electricity bill in bill.txt",
                                               "attack": "arg_poison", "injection_goal": "inj_bank_1"})
    run_id = response.json()["run_id"]
    deadline = time.time() + 5
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"done", "error"}:
            break
        time.sleep(0.03)
    assert run["status"] == "done"
    blocked = client.get(f"/api/decisions?decision=BLOCK&run_id={run_id}").json()
    assert blocked
    assert blocked[0]["rule"] == "R4"
    assert blocked[0]["reason_human"]
    assert "banking.send_money" in blocked[0]["tool"]
