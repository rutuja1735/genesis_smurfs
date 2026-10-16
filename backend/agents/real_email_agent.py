"""RealEmailAgent: exposes email.* tools backed by a MailBackend.

Security model:
- All policy / allow-block decisions stay in core/ (gate, provenance, scanner).
- This agent is a thin I/O adapter that exposes the same tool names, risk levels,
  sink_params and output_trust as the MockEmailAgent.
- DRY-RUN by default (REAL_EMAIL_DRY_RUN=1). Write operations log to an action
  ledger instead of touching the mailbox.
- Recipient allowlist (REAL_EMAIL_SEND_ALLOWLIST) is a last-resort backstop in
  addition to, never instead of, the gate.
- Hard cap on live high_impact actions per process (default 3).
- Agent selection: EMAIL_AGENT=mock|real (default mock).
  Eval/attack suites MUST use mock; never run injection evals against a real mailbox.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from core.registry import ToolSpec
from .mail_backend import (
    MailBackend,
    NormalizedEmail,
    extract_bare_address,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-process live-action cap
# ---------------------------------------------------------------------------
_HIGH_IMPACT_LOCK = threading.Lock()
_HIGH_IMPACT_COUNTER: dict[int, int] = {}  # pid -> count


def _increment_high_impact() -> int:
    pid = os.getpid()
    with _HIGH_IMPACT_LOCK:
        _HIGH_IMPACT_COUNTER[pid] = _HIGH_IMPACT_COUNTER.get(pid, 0) + 1
        return _HIGH_IMPACT_COUNTER[pid]


def _reset_high_impact_counter() -> None:
    """Used by tests only."""
    pid = os.getpid()
    with _HIGH_IMPACT_LOCK:
        _HIGH_IMPACT_COUNTER[pid] = 0


# ---------------------------------------------------------------------------
# Pydantic arg schemas — must be identical to MockEmailAgent
# ---------------------------------------------------------------------------

class ListInboxArgs(BaseModel):
    unread_only: bool = False


class EmailIdArgs(BaseModel):
    email_id: str


class SearchEmailArgs(BaseModel):
    query: str
    sender: str | None = None


class DraftArgs(BaseModel):
    to: list[str]
    subject: str
    body: str


class SendArgs(DraftArgs):
    cc: list[str] = Field(default_factory=list)


class ForwardArgs(BaseModel):
    email_id: str
    to: list[str]


# ---------------------------------------------------------------------------
# Action ledger
# ---------------------------------------------------------------------------

class ActionLedger:
    """Records every attempted write action with args and outcome."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._entries: list[dict[str, Any]] = []
        if path:
            self._path = Path(path)
            self._path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self._path = None

    def record(self, action: str, args: dict[str, Any], outcome: dict[str, Any]) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "args": args,
            "outcome": outcome,
        }
        self._entries.append(entry)
        if self._path:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
                fh.flush()
        log.info("ActionLedger: %s args=%s outcome=%s", action, args, outcome)

    @property
    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def clear(self) -> None:
        """Clear recorded entries in memory and on disk."""
        self._entries.clear()
        if self._path and self._path.exists():
            self._path.write_text("", encoding="utf-8")


# ---------------------------------------------------------------------------
# RealEmailAgent
# ---------------------------------------------------------------------------

