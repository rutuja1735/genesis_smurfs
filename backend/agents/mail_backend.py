"""MailBackend Protocol and NormalizedEmail model.

All fields in NormalizedEmail that originate from external email content are
UNTRUSTED by definition. The 'from' header is spoofable; never treat it as a
trusted identity. Security decisions are made in core/, not here.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Zero-width / bidi control characters — classic injection vector
# ---------------------------------------------------------------------------
_ZERO_WIDTH = re.compile(
    "[\u200b-\u200f\u202a-\u202e\u2060\ufeff\u00ad]"  # ZW, bidi, soft-hyphen
)


# ---------------------------------------------------------------------------
# HTML-to-text sanitiser — shared by GmailBackend and ImapBackend
# ---------------------------------------------------------------------------

def _strip_hidden_html(html: str) -> tuple[str, int]:
    """Remove content that is invisible to a human, returning (cleaned, count_removed).

    Invisible content includes:
    - display:none / visibility:hidden / font-size:0 inline styles
    - white-on-white text (approximated by color:#fff* or similar)
    - HTML comments
    - hidden / aria-hidden elements
    - <script> and <style> blocks
    - Elements with class/id containing 'hidden'

    We keep track of how many hidden-text blocks were removed so the scanner
    can treat a non-zero count as a medium-severity signal.
    """
    removed_count = 0

    # Remove HTML comments <!-- ... -->
    cleaned, n = re.subn(r"<!--.*?-->", "", html, flags=re.DOTALL)
    removed_count += n
    html = cleaned

    # Remove <style> and <script> blocks entirely
    for tag in ("style", "script"):
        pattern = rf"<\s*{tag}[^>]*>.*?<\s*/\s*{tag}\s*>"
        cleaned, n = re.subn(pattern, "", html, flags=re.DOTALL | re.IGNORECASE)
        removed_count += n
        html = cleaned

    # Remove tags whose inline style makes them invisible
    _INVISIBLE_STYLE = re.compile(
        r"(?:"
        r"display\s*:\s*none"
        r"|visibility\s*:\s*hidden"
        r"|font-size\s*:\s*0(?:px|pt|em|rem|%)?"
        r"|opacity\s*:\s*0(?:\.0+)?"
        r"|color\s*:\s*(?:#fff(?:fff)?|white|rgba?\(\s*255\s*,\s*255\s*,\s*255)"
        r")",
        re.IGNORECASE,
    )

    def _remove_invisible_style_tags(text: str) -> str:
        nonlocal removed_count
        _HIDDEN_STYLE = re.compile(
            r"<([a-zA-Z][a-zA-Z0-9]*)"   # tag name
            r"([^>]*?)"                   # other attributes
            r"style\s*=\s*[\"']([^\"']*)[\"']"  # style attribute
            r"([^>]*)>",
            re.IGNORECASE | re.DOTALL,
        )
        for _ in range(5):
            result = []
            pos = 0
            changed = False
            for m in _HIDDEN_STYLE.finditer(text):
                style = m.group(3)
                if _INVISIBLE_STYLE.search(style):
                    tag_name = m.group(1)
                    start = m.start()
                    end_tag = re.compile(
                        rf"<\s*/\s*{re.escape(tag_name)}\s*>", re.IGNORECASE
                    )
                    close = end_tag.search(text, m.end())
                    if close:
                        result.append(text[pos:start])
                        pos = close.end()
                        removed_count += 1
                        changed = True
                    else:
                        result.append(text[pos : m.end()])
                        pos = m.end()
            result.append(text[pos:])
            text = "".join(result)
            if not changed:
                break
        return text

    html = _remove_invisible_style_tags(html)

    # Remove aria-hidden="true" elements
    _ARIA_HIDDEN_TAG = re.compile(
        r"<([a-zA-Z][a-zA-Z0-9]*)[^>]*\baria-hidden\s*=\s*[\"']true[\"'][^>]*>",
        re.IGNORECASE,
    )
    for m in list(_ARIA_HIDDEN_TAG.finditer(html)):
        tag_name = m.group(1)
        end_tag = re.compile(
            rf"<\s*/\s*{re.escape(tag_name)}\s*>", re.IGNORECASE
        )
        close = end_tag.search(html, m.end())
        if close:
            html = html[: m.start()] + html[close.end() :]
            removed_count += 1

    # Remove elements with the 'hidden' attribute
    _HIDDEN_ATTR = re.compile(
        r"<([a-zA-Z][a-zA-Z0-9]*)[^>]*\bhidden\b[^>]*>",
        re.IGNORECASE,
    )
    for m in list(_HIDDEN_ATTR.finditer(html)):
        tag_name = m.group(1)
        if tag_name.lower() in ("input", "meta", "link", "br", "hr", "img"):
            continue  # self-closing, no inner content
        end_tag = re.compile(
            rf"<\s*/\s*{re.escape(tag_name)}\s*>", re.IGNORECASE
        )
        close = end_tag.search(html, m.end())
        if close:
            html = html[: m.start()] + html[close.end() :]
            removed_count += 1

    return html, removed_count


def html_to_text(html: str) -> tuple[str, int]:
    """Convert HTML to plain text. Return (text, hidden_text_removed_count).

    Steps:
    1. Strip invisible/hidden content (injection vector) — count removals.
    2. Replace block elements with newlines.
    3. Strip remaining tags.
    4. Decode HTML entities.
    5. Normalise whitespace.
    """
    cleaned_html, hidden_count = _strip_hidden_html(html)

    # Replace block-level tags with newlines
    cleaned_html = re.sub(
        r"<\s*/?\s*(?:p|div|br|h[1-6]|li|tr|blockquote|pre|hr)\b[^>]*>",
        "\n",
        cleaned_html,
        flags=re.IGNORECASE,
    )
    # Strip all remaining HTML tags
    text = re.sub(r"<[^>]+>", "", cleaned_html)

    # Basic HTML entity decoding
    _ENTITIES = {
        "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&apos;": "'",
        "&nbsp;": " ", "&#160;": " ",
    }
    for ent, char in _ENTITIES.items():
        text = text.replace(ent, char)
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)

    # Normalise whitespace but keep paragraph breaks
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, hidden_count


def strip_zero_width(text: str) -> str:
    """Strip zero-width and bidi control characters from the normalised body.

    The raw body is kept separately for provenance and audit. This function is
    applied ONLY to the body_text field of NormalizedEmail.
    """
    return _ZERO_WIDTH.sub("", text)


def normalize_unicode(text: str) -> str:
    """NFKC-normalise and strip zero-width chars."""
    return strip_zero_width(unicodedata.normalize("NFKC", text))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class AttachmentMeta(BaseModel):
    filename: str
    mime: str
    size: int  # bytes; 0 if unknown


class AuthResults(BaseModel):
    spf: str = "unknown"    # pass | fail | none | unknown
    dkim: str = "unknown"
    dmarc: str = "unknown"


class NormalizedEmail(BaseModel):
    """Canonical representation of an email message.

    IMPORTANT: every field here derived from external email content is
    UNTRUSTED. The 'from_addr' / 'from_display' fields are SPOOFABLE.
    Never use them for identity or access decisions.
    """
    id: str
    thread_id: str = ""
    from_addr: str                              # bare address only
    from_display: str = ""                      # display name (untrusted)
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    subject: str = ""
    body_text: str = ""                         # sanitised; zero-width stripped
    body_raw: str = ""                          # raw body for provenance / audit
    date: str = ""
    is_read: bool = False
    labels: list[str] = Field(default_factory=list)
    attachments: list[AttachmentMeta] = Field(default_factory=list)
    auth_results: AuthResults = Field(default_factory=AuthResults)
    was_truncated: bool = False
    hidden_text_removed: int = 0               # count of hidden blocks removed


# ---------------------------------------------------------------------------
# MailBackend Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class MailBackend(Protocol):
    """I/O adapter protocol. Implementors must NOT make allow/block decisions."""

    def list_messages(
        self,
        query: str = "",
        max_results: int = 20,
        unread_only: bool = False,
    ) -> list[NormalizedEmail]:
        """Return a list of message summaries (body_text may be empty or truncated)."""
        ...

    def get_message(self, id: str) -> NormalizedEmail:
        """Return the full message, including body_text."""
        ...

    def create_draft(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a draft. Return {id, status}."""
        ...

    def send(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
    ) -> dict[str, Any]:
        """Send an email. Return {id, status}."""
        ...

    def forward(self, id: str, to: list[str]) -> dict[str, Any]:
        """Forward a message. Return {id, status}."""
        ...

    def trash(self, id: str) -> dict[str, Any]:
        """Move a message to trash. Return {id, status}."""
        ...

    def mark_read(self, id: str) -> dict[str, Any]:
        """Mark a message as read. Return {id, read: True}."""
        ...


# ---------------------------------------------------------------------------
# Helpers used by both GmailBackend and ImapBackend
# ---------------------------------------------------------------------------

def parse_auth_results(header_value: str) -> AuthResults:
    """Parse an Authentication-Results header into AuthResults.

    This is a best-effort parser; full RFC 7601 compliance is not required.
    Security decisions based on auth_results are made in core/gate.py, not here.
    """

    def _extract(protocol: str) -> str:
        pattern = re.compile(
            rf"\b{re.escape(protocol)}\s*=\s*(pass|fail|none|neutral|permerror|temperror|unknown)",
            re.IGNORECASE,
        )
        m = pattern.search(header_value)
        if m:
            val = m.group(1).lower()
            if val in ("pass", "fail", "none"):
                return val
            return "unknown"
        return "none"

    return AuthResults(
        spf=_extract("spf"),
        dkim=_extract("dkim"),
        dmarc=_extract("dmarc"),
    )


def extract_bare_address(addr: str) -> str:
    """Extract the bare email address from a display-name form.

    'Alice <alice@example.com>' -> 'alice@example.com'
    'alice@example.com' -> 'alice@example.com'

    Lowercases the result so comparisons are case-insensitive.
    """
    addr = addr.strip()
    # RFC 5322 angle-addr form: "Display Name <addr@domain>"
    angle = re.search(r"<([^>]+)>", addr)
    if angle:
        return angle.group(1).strip().lower()
    # Plain address
    if "@" in addr:
        return addr.lower()
    return addr.lower()


def addresses_match(candidate: str, trusted: str) -> bool:
    """Return True iff candidate and trusted bare addresses are the same.

    Protects against display-name tricks:
    'Alice <attacker@evil.com>' where 'Alice' looks like a trusted sender.
    Always compares only the bare address, lowercase.
    """
    return extract_bare_address(candidate) == extract_bare_address(trusted)
