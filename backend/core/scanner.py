"""Heuristic injection scanner. It reports spans and never edits source text."""

from __future__ import annotations

import base64
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class ScanMatch:
    severity: str
    matched: str
    start: int
    end: int
    excerpt: str


@dataclass(frozen=True)
class ScanResult:
    severity: str
    matches: tuple[ScanMatch, ...]


_PATTERNS: tuple[tuple[str, str], ...] = (
    ("high", r"\bignore\s+(?:all\s+|your\s+|the\s+)?(?:previous|prior|above)\s+instructions?\b"),
    ("high", r"\b(?:system\s+override|developer\s+message|system\s+notice)\b"),
    ("high", r"<\s*(?:information|system|instructions?)\b[^>]*>"),
    ("high", r"\b(?:assistant|ai|agent)\s*[:,]\s*(?:you\s+must|do\s+this|ignore|send|reveal|forward)\b"),
    ("high", r"\b(?:you\s+must\s+now|before\s+you\s+can\s+(?:solve|answer|continue))\b"),
    ("med", r"\bimportant\s+message\s+from\b"),
    ("med", r"\b(?:roleplay|role-play)\s+as\s+(?:the\s+)?(?:system|developer|assistant)\b"),
    ("low", r"\b(?:assistant|agent)\s+(?:should|could|please)\b"),
    ("med", r"\b[a-z0-9+/]{80,}={0,2}\b"),
)
_ZERO_WIDTH = re.compile("[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")


def _normalized_with_map(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    offsets: list[int] = []
    for index, char in enumerate(text):
        normalized = unicodedata.normalize("NFKC", char)
        for item in normalized:
            chars.append(item)
            offsets.append(index)
    return "".join(chars), offsets


def scan_text(text: str) -> ScanResult:
    normalized, offsets = _normalized_with_map(text)
    matches: list[ScanMatch] = []
    for severity, pattern in _PATTERNS:
        for match in re.finditer(pattern, normalized, re.IGNORECASE):
            start = offsets[match.start()] if match.start() < len(offsets) else 0
            end = offsets[match.end() - 1] + 1 if match.end() and match.end() - 1 < len(offsets) else len(text)
            matches.append(ScanMatch(severity, match.group(0), start, end, text[max(0, start - 60):min(len(text), end + 60)]))
    for match in _ZERO_WIDTH.finditer(text):
        matches.append(ScanMatch("high", "zero_width_or_bidi_control", match.start(), match.end(), text[max(0, match.start() - 60):min(len(text), match.end() + 60)]))
    # Prefer stronger classification for overlapping/duplicate spans.
    levels = {"low": 1, "med": 2, "high": 3}
    matches.sort(key=lambda item: (item.start, -levels[item.severity], item.end))
    dedup: list[ScanMatch] = []
    for item in matches:
        if dedup and item.start < dedup[-1].end:
            if levels[item.severity] > levels[dedup[-1].severity]:
                dedup[-1] = item
            continue
        dedup.append(item)
    overall = max((item.severity for item in dedup), key=lambda item: levels[item], default="low")
    return ScanResult(overall, tuple(dedup))


def scan_output(output: object) -> dict[str, ScanResult]:
    found: dict[str, ScanResult] = {}

    def visit(value: object, path: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")
        elif isinstance(value, str):
            result = scan_text(value)
            if result.matches:
                found[path] = result

    visit(output)
    return found


def scan_hidden_text_removed(hidden_text_removed: int) -> ScanResult | None:
    """Return a medium-severity ScanResult when hidden_text_removed > 0.

    A positive count means the MIME parser stripped invisible-HTML content
    from the message body, which is a classic injection vector. Feed this
    signal into the executor's injection detection path.

    Returns None when hidden_text_removed == 0 (no signal to report).
    """
    if hidden_text_removed <= 0:
        return None
    match = ScanMatch(
        severity="med",
        matched="hidden_text_removed",
        start=0,
        end=0,
        excerpt=(
            f"Email contained {hidden_text_removed} hidden HTML block(s) "
            "that were stripped before processing. This is a medium-severity "
            "injection signal."
        ),
    )
    return ScanResult("med", (match,))