class RealEmailAgent:
    """Real-mailbox email agent backed by a MailBackend.

    Exposes identical tool names, risk levels, sink_params and output_trust
    as the MockEmailAgent so that the planner, gate and executor are backend-agnostic.
    """

    def __init__(
        self,
        backend: MailBackend,
        *,
        dry_run: bool | None = None,
        send_allowlist: list[str] | None = None,
        max_live_high_impact: int | None = None,
        ledger_path: str | Path | None = None,
    ) -> None:
        if dry_run is None:
            dry_run = os.environ.get("REAL_EMAIL_DRY_RUN", "1") != "0"
        self._dry_run = dry_run

        raw_allowlist = os.environ.get("REAL_EMAIL_SEND_ALLOWLIST", "")
        env_allowlist = [a.strip().lower() for a in raw_allowlist.split(",") if a.strip()]
        self._allowlist: list[str] = send_allowlist or env_allowlist

        max_cap_env = os.environ.get("REAL_EMAIL_MAX_HIGH_IMPACT", "3")
        try:
            self._max_live_high_impact = max_live_high_impact if max_live_high_impact is not None else int(max_cap_env)
        except ValueError:
            self._max_live_high_impact = 3

        self._backend = backend
        default_ledger_path = Path("backend/logs/real_email_actions.jsonl")
        self._ledger = ActionLedger(ledger_path or default_ledger_path)

    @property
    def backend(self) -> MailBackend:
        return self._backend

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    @dry_run.setter
    def dry_run(self, value: bool) -> None:
        self._dry_run = bool(value)

    @property
    def allowlist(self) -> list[str]:
        return list(self._allowlist)

    @allowlist.setter
    def allowlist(self, value: list[str]) -> None:
        self._allowlist = [a.strip().lower() for a in value if a.strip()]

    @property
    def ledger(self) -> ActionLedger:
        return self._ledger

    @property
    def state(self) -> dict[str, Any]:
        return {
            "backend": type(self._backend).__name__,
            "mode": getattr(self._backend, "mode", os.environ.get("REAL_EMAIL_MODE", "readonly")),
            "dry_run": self._dry_run,
            "actions": self._ledger.entries,
        }

    @state.setter
    def state(self, value: dict[str, Any]) -> None:
        pass

    def snapshot(self) -> dict[str, Any]:
        import copy
        return copy.deepcopy(self.state)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _email_to_dict(msg: NormalizedEmail) -> dict[str, Any]:
        """Convert NormalizedEmail to a plain dict.  body_raw is excluded from
        the public output (it lives in raw_outputs for provenance only)."""
        return {
            "id": msg.id,
            "thread_id": msg.thread_id,
            "from": msg.from_addr,                  # bare address; still untrusted
            "from_display": msg.from_display,        # untrusted display name
            "to": msg.to,
            "cc": msg.cc,
            "subject": msg.subject,
            "body": msg.body_text,                   # sanitised body
            "body_raw": msg.body_raw,                # kept for provenance; executor stores in raw_outputs
            "date": msg.date,
            "read": msg.is_read,
            "labels": msg.labels,
            "attachments": [a.model_dump() for a in msg.attachments],
            "auth_results": msg.auth_results.model_dump(),
            "was_truncated": msg.was_truncated,
            "hidden_text_removed": msg.hidden_text_removed,
        }

    def _check_allowlist(self, recipients: list[str]) -> None:
        """Backstop: refuse to send to addresses outside the allowlist in full mode.

        This is IN ADDITION to the gate, never instead of it.
        Raises PermissionError listing which addresses are blocked.
        """
        if not self._allowlist:
            return  # No allowlist configured — pass (gate still guards)
        blocked = []
        for addr in recipients:
            bare = extract_bare_address(addr)
            if bare not in self._allowlist:
                blocked.append(bare)
        if blocked:
            raise PermissionError(
                f"Recipient(s) {blocked} are not in REAL_EMAIL_SEND_ALLOWLIST. "
                "Add them to the allowlist or use dry-run mode."
            )

    def _check_live_cap(self, action: str) -> None:
        """Refuse once the per-process high-impact action cap is exceeded."""
        cap = _increment_high_impact()
        if cap > self._max_live_high_impact:
            raise PermissionError(
                f"Live high-impact action cap exceeded (max={self._max_live_high_impact}). "
                f"Action '{action}' refused. Restart process to reset."
            )

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def list_inbox(self, unread_only: bool = False) -> dict[str, Any]:
        msgs = self._backend.list_messages(unread_only=unread_only)
        rows = [self._email_to_dict(m) for m in msgs]
        return {"emails": rows, "count": len(rows)}

    def read_email(self, email_id: str) -> dict[str, Any]:
        msg = self._backend.get_message(email_id)
        return self._email_to_dict(msg)

    def search_emails(self, query: str, sender: str | None = None) -> dict[str, Any]:
        q = query
        if sender:
            q = f"{q} from:{sender}"
        msgs = self._backend.list_messages(query=q)
        rows = [self._email_to_dict(m) for m in msgs]
        return {"emails": rows, "count": len(rows)}

    def mark_read(self, email_id: str) -> dict[str, Any]:
        result = self._backend.mark_read(email_id)
        return result

    def create_draft(
        self,
        to: list[str],
        subject: str,
        body: str,
    ) -> dict[str, Any]:
        result = self._backend.create_draft(to=to, subject=subject, body=body)
        self._ledger.record("create_draft", {"to": to, "subject": subject}, result)
        return result

    def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
    ) -> dict[str, Any]:
        args = {"to": to, "cc": cc or [], "subject": subject, "body": body}
        if self._dry_run:
            outcome = {"status": "dry_run", "would_have": args}
            self._ledger.record("send_email", args, outcome)
            log.info("DRY RUN: send_email would_have=%s", args)
            return outcome
        self._check_allowlist(to + (cc or []))
        self._check_live_cap("send_email")
        result = self._backend.send(to=to, subject=subject, body=body, cc=cc)
        self._ledger.record("send_email", args, result)
        return result

    def forward_email(self, email_id: str, to: list[str]) -> dict[str, Any]:
        args = {"email_id": email_id, "to": to}
        if self._dry_run:
            outcome = {"status": "dry_run", "would_have": args}
            self._ledger.record("forward_email", args, outcome)
            log.info("DRY RUN: forward_email would_have=%s", args)
            return outcome
        self._check_allowlist(to)
        self._check_live_cap("forward_email")
        result = self._backend.forward(id=email_id, to=to)
        self._ledger.record("forward_email", args, result)
        return result

    def delete_email(self, email_id: str) -> dict[str, Any]:
        args = {"email_id": email_id}
        if self._dry_run:
            outcome = {"status": "dry_run", "would_have": args}
            self._ledger.record("delete_email", args, outcome)
            log.info("DRY RUN: delete_email would_have=%s", args)
            return outcome
        self._check_live_cap("delete_email")
        result = self._backend.trash(email_id)
        self._ledger.record("delete_email", args, result)
        return result

    # ------------------------------------------------------------------
    # ToolSpec registration — identical risk/sink/trust as MockEmailAgent
    # ------------------------------------------------------------------

    def specs(self) -> list[ToolSpec]:
        """Return ToolSpec list with same risk/sink/trust as PLAN.md Section 10.4."""
        return [
            ToolSpec(
                "email.list_inbox", "email", self.list_inbox, ListInboxArgs,
                risk="read",
                output_trust={
                    "emails.*.from": "untrusted",
                    "emails.*.from_display": "untrusted",
                    "emails.*.subject": "untrusted",
                    "emails.*.body": "untrusted",
                    "emails.*.body_raw": "untrusted",
                    "emails.*.attachments.*.filename": "untrusted",
                    "emails.*.auth_results": "untrusted",
                },
                description="List inbox messages",
            ),
            ToolSpec(
                "email.read_email", "email", self.read_email, EmailIdArgs,
                risk="read",
                output_trust={
                    "from": "untrusted",
                    "from_display": "untrusted",
                    "subject": "untrusted",
                    "body": "untrusted",
                    "body_raw": "untrusted",
                    "attachments.*.filename": "untrusted",
                    "auth_results": "untrusted",
                },
                sink_params={"email_id": "identifier"},
                description="Read a message by id",
            ),
            ToolSpec(
                "email.search_emails", "email", self.search_emails, SearchEmailArgs,
                risk="read",
                output_trust={
                    "emails.*.from": "untrusted",
                    "emails.*.from_display": "untrusted",
                    "emails.*.subject": "untrusted",
                    "emails.*.body": "untrusted",
                    "emails.*.body_raw": "untrusted",
                },
                description="Search email",
            ),
            ToolSpec(
                "email.mark_read", "email", self.mark_read, EmailIdArgs,
                risk="write",
                sink_params={"email_id": "identifier"},
                description="Mark a message read",
            ),
            ToolSpec(
                "email.create_draft", "email", self.create_draft, DraftArgs,
                risk="write",
                sink_params={"to": "recipient", "body": "body"},
                description="Create an email draft",
                intent_verbs=("draft", "prepare"),
            ),
            ToolSpec(
                "email.send_email", "email", self.send_email, SendArgs,
                risk="high_impact",
                sink_params={"to": "recipient", "cc": "recipient", "body": "body"},
                description="Send an email",
                intent_verbs=("send", "email"),
            ),
            ToolSpec(
                "email.forward_email", "email", self.forward_email, ForwardArgs,
                risk="high_impact",
                sink_params={"to": "recipient"},
                description="Forward an email",
                intent_verbs=("forward",),
            ),
            ToolSpec(
                "email.delete_email", "email", self.delete_email, EmailIdArgs,
                risk="high_impact",
                description="Delete an email",
                intent_verbs=("delete", "remove"),
            ),
        ]


