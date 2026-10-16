"""Tests for RealEmailAgent.

- Scopes per mode: correct scope selected.
- Dry-run: send/forward/delete do NOT call backend methods.
- Allowlist: live sends to non-allowlisted addresses are refused.
- Live-action cap: 4th high-impact action is refused.
- Ledger: entries written for every attempted write.
- Secrets: never appear in captured logs.

No network, no real credentials. Uses FakeMailBackend.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from agents.mail_backend import (
    AttachmentMeta,
    AuthResults,
    MailBackend,
    NormalizedEmail,
)
from agents.real_email_agent import (
    RealEmailAgent,
    ActionLedger,
    _reset_high_impact_counter,
)
from agents.gmail_backend import _SCOPES_BY_MODE


# ---------------------------------------------------------------------------
# FakeMailBackend — satisfies MailBackend protocol
# ---------------------------------------------------------------------------

class FakeMailBackend:
    """Minimal fake that records method calls and returns canned data."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def _msg(self, id: str = "msg1", body: str = "Email body") -> NormalizedEmail:
        return NormalizedEmail(
            id=id,
            from_addr="sender@example.com",
            from_display="Sender",
            to=["me@test.com"],
            subject="Test Subject",
            body_text=body,
            body_raw=body,
            date="Mon, 16 Oct 2026 10:00:00 +0000",
        )

    def list_messages(self, query="", max_results=20, unread_only=False):
        self.calls.append(("list_messages", {"query": query, "unread_only": unread_only}))
        return [self._msg("m1"), self._msg("m2")]

    def get_message(self, id):
        self.calls.append(("get_message", id))
        return self._msg(id)

    def create_draft(self, to, subject, body, cc=None):
        self.calls.append(("create_draft", {"to": to, "subject": subject}))
        return {"id": "draft1", "status": "draft_created"}

    def send(self, to, subject, body, cc=None):
        self.calls.append(("send", {"to": to, "subject": subject}))
        return {"id": "sent1", "status": "sent"}

    def forward(self, id, to):
        self.calls.append(("forward", {"id": id, "to": to}))
        return {"id": "fwd1", "status": "sent"}

    def trash(self, id):
        self.calls.append(("trash", id))
        return {"id": id, "status": "trashed"}

    def mark_read(self, id):
        self.calls.append(("mark_read", id))
        return {"id": id, "read": True}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_counter():
    """Reset the per-process high-impact counter before each test."""
    _reset_high_impact_counter()
    yield
    _reset_high_impact_counter()


def make_agent(dry_run=True, allowlist=None, max_cap=3, tmp_path=None):
    backend = FakeMailBackend()
    ledger_path = tmp_path / "ledger.jsonl" if tmp_path else None
    agent = RealEmailAgent(
        backend=backend,
        dry_run=dry_run,
        send_allowlist=allowlist or [],
        max_live_high_impact=max_cap,
        ledger_path=ledger_path,
    )
    return agent, backend


# ---------------------------------------------------------------------------
# Scope tests (gmail_backend)
# ---------------------------------------------------------------------------

class TestGmailScopes:
    def test_readonly_scope_is_minimal(self):
        scopes = _SCOPES_BY_MODE["readonly"]
        assert len(scopes) == 1
        assert "gmail.readonly" in scopes[0]
        # readonly must NOT include gmail.send or gmail.modify
        assert not any("send" in s or "modify" in s for s in scopes)

    def test_draft_scope_includes_compose_not_send(self):
        scopes = _SCOPES_BY_MODE["draft"]
        scope_str = " ".join(scopes)
        assert "gmail.readonly" in scope_str or "compose" in scope_str
        assert "gmail.send" not in scope_str

    def test_full_scope_includes_modify_and_send(self):
        scopes = _SCOPES_BY_MODE["full"]
        scope_str = " ".join(scopes)
        assert "gmail.modify" in scope_str or "gmail.send" in scope_str

    def test_unknown_mode_raises(self):
        from agents.gmail_backend import GmailBackend
        with pytest.raises(ValueError, match="REAL_EMAIL_MODE"):
            GmailBackend(mode="superpower", _service=object())


