"""Dedicated REST endpoints for the Real Email Agent (and Mock fallback).

Provides the frontend team with:
- GET /api/email/status: Active configuration, backend type, auth state, and inbox counters
- POST /api/email/config: Runtime toggles for mock/real, mode, dry-run, and send allowlist
- GET /api/email/inbox: List inbox messages (with unread_only and search support)
- GET /api/email/messages/{email_id}: Read specific message details
- POST /api/email/messages/{email_id}/read: Mark message as read
- DELETE /api/email/messages/{email_id}: Trash message (respects mode and dry-run)
- POST /api/email/draft: Create email draft
- POST /api/email/send: Send email or simulate in dry-run (respects allowlist and cap)
- GET /api/email/actions: Action ledger of all write actions
- DELETE /api/email/actions: Clear the action ledger
- POST /api/email/run: Execute an email prompt directly through the security defense pipeline
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from agents.email import EmailAgent
from agents.real_email_agent import ActionLedger, RealEmailAgent, create_email_agent
from .schemas import (
    EmailConfigUpdate,
    EmailDraftRequest,
    EmailRunRequest,
    EmailSendRequest,
    RunCreate,
)

router = APIRouter(prefix="/api/email", tags=["Email Agent"])


def _get_active_real_agent(request: Request) -> RealEmailAgent | None:
    """Return an injected or singleton RealEmailAgent instance if available."""
    if hasattr(request.app.state, "real_email_agent") and request.app.state.real_email_agent is not None:
        return request.app.state.real_email_agent
    return None


def get_agent_instance(
    request: Request,
    agent_override: Literal["real", "mock"] | None = None,
) -> tuple[Any, str]:
    """Resolve the email agent instance and return (agent, 'real' | 'mock')."""
    configured = agent_override or os.environ.get("EMAIL_AGENT", "mock").lower()
    if configured == "mock":
        return EmailAgent(), "mock"

    injected = _get_active_real_agent(request)
    if injected is not None:
        return injected, "real"

    try:
        real_agent = create_email_agent(force_mock=False)
        return real_agent, "real"
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Real email agent is not ready: {exc}. Please check your credentials or switch to mock mode.",
        ) from exc


def _check_auth_status() -> dict[str, Any]:
    user = os.environ.get("EMAIL_USER", "")
    pwd = os.environ.get("EMAIL_PASSWORD", "") or os.environ.get("APP_PASSWORD", "")
    has_imap_creds = bool(user and pwd)
    backend_type = os.environ.get("EMAIL_BACKEND", "imap" if has_imap_creds else "gmail").lower()
    if backend_type == "imap":
        host = os.environ.get("IMAP_HOST", "imap.gmail.com" if user.endswith("@gmail.com") else "")
        return {
            "type": "imap",
            "configured": bool(user and pwd and host),
            "host": host or None,
            "user": user or None,
            "error": None if (user and pwd and host) else "EMAIL_USER, and EMAIL_PASSWORD (or APP_PASSWORD) must be set in .env",
        }
    else:
        creds_path = Path(os.environ.get("GMAIL_CREDENTIALS_PATH", "backend/.secrets/credentials.json"))
        tok_path = Path(os.environ.get("GMAIL_TOKEN_PATH", "backend/.secrets/gmail_token.json"))
        exists_creds = creds_path.exists()
        exists_tok = tok_path.exists()
        error = None
        if not exists_creds and not exists_tok:
            error = f"Gmail credentials not found at {creds_path}. Place credentials.json in .secrets/ or run OAuth flow."
        return {
            "type": "gmail",
            "configured": exists_creds or exists_tok,
            "credentials_path": str(creds_path),
            "credentials_exist": exists_creds,
            "token_path": str(tok_path),
            "token_exists": exists_tok,
            "error": error,
        }


# ---------------------------------------------------------------------------
# Status & Configuration
# ---------------------------------------------------------------------------

@router.get("/status")
def email_status(request: Request) -> dict[str, Any]:
    """Return complete real/mock email agent operational status."""
    configured_agent = os.environ.get("EMAIL_AGENT", "mock").lower()
    mode = os.environ.get("REAL_EMAIL_MODE", "readonly")
    dry_run = os.environ.get("REAL_EMAIL_DRY_RUN", "1") != "0"
    raw_allowlist = os.environ.get("REAL_EMAIL_SEND_ALLOWLIST", "")
    send_allowlist = [a.strip().lower() for a in raw_allowlist.split(",") if a.strip()]
    auth = _check_auth_status()

    inbox_stats: dict[str, Any] = {"total": None, "unread": None, "error": None}
    active_source = configured_agent

    # Attempt a lightweight inbox probe
    try:
        agent, active_source = get_agent_instance(request)
        if hasattr(agent, "backend") and hasattr(agent.backend, "get_inbox_stats"):
            stats = agent.backend.get_inbox_stats()
            inbox_stats["total"] = stats["total"]
            inbox_stats["unread"] = stats["unread"]
        else:
            inbox = agent.list_inbox()
            emails = inbox.get("emails", [])
            inbox_stats["total"] = len(emails)
            inbox_stats["unread"] = sum(1 for m in emails if not m.get("read", False))
    except Exception as exc:
        inbox_stats["error"] = str(exc)

    return {
        "configured_agent": configured_agent,
        "active_agent": active_source,
        "backend_type": os.environ.get("EMAIL_BACKEND", "gmail").lower(),
        "mode": mode,
        "dry_run": dry_run,
        "send_allowlist": send_allowlist,
        "max_high_impact": int(os.environ.get("REAL_EMAIL_MAX_HIGH_IMPACT", "3")),
        "body_max_chars": int(os.environ.get("EMAIL_BODY_MAX_CHARS", "4000")),
        "auth": auth,
        "inbox_stats": inbox_stats,
    }


@router.post("/config")
def update_email_config(request: Request, body: EmailConfigUpdate) -> dict[str, Any]:
    """Dynamically update email agent configuration at runtime."""
    if body.email_agent is not None:
        os.environ["EMAIL_AGENT"] = body.email_agent
    if body.mode is not None:
        os.environ["REAL_EMAIL_MODE"] = body.mode
    if body.dry_run is not None:
        os.environ["REAL_EMAIL_DRY_RUN"] = "1" if body.dry_run else "0"
    if body.send_allowlist is not None:
        os.environ["REAL_EMAIL_SEND_ALLOWLIST"] = ",".join(body.send_allowlist)

    # Sync with injected real agent if present
    injected = _get_active_real_agent(request)
    if injected is not None:
        if body.dry_run is not None:
            injected.dry_run = body.dry_run
        if body.send_allowlist is not None:
            injected.allowlist = body.send_allowlist

    return email_status(request)


# ---------------------------------------------------------------------------
# Mailbox Access
# ---------------------------------------------------------------------------

@router.get("/inbox")
def list_inbox(
    request: Request,
    unread_only: bool = Query(False, description="Filter for unread messages only"),
    limit: int = Query(25, ge=1, le=100, description="Maximum messages to return"),
    query: str | None = Query(None, description="Optional search term for subject/body"),
    agent: Literal["real", "mock"] | None = Query(None, description="Force real or mock agent"),
) -> dict[str, Any]:
    """Retrieve emails from the active agent."""
    active_agent, source = get_agent_instance(request, agent)
    try:
        if query:
            result = active_agent.search_emails(query=query)
        else:
            result = active_agent.list_inbox(unread_only=unread_only)
    except Exception as exc:
        raise HTTPException(500, f"Failed to list inbox: {exc}") from exc

    emails = result.get("emails", [])
    if limit:
        emails = emails[:limit]
    return {"emails": emails, "count": len(emails), "source": source}


@router.get("/messages/{email_id}")
def read_message(
    email_id: str,
    request: Request,
    agent: Literal["real", "mock"] | None = Query(None),
) -> dict[str, Any]:
    """Read a specific message by ID."""
    active_agent, source = get_agent_instance(request, agent)
    try:
        msg = active_agent.read_email(email_id=email_id)
        return {"email": msg, "source": source}
    except KeyError:
        raise HTTPException(404, f"Message '{email_id}' not found")
    except Exception as exc:
        raise HTTPException(500, f"Failed to read message '{email_id}': {exc}") from exc


@router.post("/messages/{email_id}/read")
def mark_read(
    email_id: str,
    request: Request,
    agent: Literal["real", "mock"] | None = Query(None),
) -> dict[str, Any]:
    """Mark a message as read."""
    active_agent, source = get_agent_instance(request, agent)
    try:
        result = active_agent.mark_read(email_id=email_id)
        return {"id": email_id, "result": result, "source": source}
    except KeyError:
        raise HTTPException(404, f"Message '{email_id}' not found")
    except Exception as exc:
        raise HTTPException(500, f"Failed to mark read: {exc}") from exc


@router.delete("/messages/{email_id}")
def delete_message(
    email_id: str,
    request: Request,
    agent: Literal["real", "mock"] | None = Query(None),
) -> dict[str, Any]:
    """Delete / trash a message (respects mode and dry-run)."""
    active_agent, source = get_agent_instance(request, agent)
    try:
        result = active_agent.delete_email(email_id=email_id)
        return {"id": email_id, "result": result, "source": source}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError:
        raise HTTPException(404, f"Message '{email_id}' not found")
    except Exception as exc:
        raise HTTPException(500, f"Failed to delete message: {exc}") from exc


# ---------------------------------------------------------------------------
# Compose: Draft & Send
# ---------------------------------------------------------------------------

@router.post("/draft")
def create_draft(request: Request, body: EmailDraftRequest) -> dict[str, Any]:
    """Create a draft message."""
    active_agent, source = get_agent_instance(request, body.agent)
    try:
        result = active_agent.create_draft(to=body.to, subject=body.subject, body=body.body)
        return {"status": "ok", "result": result, "source": source}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Failed to create draft: {exc}") from exc


@router.post("/send")
def send_email(request: Request, body: EmailSendRequest) -> dict[str, Any]:
    """Send an email or simulate in dry-run mode."""
    active_agent, source = get_agent_instance(request, body.agent)
    try:
        result = active_agent.send_email(
            to=body.to,
            subject=body.subject,
            body=body.body,
            cc=body.cc,
        )
        return {"status": "ok", "result": result, "source": source}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Failed to send email: {exc}") from exc


# ---------------------------------------------------------------------------
# Action Ledger
# ---------------------------------------------------------------------------

@router.get("/actions")
@router.get("/ledger")
def get_action_ledger(request: Request) -> dict[str, Any]:
    """Return all recorded mutation actions from the ledger."""
    injected = _get_active_real_agent(request)
    if injected is not None:
        entries = injected.ledger.entries
    else:
        ledger_path = Path("backend/logs/real_email_actions.jsonl")
        entries = []
        if ledger_path.exists():
            for line in ledger_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return {"actions": list(reversed(entries)), "count": len(entries)}


@router.delete("/actions")
@router.delete("/ledger")
def clear_action_ledger(request: Request) -> dict[str, Any]:
    """Clear recorded action ledger entries."""
    injected = _get_active_real_agent(request)
    if injected is not None:
        injected.ledger.clear()
    ledger_path = Path("backend/logs/real_email_actions.jsonl")
    if ledger_path.exists():
        ledger_path.write_text("", encoding="utf-8")
    return {"cleared": True}


# ---------------------------------------------------------------------------
# Direct Run Endpoint
# ---------------------------------------------------------------------------

@router.post("/run")
async def email_run(request: Request, body: EmailRunRequest) -> dict[str, Any]:
    """Execute an email task through the complete security pipeline (Gate + Planner + Executor)."""
    start_run_fn = getattr(request.app.state, "start_run", None)
    if not start_run_fn:
        raise HTTPException(500, "Runner service is not initialized on application")
    spec = RunCreate(
        command=body.command,
        agents=["email"],
        defense=body.defense,
        confirm_policy=body.confirm_policy,
        neutralize=body.neutralize,
        output_filter=body.output_filter,
        email_agent=body.email_agent,
    )
    run_id = await start_run_fn(spec)
    return {"run_id": run_id, "email_agent": body.email_agent}
