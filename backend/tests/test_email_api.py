"""Tests for the dedicated Real Email Agent REST API endpoints."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agents.mail_backend import NormalizedEmail
from agents.real_email_agent import RealEmailAgent
from api.main import create_app
from core.logstore import LogStore
from core.types import FakeLLM


class DummyMailBackend:
    """In-memory backend implementing MailBackend interface for API tests."""

    def __init__(self, mode: str = "full") -> None:
        self.mode = mode
        self.emails = [
            NormalizedEmail(
                id="msg_001",
                thread_id="th_001",
                from_addr="alice@trusted.com",
                from_display="Alice Smith",
                to=["me@example.com"],
                cc=[],
                subject="Quarterly Sync",
                body_text="Here is the quarterly update.",
                body_raw="Here is the quarterly update.",
                date="2026-10-16T10:00:00Z",
                is_read=False,
                labels=["INBOX", "UNREAD"],
            ),
            NormalizedEmail(
                id="msg_002",
                thread_id="th_002",
                from_addr="bob@external.com",
                from_display="Bob Jones",
                to=["me@example.com"],
                cc=[],
                subject="Lunch tomorrow?",
                body_text="Are we still meeting for lunch?",
                body_raw="Are we still meeting for lunch?",
                date="2026-10-16T11:00:00Z",
                is_read=True,
                labels=["INBOX"],
            ),
        ]
        self.drafts: list[dict] = []
        self.sent: list[dict] = []
        self.trashed: list[str] = []

    def list_messages(self, query: str = "", max_results: int = 20, unread_only: bool = False):
        res = self.emails
        if unread_only:
            res = [m for m in res if not m.is_read]
        if query:
            q = query.casefold()
            res = [m for m in res if q in m.subject.casefold() or q in m.body_text.casefold()]
        return res[:max_results]

    def get_message(self, id: str):
        for m in self.emails:
            if m.id == id:
                return m
        raise KeyError(f"Email {id} not found")

    def mark_read(self, id: str):
        for m in self.emails:
            if m.id == id:
                m.is_read = True
                return {"id": id, "read": True}
        raise KeyError(f"Email {id} not found")

    def create_draft(self, to: list[str], subject: str, body: str):
        draft_id = f"draft_{len(self.drafts)+1}"
        d = {"id": draft_id, "to": to, "subject": subject, "body": body}
        self.drafts.append(d)
        return {"id": draft_id, "status": "draft_created"}

    def send(self, to: list[str], subject: str, body: str, cc: list[str] | None = None):
        send_id = f"send_{len(self.sent)+1}"
        s = {"id": send_id, "to": to, "subject": subject, "body": body, "cc": cc or []}
        self.sent.append(s)
        return {"id": send_id, "status": "sent"}

    def forward(self, id: str, to: list[str]):
        return {"status": "forwarded", "id": id, "to": to}

    def trash(self, id: str):
        self.trashed.append(id)
        return {"id": id, "status": "trashed"}


@pytest.fixture
def test_setup(tmp_path, monkeypatch):
    """Setup app with an injected RealEmailAgent backed by DummyMailBackend."""
    monkeypatch.setenv("EMAIL_AGENT", "real")
    monkeypatch.setenv("REAL_EMAIL_DRY_RUN", "1")
    monkeypatch.setenv("REAL_EMAIL_MODE", "full")
    monkeypatch.setenv("REAL_EMAIL_SEND_ALLOWLIST", "alice@trusted.com")

    app = create_app(store=LogStore(tmp_path / "index.db"), logs_dir=tmp_path / "logs")
    backend = DummyMailBackend()
    ledger_path = tmp_path / "test_ledger.jsonl"
    real_agent = RealEmailAgent(
        backend=backend,
        dry_run=True,
        send_allowlist=["alice@trusted.com"],
        ledger_path=ledger_path,
    )
    app.state.real_email_agent = real_agent
    app.state.llm_factory = lambda **kwargs: FakeLLM()
    client = TestClient(app)
    return client, real_agent, backend


def test_email_status_endpoint(test_setup):
    client, agent, backend = test_setup
    resp = client.get("/api/email/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured_agent"] == "real"
    assert data["active_agent"] == "real"
    assert data["dry_run"] is True
    assert data["inbox_stats"]["total"] == 2
    assert data["inbox_stats"]["unread"] == 1


def test_email_config_update(test_setup):
    client, agent, backend = test_setup
    resp = client.post("/api/email/config", json={
        "dry_run": False,
        "send_allowlist": ["bob@external.com", "alice@trusted.com"]
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["dry_run"] is False
    assert "bob@external.com" in data["send_allowlist"]
    assert agent.dry_run is False
    assert "bob@external.com" in agent.allowlist


def test_email_inbox_and_search(test_setup):
    client, agent, backend = test_setup
    # List all
    resp = client.get("/api/email/inbox")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert data["source"] == "real"
    assert data["emails"][0]["id"] == "msg_001"

    # Filter unread
    resp_unread = client.get("/api/email/inbox?unread_only=true")
    assert resp_unread.status_code == 200
    assert resp_unread.json()["count"] == 1
    assert resp_unread.json()["emails"][0]["id"] == "msg_001"

    # Search query
    resp_search = client.get("/api/email/inbox?query=lunch")
    assert resp_search.status_code == 200
    assert resp_search.json()["count"] == 1
    assert resp_search.json()["emails"][0]["id"] == "msg_002"


def test_email_read_and_mark_read(test_setup):
    client, agent, backend = test_setup
    # Read message
    resp = client.get("/api/email/messages/msg_001")
    assert resp.status_code == 200
    assert resp.json()["email"]["subject"] == "Quarterly Sync"

    # Read nonexistent message
    resp_404 = client.get("/api/email/messages/msg_999")
    assert resp_404.status_code == 404

    # Mark as read
    resp_read = client.post("/api/email/messages/msg_001/read")
    assert resp_read.status_code == 200
    assert resp_read.json()["result"]["read"] is True


def test_email_draft_creation(test_setup):
    client, agent, backend = test_setup
    resp = client.post("/api/email/draft", json={
        "to": ["alice@trusted.com"],
        "subject": "Follow-up",
        "body": "Thanks for the meeting!"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["result"]["status"] == "draft_created"
    assert len(backend.drafts) == 1


def test_email_send_dry_run_and_ledger(test_setup):
    client, agent, backend = test_setup
    # Agent is in dry_run mode
    assert agent.dry_run is True

    resp = client.post("/api/email/send", json={
        "to": ["alice@trusted.com"],
        "subject": "Hello Alice",
        "body": "Checking in."
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["status"] == "dry_run"
    assert len(backend.sent) == 0  # Not sent in live mailbox

    # Check ledger
    resp_ledger = client.get("/api/email/actions")
    assert resp_ledger.status_code == 200
    actions = resp_ledger.json()["actions"]
    assert len(actions) >= 1
    assert actions[0]["action"] == "send_email"
    assert actions[0]["outcome"]["status"] == "dry_run"

    # Clear ledger
    resp_clear = client.delete("/api/email/actions")
    assert resp_clear.status_code == 200
    assert resp_clear.json()["cleared"] is True
    assert client.get("/api/email/actions").json()["count"] == 0


def test_email_send_allowlist_blocking(test_setup):
    client, agent, backend = test_setup
    # Turn off dry-run to trigger live allowlist check
    agent.dry_run = False
    agent.allowlist = ["alice@trusted.com"]

    # Attempt send to unauthorized recipient
    resp = client.post("/api/email/send", json={
        "to": ["attacker@evil.com"],
        "subject": "Exfil",
        "body": "Secret data"
    })
    assert resp.status_code == 403
    assert "not in REAL_EMAIL_SEND_ALLOWLIST" in resp.json()["detail"]


def test_email_delete_message(test_setup):
    client, agent, backend = test_setup
    # In dry run mode
    resp = client.delete("/api/email/messages/msg_001")
    assert resp.status_code == 200
    assert resp.json()["result"]["status"] == "dry_run"


def test_email_run_pipeline(test_setup):
    client, agent, backend = test_setup
    plan = {
        "tool_calls": [
            {
                "id": "1",
                "function_name": "email.list_inbox",
                "args": {"unread_only": True},
                "depends_on": [],
                "arg_sources": {},
                "risk": "read",
                "justification": "List unread emails as requested",
            }
        ]
    }
    client.app.state.llm_factory = lambda **kwargs: FakeLLM(responses={"planner": [json.dumps(plan)]})

    resp = client.post("/api/email/run", json={
        "command": "Check my unread emails",
        "email_agent": "real",
        "defense": "ours"
    })
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    assert run_id

    # Verify run record in API
    run_resp = client.get(f"/api/runs/{run_id}")
    assert run_resp.status_code == 200
    assert run_resp.json()["track"] == "real"
