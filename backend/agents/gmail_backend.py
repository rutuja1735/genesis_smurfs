"""GmailBackend: Gmail API implementation of MailBackend.

Security model:
- This is a pure I/O adapter. NO allow/block decisions are made here.
- All returned email content is UNTRUSTED. The gate in core/ enforces policy.
- OAuth secrets are never logged; secret masking happens in core/audit.py too.
- Scopes are determined by REAL_EMAIL_MODE in .env. We request the minimum.
- Retries with exponential backoff on 429/5xx. Never retry on 401/403.
"""

from __future__ import annotations

import base64
import email as email_stdlib
import email.header
import logging
import os
import time
from pathlib import Path
from typing import Any

from .mail_backend import (
    AttachmentMeta,
    AuthResults,
    MailBackend,
    NormalizedEmail,
    html_to_text,
    normalize_unicode,
    parse_auth_results,
    strip_zero_width,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scope configuration
# ---------------------------------------------------------------------------
_SCOPES_BY_MODE: dict[str, list[str]] = {
    "readonly": ["https://www.googleapis.com/auth/gmail.readonly"],
    "draft": [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
    ],
    "full": [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.send",
    ],
}

_SCOPE_ALLOWS: dict[str, set[str]] = {
    "readonly": {"list", "get"},
    "draft": {"list", "get", "draft"},
    "full": {"list", "get", "draft", "send", "trash", "mark_read"},
}


def _default_body_max() -> int:
    try:
        return int(os.environ.get("EMAIL_BODY_MAX_CHARS", "4000"))
    except ValueError:
        return 4000


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def _retry(fn: Any, *, max_retries: int = 3, base_delay: float = 1.0) -> Any:
    """Call fn() with exponential backoff on 429/5xx errors.

    Never retries on 401/403 (auth errors).
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            status = _http_status(exc)
            if status in {401, 403}:
                raise  # Auth errors: fail immediately
            if status is None or status < 400:
                raise  # Not an HTTP error we should retry
            last_exc = exc
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                log.warning(
                    "Gmail API error %s (attempt %d/%d), retrying in %.1fs",
                    status, attempt + 1, max_retries, delay,
                )
                time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def _http_status(exc: Exception) -> int | None:
    # google-api-python-client raises googleapiclient.errors.HttpError
    if hasattr(exc, "resp") and hasattr(exc.resp, "status"):
        try:
            return int(exc.resp.status)
        except (ValueError, TypeError):
            pass
    if hasattr(exc, "status_code"):
        return getattr(exc, "status_code", None)
    return None


# ---------------------------------------------------------------------------
# MIME decoding helpers
# ---------------------------------------------------------------------------

def _decode_header_value(raw: str) -> str:
    """Decode RFC 2047-encoded header value."""
    parts = email.header.decode_header(raw)
    result = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            try:
                result.append(chunk.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                result.append(chunk.decode("latin-1", errors="replace"))
        else:
            result.append(str(chunk))
    return "".join(result)


def _decode_b64url(data: str) -> bytes:
    """Decode base64url-encoded data (Gmail uses URL-safe base64)."""
    padded = data.replace("-", "+").replace("_", "/")
    padding = 4 - len(padded) % 4
    if padding != 4:
        padded += "=" * padding
    return base64.b64decode(padded)


def _extract_body_from_payload(payload: dict[str, Any]) -> tuple[str, str, int]:
    """Extract (body_text, body_raw, hidden_text_removed) from a Gmail message payload.

    Preference order: text/plain > text/html > first text/* part > empty.
    For HTML-only messages, strips hidden content and converts to text.
    """
    mime_type = (payload.get("mimeType") or "").lower()
    parts = payload.get("parts") or []

    # Leaf node with data
    if not parts:
        raw_data = (payload.get("body") or {}).get("data", "")
        if not raw_data:
            return "", "", 0
        try:
            raw_bytes = _decode_b64url(raw_data)
        except Exception:
            return "", "", 0
        raw_str = raw_bytes.decode("utf-8", errors="replace")
        if mime_type == "text/plain":
            stripped = strip_zero_width(raw_str)
            return stripped, raw_str, 0
        if mime_type == "text/html":
            text, hidden_count = html_to_text(raw_str)
            text = strip_zero_width(text)
            return text, raw_str, hidden_count
        return "", "", 0

    # multipart/alternative: prefer text/plain
    if "alternative" in mime_type:
        plain_part = next((p for p in parts if (p.get("mimeType") or "").lower() == "text/plain"), None)
        html_part = next((p for p in parts if (p.get("mimeType") or "").lower() == "text/html"), None)
        if plain_part:
            return _extract_body_from_payload(plain_part)
        if html_part:
            return _extract_body_from_payload(html_part)

    # multipart/mixed or other: recurse and concatenate text parts
    texts: list[str] = []
    raws: list[str] = []
    hidden_total = 0
    for part in parts:
        t, r, h = _extract_body_from_payload(part)
        if t:
            texts.append(t)
            raws.append(r)
            hidden_total += h
    return "\n\n".join(texts), "\n\n".join(raws), hidden_total


def _extract_attachments(payload: dict[str, Any]) -> list[AttachmentMeta]:
    """Recursively list attachment metadata. Never downloads content."""
    attachments: list[AttachmentMeta] = []
    parts = payload.get("parts") or []
    for part in parts:
        disposition = part.get("headers", [])
        disp_header = next(
            (h.get("value", "") for h in disposition if (h.get("name") or "").lower() == "content-disposition"),
            "",
        )
        filename = part.get("filename") or ""
        if not filename:
            # Recurse into multipart
            if (part.get("mimeType") or "").startswith("multipart/"):
                attachments.extend(_extract_attachments(part))
            continue
        size = int((part.get("body") or {}).get("size", 0))
        attachments.append(AttachmentMeta(
            filename=normalize_unicode(filename),
            mime=part.get("mimeType") or "application/octet-stream",
            size=size,
        ))
    return attachments


def _get_header(headers: list[dict[str, str]], name: str) -> str:
    for h in headers:
        if (h.get("name") or "").lower() == name.lower():
            return _decode_header_value(h.get("value", ""))
    return ""


def _parse_address_header(raw: str) -> tuple[str, str]:
    """Return (bare_address, display_name) from a raw From/To header value."""
    import re as _re
    raw = raw.strip()
    # "Display Name <addr@domain>" form
    m = _re.search(r"<([^>]+)>", raw)
    if m:
        addr = m.group(1).strip().lower()
        display = raw[: m.start()].strip().strip('"').strip("'").strip()
        return addr, display
    # Plain address
    if "@" in raw:
        return raw.lower(), ""
    return raw.lower(), ""


def _parse_address_list(raw: str) -> list[str]:
    """Parse a comma-separated list of addresses, returning bare addresses."""
    import re as _re
    addrs = []
    # Split on commas that are NOT inside angle brackets
    for part in _re.split(r",(?![^<]*>)", raw):
        part = part.strip()
        if not part:
            continue
        addr, _ = _parse_address_header(part)
        if addr:
            addrs.append(addr)
    return addrs


# ---------------------------------------------------------------------------
# GmailBackend
# ---------------------------------------------------------------------------

class GmailBackend:
    """Gmail API implementation of MailBackend.

    Uses google-api-python-client with an installed-app OAuth flow.
    Secrets are never logged here; masking also happens in JsonlAuditLog.
    """

    def __init__(
        self,
        *,
        credentials_path: str | Path | None = None,
        token_path: str | Path | None = None,
        mode: str | None = None,
        body_max_chars: int | None = None,
        _service: Any = None,  # injected in tests
    ) -> None:
        self._mode = (mode or os.environ.get("REAL_EMAIL_MODE", "readonly")).lower()
        if self._mode not in _SCOPES_BY_MODE:
            raise ValueError(
                f"REAL_EMAIL_MODE must be one of {list(_SCOPES_BY_MODE)}, got {self._mode!r}"
            )
        self._allowed_ops = _SCOPE_ALLOWS[self._mode]
        self._body_max = body_max_chars if body_max_chars is not None else _default_body_max()
        self._service: Any = _service  # set in tests to avoid network

        if _service is None:
            self._service = self._build_service(credentials_path, token_path)

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _build_service(
        self,
        credentials_path: str | Path | None,
        token_path: str | Path | None,
    ) -> Any:
        """Build and return the Gmail API service object."""
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ImportError(
                "Gmail dependencies not installed. Run: "
                "pip install google-api-python-client google-auth-oauthlib"
            ) from exc

        creds_path = Path(
            credentials_path
            or os.environ.get("GMAIL_CREDENTIALS_PATH", "backend/.secrets/credentials.json")
        )
        tok_path = Path(
            token_path
            or os.environ.get("GMAIL_TOKEN_PATH", "backend/.secrets/gmail_token.json")
        )
        tok_path.parent.mkdir(parents=True, exist_ok=True)

        scopes = _SCOPES_BY_MODE[self._mode]
        creds: Any = None

        if tok_path.exists():
            creds = Credentials.from_authorized_user_file(str(tok_path), scopes)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as exc:
                    log.warning("Token refresh failed: %s — re-running OAuth flow", type(exc).__name__)
                    creds = None
            if not creds:
                if not creds_path.exists():
                    raise FileNotFoundError(
                        f"Gmail credentials not found at {creds_path}. "
                        "Download them from the Google Cloud Console."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), scopes)
                creds = flow.run_local_server(port=0)
            # Save token at mode 600 (owner read/write only)
            tok_path.write_text(creds.to_json(), encoding="utf-8")
            try:
                tok_path.chmod(0o600)
            except NotImplementedError:
                pass  # Windows

        log.info("Gmail service authenticated (mode=%s)", self._mode)
        return build("gmail", "v1", credentials=creds)

    # ------------------------------------------------------------------
    # Scope guard
    # ------------------------------------------------------------------

    def _require_op(self, op: str) -> None:
        if op not in self._allowed_ops:
            raise PermissionError(
                f"Operation '{op}' is not permitted in mode '{self._mode}'. "
                f"Set REAL_EMAIL_MODE=full (or 'draft' for drafts)."
            )

    # ------------------------------------------------------------------
    # MailBackend implementation
    # ------------------------------------------------------------------

    def list_messages(
        self,
        query: str = "",
        max_results: int = 20,
        unread_only: bool = False,
    ) -> list[NormalizedEmail]:
        self._require_op("list")
        q_parts = [query] if query else []
        if unread_only:
            q_parts.append("is:unread")
        q = " ".join(q_parts)

        def _call() -> Any:
            return (
                self._service.users()
                .messages()
                .list(userId="me", q=q, maxResults=min(max_results, 500))
                .execute()
            )

        resp = _retry(_call)
        messages = resp.get("messages") or []
        result = []
        for msg in messages[:max_results]:
            try:
                email_obj = self._fetch_message(msg["id"], full=False)
                result.append(email_obj)
            except Exception as exc:
                log.warning("Failed to fetch message %s: %s", msg["id"], type(exc).__name__)
        return result

    def get_message(self, id: str) -> NormalizedEmail:
        self._require_op("get")
        return self._fetch_message(id, full=True)

    def create_draft(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
    ) -> dict[str, Any]:
        self._require_op("draft")
        raw = self._build_raw_mime(to=to, subject=subject, body=body, cc=cc or [])
        def _call() -> Any:
            return (
                self._service.users()
                .drafts()
                .create(userId="me", body={"message": {"raw": raw}})
                .execute()
            )
        resp = _retry(_call)
        return {"id": resp.get("id", ""), "status": "draft_created"}

    def send(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
    ) -> dict[str, Any]:
        self._require_op("send")
        raw = self._build_raw_mime(to=to, subject=subject, body=body, cc=cc or [])
        def _call() -> Any:
            return (
                self._service.users()
                .messages()
                .send(userId="me", body={"raw": raw})
                .execute()
            )
        resp = _retry(_call)
        return {"id": resp.get("id", ""), "status": "sent"}

    def forward(self, id: str, to: list[str]) -> dict[str, Any]:
        self._require_op("send")
        original = self._fetch_message(id, full=True)
        fwd_subject = f"Fwd: {original.subject}"
        fwd_body = (
            f"\n\n--- Forwarded message ---\n"
            f"From: {original.from_display} <{original.from_addr}>\n"
            f"Subject: {original.subject}\n\n"
            f"{original.body_text}"
        )
        return self.send(to=to, subject=fwd_subject, body=fwd_body)

    def trash(self, id: str) -> dict[str, Any]:
        self._require_op("trash")
        def _call() -> Any:
            return (
                self._service.users()
                .messages()
                .trash(userId="me", id=id)
                .execute()
            )
        _retry(_call)
        return {"id": id, "status": "trashed"}

    def mark_read(self, id: str) -> dict[str, Any]:
        self._require_op("mark_read")
        body = {"removeLabelIds": ["UNREAD"]}
        def _call() -> Any:
            return (
                self._service.users()
                .messages()
                .modify(userId="me", id=id, body=body)
                .execute()
            )
        _retry(_call)
        return {"id": id, "read": True}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_message(self, msg_id: str, *, full: bool) -> NormalizedEmail:
        fmt = "full" if full else "metadata"
        def _call() -> Any:
            return (
                self._service.users()
                .messages()
                .get(userId="me", id=msg_id, format=fmt)
                .execute()
            )
        msg = _retry(_call)
        return self._normalize_message(msg, full=full)

    def _normalize_message(self, msg: dict[str, Any], *, full: bool) -> NormalizedEmail:
        payload = msg.get("payload") or {}
        headers: list[dict[str, str]] = payload.get("headers") or []
        labels: list[str] = msg.get("labelIds") or []
        is_read = "UNREAD" not in labels

        from_raw = _get_header(headers, "From")
        from_addr, from_display = _parse_address_header(from_raw)
        to_raw = _get_header(headers, "To")
        cc_raw = _get_header(headers, "Cc")
        to_addrs = _parse_address_list(to_raw) if to_raw else []
        cc_addrs = _parse_address_list(cc_raw) if cc_raw else []
        subject = _get_header(headers, "Subject")
        date_raw = _get_header(headers, "Date")
        auth_raw = _get_header(headers, "Authentication-Results")
        auth_results = parse_auth_results(auth_raw) if auth_raw else AuthResults()

        body_text = ""
        body_raw_text = ""
        hidden_count = 0
        was_truncated = False
        attachments: list[AttachmentMeta] = []

        if full:
            body_text, body_raw_text, hidden_count = _extract_body_from_payload(payload)
            attachments = _extract_attachments(payload)
            # Truncate to configured limit
            max_chars = self._body_max
            if len(body_text) > max_chars:
                body_text = body_text[:max_chars]
                was_truncated = True
                log.debug(
                    "Message %s body truncated to %d chars (was_truncated=True)",
                    msg.get("id"), max_chars,
                )
            if len(body_raw_text) > max_chars * 2:
                body_raw_text = body_raw_text[: max_chars * 2]

        if hidden_count > 0:
            log.info(
                "Message %s: removed %d hidden text block(s) from body "
                "(potential injection content).",
                msg.get("id"), hidden_count,
            )

        return NormalizedEmail(
            id=msg.get("id", ""),
            thread_id=msg.get("threadId", ""),
            from_addr=from_addr,
            from_display=normalize_unicode(from_display),
            to=to_addrs,
            cc=cc_addrs,
            subject=normalize_unicode(subject),
            body_text=body_text,
            body_raw=body_raw_text,
            date=date_raw,
            is_read=is_read,
            labels=labels,
            attachments=attachments,
            auth_results=auth_results,
            was_truncated=was_truncated,
            hidden_text_removed=hidden_count,
        )

    @staticmethod
    def _build_raw_mime(
        to: list[str],
        subject: str,
        body: str,
        cc: list[str],
    ) -> str:
        """Build a base64url-encoded raw MIME message."""
        from email.mime.text import MIMEText
        msg = MIMEText(body, "plain", "utf-8")
        msg["To"] = ", ".join(to)
        msg["Cc"] = ", ".join(cc) if cc else ""
        msg["Subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        return raw