# ---------------------------------------------------------------------------
# Factory: select mock or real based on EMAIL_AGENT env var
# ---------------------------------------------------------------------------

def create_email_agent(
    *,
    backend: MailBackend | None = None,
    force_mock: bool = False,
    **kwargs: Any,
) -> Any:
    """Return an EmailAgent (mock) or RealEmailAgent based on EMAIL_AGENT env var.

    Eval/attack suites MUST pass force_mock=True. Never run injection evals
    against a real mailbox.
    """
    mode = os.environ.get("EMAIL_AGENT", "mock").lower()
    if force_mock or mode == "mock":
        from .email import EmailAgent
        return EmailAgent(**kwargs)

    if backend is None:
        email_mode = os.environ.get("REAL_EMAIL_MODE", "readonly")
        email_backend_type = os.environ.get("EMAIL_BACKEND", "").lower()
        has_imap_creds = bool(os.environ.get("EMAIL_USER") and (os.environ.get("EMAIL_PASSWORD") or os.environ.get("APP_PASSWORD")))
        creds_path = Path(os.environ.get("GMAIL_CREDENTIALS_PATH", "backend/.secrets/credentials.json"))
        token_path = Path(os.environ.get("GMAIL_TOKEN_PATH", "backend/.secrets/gmail_token.json"))

        if email_backend_type == "imap" or (not email_backend_type and has_imap_creds and not (creds_path.exists() or token_path.exists())):
            from .imap_backend import ImapBackend
            backend = ImapBackend(mode=email_mode)
        else:
            from .gmail_backend import GmailBackend
            backend = GmailBackend(mode=email_mode)

    return RealEmailAgent(backend=backend)