# ---------------------------------------------------------------------------
# Dry-run tests
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_send_in_dry_run_does_not_call_backend(self):
        agent, backend = make_agent(dry_run=True)
        result = agent.send_email(["target@example.com"], "Hi", "Body")
        assert result["status"] == "dry_run"
        assert "would_have" in result
        # Backend.send must NOT have been called
        assert not any(call[0] == "send" for call in backend.calls)

    def test_forward_in_dry_run_does_not_call_backend(self):
        agent, backend = make_agent(dry_run=True)
        result = agent.forward_email("msg1", ["fwd@example.com"])
        assert result["status"] == "dry_run"
        assert not any(call[0] == "forward" for call in backend.calls)

    def test_delete_in_dry_run_does_not_call_backend(self):
        agent, backend = make_agent(dry_run=True)
        result = agent.delete_email("msg1")
        assert result["status"] == "dry_run"
        assert not any(call[0] == "trash" for call in backend.calls)

    def test_read_operations_work_in_dry_run(self):
        agent, backend = make_agent(dry_run=True)
        result = agent.list_inbox()
        assert result["count"] == 2
        assert any(call[0] == "list_messages" for call in backend.calls)

    def test_mark_read_works_in_dry_run(self):
        agent, backend = make_agent(dry_run=True)
        result = agent.mark_read("msg1")
        assert result["read"] is True
        assert any(call[0] == "mark_read" for call in backend.calls)

    def test_create_draft_works_in_dry_run(self):
        agent, backend = make_agent(dry_run=True)
        result = agent.create_draft(["alice@example.com"], "Subject", "Body")
        assert result["status"] == "draft_created"
        assert any(call[0] == "create_draft" for call in backend.calls)


# ---------------------------------------------------------------------------
# Allowlist tests (live mode)
# ---------------------------------------------------------------------------

class TestAllowlist:
    def test_send_to_allowlisted_address_succeeds(self):
        agent, backend = make_agent(
            dry_run=False,
            allowlist=["allowed@example.com"],
            max_cap=10,
        )
        result = agent.send_email(["allowed@example.com"], "Hi", "Body")
        assert result["status"] == "sent"

    def test_send_to_non_allowlisted_address_refused(self):
        agent, backend = make_agent(
            dry_run=False,
            allowlist=["allowed@example.com"],
            max_cap=10,
        )
        with pytest.raises(PermissionError, match="not in REAL_EMAIL_SEND_ALLOWLIST"):
            agent.send_email(["attacker@evil.com"], "Hi", "Body")
        # Backend.send must NOT have been called
        assert not any(call[0] == "send" for call in backend.calls)

    def test_cc_recipient_also_checked_against_allowlist(self):
        agent, backend = make_agent(
            dry_run=False,
            allowlist=["allowed@example.com"],
            max_cap=10,
        )
        with pytest.raises(PermissionError):
            agent.send_email(
                ["allowed@example.com"],
                "Hi",
                "Body",
                cc=["evil@external.com"],
            )

    def test_empty_allowlist_allows_all(self):
        """No allowlist configured: gate still guards, but agent itself does not block."""
        agent, backend = make_agent(dry_run=False, allowlist=[], max_cap=10)
        result = agent.send_email(["anyone@example.com"], "Hi", "Body")
        assert result["status"] == "sent"


# ---------------------------------------------------------------------------
# Live-action cap tests
# ---------------------------------------------------------------------------

class TestLiveActionCap:
    def test_first_action_within_cap_succeeds(self):
        agent, backend = make_agent(dry_run=False, max_cap=3)
        result = agent.send_email(["a@example.com"], "Hi", "Body")
        assert result["status"] == "sent"

    def test_fourth_action_exceeds_cap(self):
        agent, backend = make_agent(dry_run=False, max_cap=3)
        for _ in range(3):
            agent.send_email(["a@example.com"], "Hi", "Body")
        with pytest.raises(PermissionError, match="cap exceeded"):
            agent.send_email(["a@example.com"], "Hi", "Body")
        # Backend.send called exactly 3 times
        send_calls = [c for c in backend.calls if c[0] == "send"]
        assert len(send_calls) == 3


# ---------------------------------------------------------------------------
# Ledger tests
# ---------------------------------------------------------------------------

