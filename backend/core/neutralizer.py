"""Creates a sanitized copy of tool output while preserving raw data elsewhere."""

from __future__ import annotations

import copy
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from .scanner import ScanResult, scan_text

Mode = Literal["off", "annotate", "redact"]
_ZERO_WIDTH = re.compile("[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_PROTECTED = re.compile(r"(?i)(?:\b[A-Z]{2}\d{2}[A-Z0-9 ]{10,32}\b|\b[\w.+-]+@[\w.-]+\.[A-Z]{2,}\b|https?://[^\s<>]+|\b\d+(?:[.,]\d{1,2})?\s?(?:USD|EUR|GBP|INR|\$|€|£|₹)\b|\b\d{5,}\b)")


@dataclass(frozen=True)
class SanitizedView:
    value: Any
    spans: int
    mode: str
    events: tuple[dict[str, Any], ...]


def _intersects(start: int, end: int, protected: list[tuple[int, int]]) -> bool:
    return any(start < right and end > left for left, right in protected)


def sanitize_text(text: str, mode: Mode = "redact", requested_values: list[str] | None = None, sink_field: bool = False) -> tuple[str, ScanResult, list[dict[str, Any]]]:
    raw = text
    normalized = unicodedata.normalize("NFKC", _ZERO_WIDTH.sub("", text))
    scan = scan_text(raw)
    if mode == "off":
        return normalized, scan, []
    if sink_field:
        return normalized, scan, [{"kind": "annotated_protected_sink_field", "severity": m.severity, "excerpt": m.excerpt} for m in scan.matches]
    protected = [(m.start(), m.end()) for m in _PROTECTED.finditer(raw)]
    for value in requested_values or []:
        if value:
            for match in re.finditer(re.escape(value), raw, re.IGNORECASE):
                protected.append((match.start(), match.end()))
    chunks: list[str] = []
    cursor = 0
    events: list[dict[str, Any]] = []
    index = 0
    for item in scan.matches:
        index += 1
        start, end = item.start, item.end
        if _intersects(start, end, protected):
            chunks.extend((raw[cursor:start], f'<suspected_injection severity="{item.severity}">{raw[start:end]}</suspected_injection>'))
            events.append({"kind": "annotated_protected_value", "severity": item.severity, "excerpt": item.excerpt})
        elif item.severity == "high" and mode == "redact":
            chunks.extend((raw[cursor:start], f"[REDACTED: suspected injected instruction #{index}, see security notes]"))
            events.append({"kind": "redacted", "severity": item.severity, "excerpt": item.excerpt})
        elif item.severity in {"high", "med"}:
            chunks.extend((raw[cursor:start], f'<suspected_injection severity="{item.severity}">{raw[start:end]}</suspected_injection>'))
            events.append({"kind": "annotated", "severity": item.severity, "excerpt": item.excerpt})
        else:
            continue
        cursor = end
    if cursor:
        chunks.append(raw[cursor:])
        result = "".join(chunks)
    else:
        result = raw
    result = unicodedata.normalize("NFKC", _ZERO_WIDTH.sub("", result))
    return result, scan, events


def sanitize(output: Any, mode: Mode = "redact", requested_values: list[str] | None = None, sink_fields: set[str] | None = None) -> SanitizedView:
    if mode not in {"off", "annotate", "redact"}:
        raise ValueError("mode must be off, annotate, or redact")
    copied = copy.deepcopy(output)
    events: list[dict[str, Any]] = []
    count = 0

    def visit(value: Any, path: str = "") -> Any:
        nonlocal count
        if isinstance(value, dict):
            return {key: visit(child, f"{path}.{key}" if path else str(key)) for key, child in value.items()}
        if isinstance(value, list):
            return [visit(child, f"{path}[{index}]") for index, child in enumerate(value)]
        if isinstance(value, str):
            leaf = path.rsplit(".", 1)[-1]
            is_sink = leaf in (sink_fields or set())
            result, scan_result, local_events = sanitize_text(value, mode, requested_values, is_sink)
            count += len(scan_result.matches)
            for event in local_events:
                events.append({"field": path, **event})
            return result
        return value

    sanitized = visit(copied)
    return SanitizedView(sanitized, count, mode, tuple(events))
