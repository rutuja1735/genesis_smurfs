"""Append-only JSONL audit writer with basic secret masking."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b"),
    re.compile(r"(?i)(password|passwd|api[_ -]?key|token)(\s*[:=]\s*)([^\s,;]+)"),
)


def _mask(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if re.search(r"password|secret|api[_-]?key|token", str(key), re.I) else _mask(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask(item) for item in value]
    if isinstance(value, str):
        result = value
        result = _SECRET_PATTERNS[0].sub("[REDACTED_IBAN]", result)
        result = _SECRET_PATTERNS[1].sub(r"\1\2[REDACTED]", result)
        return result
    return value


class JsonlAuditLog:
    def __init__(self, path: str | Path, run_id: str, case_id: str | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.case_id = case_id

    def write(self, event: str, **fields: Any) -> dict[str, Any]:
        record = {"ts": datetime.now(timezone.utc).isoformat(), "run_id": self.run_id}
        if self.case_id is not None:
            record["case_id"] = self.case_id
        record.update({"event": event, **fields})
        record = _mask(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            handle.flush()
        return record

    def decision(self, decision: Any, **fields: Any) -> dict[str, Any]:
        action = getattr(getattr(decision, "action", None), "value", getattr(decision, "action", None))
        rule = getattr(decision, "rule_id", None)
        reason = getattr(decision, "reason", None)
        human = getattr(decision, "reason_human", None)
        if action not in {"ALLOW", None} and not human:
            raise ValueError("every non-ALLOW decision must include reason_human")
        return self.write("GATE_DECISION", decision=action, rule=rule, reason=reason, reason_human=human, **fields)

    def output_filter(self, decision: Any, **fields: Any) -> dict[str, Any]:
        action = getattr(getattr(decision, "action", None), "value", getattr(decision, "action", None))
        if action not in {"ALLOW", None} and not getattr(decision, "reason_human", None):
            raise ValueError("every non-ALLOW decision must include reason_human")
        return self.write("FINAL_ANSWER_FILTER", decision=action, rule=getattr(decision, "rule_id", None), reason=getattr(decision, "reason", None), reason_human=getattr(decision, "reason_human", None), **fields)


class AuditLogger(JsonlAuditLog):
    """JSONL-first audit sink that also indexes events and publishes live updates."""

    def __init__(self, path: str | Path, run_id: str, case_id: str | None = None,
                 *, store: Any = None, event_bus: Any = None) -> None:
        super().__init__(path, run_id, case_id)
        self.store = store
        self.event_bus = event_bus

    def write(self, event: str, **fields: Any) -> dict[str, Any]:
        record = super().write(event, **fields)
        if self.store is not None:
            try:
                self.store.index_event(record)
            except Exception:
                # JSONL is the source of truth and remains available for reindex.
                pass
        if self.event_bus is not None:
            self.event_bus.publish(self.run_id, record)
        return record
