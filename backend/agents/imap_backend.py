"""ImapBackend: IMAP/SMTP fallback implementation of MailBackend.

Uses imaplib + smtplib with an app password from .env.
Shares MIME parsing helpers with GmailBackend via mail_backend module.
This is intentionally small; add features only as needed.

Security model:
- Pure I/O adapter. No allow/block decisions made here.
- All returned content is UNTRUSTED by definition.
- App password is never logged; audit masking happens in core/audit.py.
"""

from __future__ import annotations

import email as email_stdlib
import email.header
import imaplib
import logging
import os
import re
import smtplib
import socket
from email.mime.text import MIMEText
from typing import Any

from .mail_backend import (
    AttachmentMeta,
    AuthResults,
    NormalizedEmail,
    html_to_text,
    normalize_unicode,
    parse_auth_results,
    strip_zero_width,
)

log = logging.getLogger(__name__)

_DEFAULT_BODY_MAX = 4000


def _decode_header(value: str) -> str:
    parts = email.header.decode_header(value)
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


def _parse_address(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    m = re.search(r"<([^>]+)>", raw)
    if m:
        addr = m.group(1).strip().lower()
        display = raw[: m.start()].strip().strip('"').strip("'").strip()
        return addr, display
    if "@" in raw:
        return raw.lower(), ""
    return raw.lower(), ""


def _parse_address_list(raw: str) -> list[str]:
    addrs = []
    for part in re.split(r",(?![^<]*>)", raw):
        part = part.strip()
        if not part:
            continue
        addr, _ = _parse_address(part)
        if addr:
            addrs.append(addr)
    return addrs


def _extract_body_from_message(
    msg: email_stdlib.message.Message,
    body_max: int,
) -> tuple[str, str, int]:
    """Extract (body_text, body_raw, hidden_removed) from a parsed email.Message."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    hidden_total = 0

    def _walk(part: email_stdlib.message.Message) -> None:
        nonlocal hidden_total
        ct = (part.get_content_type() or "").lower()
        disp = (part.get_content_disposition() or "").lower()
        if disp == "attachment":
            return
        if part.is_multipart():
            for sub in part.get_payload(decode=False):  # type: ignore[arg-type]
                if isinstance(sub, email_stdlib.message.Message):
                    _walk(sub)
        elif ct == "text/plain":
            raw = part.get_payload(decode=True)
            if isinstance(raw, bytes):
                charset = part.get_param("charset") or "utf-8"
                try:
                    text = raw.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    text = raw.decode("latin-1", errors="replace")
                plain_parts.append(text)
        elif ct == "text/html":
            raw = part.get_payload(decode=True)
            if isinstance(raw, bytes):
                charset = part.get_param("charset") or "utf-8"
                try:
                    html_str = raw.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    html_str = raw.decode("latin-1", errors="replace")
                text, hidden_count = html_to_text(html_str)
                hidden_total += hidden_count
                html_parts.append(text)

    _walk(msg)

    if plain_parts:
        body = "\n\n".join(plain_parts)
        raw_body = body
    elif html_parts:
        body = "\n\n".join(html_parts)
        raw_body = body
    else:
        body = ""
        raw_body = ""

    body_text = strip_zero_width(body)
    was_trunc = len(body_text) > body_max
    return body_text[:body_max], raw_body, hidden_total


def _extract_attachments(msg: email_stdlib.message.Message) -> list[AttachmentMeta]:
    attachments = []
    for part in msg.walk():
        disp = part.get_content_disposition() or ""
        filename = part.get_filename()
        if filename and "attachment" in disp.lower():
            payload = part.get_payload(decode=True)
            size = len(payload) if isinstance(payload, bytes) else 0
            attachments.append(AttachmentMeta(
                filename=normalize_unicode(_decode_header(filename)),
                mime=part.get_content_type() or "application/octet-stream",
                size=size,
            ))
    return attachments


class ImapBackend:
    """IMAP/SMTP fallback implementation of MailBackend.

    Required env vars:
    - IMAP_HOST, IMAP_PORT (default 993)
    - SMTP_HOST, SMTP_PORT (default 587)
    - EMAIL_USER, EMAIL_PASSWORD (app password, never logged)
    - EMAIL_BODY_MAX_CHARS (default 4000)
    """

    def __init__(
        self,
        *,
        host: str | None = None,
        smtp_host: str | None = None,
        user: str | None = None,
        password: str | None = None,
        imap_port: int | None = None,
        smtp_port: int | None = None,
        mode: str | None = None,
        body_max_chars: int | None = None,
        _imap_conn: Any = None,  # injected in tests
    ) -> None:
        self.mode = (mode or os.environ.get("REAL_EMAIL_MODE", "readonly")).lower()
        user_val = user or os.environ.get("EMAIL_USER", "")
        pwd_val = password or os.environ.get("EMAIL_PASSWORD", "") or os.environ.get("APP_PASSWORD", "")
        self._user = user_val.strip()
        self._password = pwd_val.strip().replace(" ", "")
        default_host = "imap.gmail.com" if self._user.endswith("@gmail.com") else ""
        default_smtp = "smtp.gmail.com" if self._user.endswith("@gmail.com") else default_host
        self._host = host or os.environ.get("IMAP_HOST", default_host)
        self._smtp_host = smtp_host or os.environ.get("SMTP_HOST", default_smtp or self._host)
        self._imap_port = imap_port or int(os.environ.get("IMAP_PORT", "993"))
        self._smtp_port = smtp_port or int(os.environ.get("SMTP_PORT", "587"))
        self._body_max = body_max_chars if body_max_chars is not None else _DEFAULT_BODY_MAX
        self._imap: Any = _imap_conn  # test injection; None = real connection on demand

    def _get_imap(self) -> imaplib.IMAP4_SSL:
        if self._imap is None:
            conn = imaplib.IMAP4_SSL(self._host, self._imap_port)
            conn.login(self._user, self._password)
            self._imap = conn
        return self._imap  # type: ignore[return-value]

    def get_inbox_stats(self) -> dict[str, int]:
        """Fetch total and unread message counters in a single roundtrip."""
        imap = self._get_imap()
        _, data = imap.status("INBOX", "(MESSAGES UNSEEN)")
        if data and data[0]:
            raw = data[0].decode() if isinstance(data[0], bytes) else str(data[0])
            msgs_match = re.search(r"MESSAGES\s+(\d+)", raw)
            unseen_match = re.search(r"UNSEEN\s+(\d+)", raw)
            return {
                "total": int(msgs_match.group(1)) if msgs_match else 0,
                "unread": int(unseen_match.group(1)) if unseen_match else 0,
            }
        return {"total": 0, "unread": 0}

    def list_messages(
        self,
        query: str = "",
        max_results: int = 20,
        unread_only: bool = False,
    ) -> list[NormalizedEmail]:
        imap = self._get_imap()
        imap.select("INBOX")
        criterion = "UNSEEN" if unread_only else "ALL"
        if query:
            criterion = f'({criterion} SUBJECT "{query}")'
        _, data = imap.search(None, criterion)
        ids = (data[0].split() if data and data[0] else [])[-max_results:]
        results = []
        for msg_id_bytes in ids:
            try:
                msg_id = msg_id_bytes.decode() if isinstance(msg_id_bytes, bytes) else str(msg_id_bytes)
                email_obj = self._fetch(msg_id, full=False)
                results.append(email_obj)
            except Exception as exc:
                log.warning("IMAP fetch failed for %s: %s", msg_id_bytes, exc)
        return results

    def get_message(self, id: str) -> NormalizedEmail:
        return self._fetch(id, full=True)

    def create_draft(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
    ) -> dict[str, Any]:
        imap = self._get_imap()
        mime = self._build_mime(to=to, subject=subject, body=body, cc=cc or [])
        imap.append("Drafts", None, None, mime.as_bytes())
        return {"id": "", "status": "draft_created"}

    def send(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
    ) -> dict[str, Any]:
        mime = self._build_mime(to=to, subject=subject, body=body, cc=cc or [])
        with smtplib.SMTP(self._smtp_host, self._smtp_port) as smtp:
            smtp.starttls()
            smtp.login(self._user, self._password)  # password never logged
            smtp.sendmail(self._user, to + (cc or []), mime.as_string())
        return {"id": "", "status": "sent"}

    def forward(self, id: str, to: list[str]) -> dict[str, Any]:
        original = self._fetch(id, full=True)
        fwd_subject = f"Fwd: {original.subject}"
        fwd_body = (
            f"\n\n--- Forwarded message ---\n"
            f"From: {original.from_display} <{original.from_addr}>\n"
            f"Subject: {original.subject}\n\n"
            f"{original.body_text}"
        )
        return self.send(to=to, subject=fwd_subject, body=fwd_body)

    def trash(self, id: str) -> dict[str, Any]:
        imap = self._get_imap()
        imap.store(id, "+FLAGS", "\\Deleted")
        imap.expunge()
        return {"id": id, "status": "trashed"}

    def mark_read(self, id: str) -> dict[str, Any]:
        imap = self._get_imap()
        imap.store(id, "+FLAGS", "\\Seen")
        return {"id": id, "read": True}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fetch(self, msg_id: str, *, full: bool) -> NormalizedEmail:
        imap = self._get_imap()
        fetch_parts = "(RFC822)" if full else "(RFC822.HEADER FLAGS)"
        _, data = imap.fetch(msg_id, fetch_parts)
        raw_bytes = b""
        for item in data:
            if isinstance(item, tuple):
                raw_bytes = item[1]
                break
        msg = email_stdlib.message_from_bytes(raw_bytes)
        return self._normalize(msg_id, msg, full=full)

    def _normalize(
        self,
        msg_id: str,
        msg: email_stdlib.message.Message,
        *,
        full: bool,
    ) -> NormalizedEmail:
        from_raw = _decode_header(msg.get("From", ""))
        from_addr, from_display = _parse_address(from_raw)
        to_raw = _decode_header(msg.get("To", ""))
        cc_raw = _decode_header(msg.get("Cc", ""))
        subject = normalize_unicode(_decode_header(msg.get("Subject", "")))
        date = msg.get("Date", "")
        auth_raw = msg.get("Authentication-Results", "")
        auth_results = parse_auth_results(auth_raw) if auth_raw else AuthResults()
        labels: list[str] = []  # IMAP doesn't have Gmail-style labels
        is_read = False  # IMAP FLAGS not parsed in this minimal version

        body_text = ""
        body_raw_text = ""
        hidden_count = 0
        was_truncated = False
        attachments: list[AttachmentMeta] = []

        if full:
            body_text, body_raw_text, hidden_count = _extract_body_from_message(
                msg, self._body_max
            )
            was_truncated = len(body_raw_text) >= self._body_max
            attachments = _extract_attachments(msg)

        return NormalizedEmail(
            id=msg_id,
            thread_id="",
            from_addr=from_addr,
            from_display=normalize_unicode(from_display),
            to=_parse_address_list(to_raw),
            cc=_parse_address_list(cc_raw),
            subject=subject,
            body_text=body_text,
            body_raw=body_raw_text,
            date=date,
            is_read=is_read,
            labels=labels,
            attachments=attachments,
            auth_results=auth_results,
            was_truncated=was_truncated,
            hidden_text_removed=hidden_count,
        )

    @staticmethod
    def _build_mime(
        to: list[str],
        subject: str,
        body: str,
        cc: list[str],
    ) -> MIMEText:
        mime = MIMEText(body, "plain", "utf-8")
        mime["To"] = ", ".join(to)
        mime["Cc"] = ", ".join(cc) if cc else ""
        mime["Subject"] = subject
        return mime