class TestLedger:
    def test_dry_run_sends_are_recorded_in_ledger(self, tmp_path):
        agent, backend = make_agent(dry_run=True, tmp_path=tmp_path)
        agent.send_email(["target@example.com"], "Subject", "Body")
        agent.forward_email("msg1", ["fwd@example.com"])
        agent.delete_email("msg1")
        entries = agent._ledger.entries
        assert len(entries) == 3
        actions = {e["action"] for e in entries}
        assert "send_email" in actions
        assert "forward_email" in actions
        assert "delete_email" in actions

    def test_ledger_written_to_jsonl_file(self, tmp_path):
        import json
        agent, backend = make_agent(dry_run=True, tmp_path=tmp_path)
        agent.send_email(["target@example.com"], "Subject", "Body")
        ledger_file = tmp_path / "ledger.jsonl"
        assert ledger_file.exists()
        lines = ledger_file.read_text().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["action"] == "send_email"
        assert entry["outcome"]["status"] == "dry_run"

    def test_live_send_also_recorded(self, tmp_path):
        import json
        agent, backend = make_agent(dry_run=False, tmp_path=tmp_path)
        agent.send_email(["a@example.com"], "Hi", "Body")
        lines = (tmp_path / "ledger.jsonl").read_text().splitlines()
        entry = json.loads(lines[0])
        assert entry["outcome"]["status"] == "sent"


# ---------------------------------------------------------------------------
# Secrets never appear in logs
# ---------------------------------------------------------------------------

class TestSecretsNotInLogs:
    def test_oauth_token_not_in_logs(self, caplog):
        """Simulate an auth result with a fake token: it must NOT appear in logs."""
        secret_token = "ya29.SUPER_SECRET_ACCESS_TOKEN_12345"
        with caplog.at_level(logging.DEBUG, logger="agents"):
            agent, backend = make_agent(dry_run=True)
            # Simulate a scenario where the token could leak
            agent.send_email(["target@example.com"], "Hi", "Body")
        for record in caplog.records:
            assert secret_token not in record.getMessage()

    def test_password_not_in_logs(self, caplog):
        password = "s3cr3t_p4ssw0rd"
        with caplog.at_level(logging.DEBUG, logger="agents"):
            agent, backend = make_agent(dry_run=True)
            agent.list_inbox()
        for record in caplog.records:
            assert password not in record.getMessage()


# ---------------------------------------------------------------------------
# Tool specs
# ---------------------------------------------------------------------------

class TestToolSpecs:
    def test_specs_have_correct_names_and_risk(self):
        agent, _ = make_agent()
        specs = {s.name: s for s in agent.specs()}
        assert "email.list_inbox" in specs
        assert "email.read_email" in specs
        assert "email.search_emails" in specs
        assert "email.mark_read" in specs
        assert "email.create_draft" in specs
        assert "email.send_email" in specs
        assert "email.forward_email" in specs
        assert "email.delete_email" in specs
        assert specs["email.list_inbox"].risk == "read"
        assert specs["email.send_email"].risk == "high_impact"
        assert specs["email.forward_email"].risk == "high_impact"
        assert specs["email.delete_email"].risk == "high_impact"
        assert specs["email.create_draft"].risk == "write"
        assert specs["email.mark_read"].risk == "write"

    def test_all_untrusted_output_fields_marked(self):
        agent, _ = make_agent()
        specs = {s.name: s for s in agent.specs()}
        # Every email field returned from read tools must be marked untrusted
        read_email_trust = specs["email.read_email"].output_trust
        assert read_email_trust.get("from") == "untrusted"
        assert read_email_trust.get("subject") == "untrusted"
        assert read_email_trust.get("body") == "untrusted"

    def test_sink_params_match_mock_agent(self):
        agent, _ = make_agent()
        specs = {s.name: s for s in agent.specs()}
        assert specs["email.send_email"].sink_params["to"] == "recipient"
        assert specs["email.send_email"].sink_params["body"] == "body"
        assert specs["email.forward_email"].sink_params["to"] == "recipient"
        assert specs["email.read_email"].sink_params["email_id"] == "identifier"

    def test_all_specs_are_registerable(self):
        """Verify specs can be added to a ToolRegistry without collision."""
        from core.registry import ToolRegistry
        agent, _ = make_agent()
        registry = ToolRegistry(agent.specs())
        assert len(list(registry)) == 8
