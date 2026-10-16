import json

import pytest

from core.audit import JsonlAuditLog
from core.gate import Decision, DecisionAction
from core.output_filter import FilterDecision


def test_audit_writes_one_json_line_per_decision_and_masks_secrets(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit = JsonlAuditLog(path, "run-1")
    allow = Decision(DecisionAction.ALLOW, "", "ok", "")
    blocked = Decision(DecisionAction.BLOCK, "R4", "untrusted", "Blocked because source was untrusted")
    audit.decision(allow, tool="email.search")
    audit.decision(blocked, tool="banking.send_money", args={"iban": "GB82 WEST 1234 5698 7654 32"})
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert records[1]["reason_human"] and "[REDACTED_IBAN]" in json.dumps(records[1])


def test_non_allow_without_human_reason_is_rejected(tmp_path):
    audit = JsonlAuditLog(tmp_path / "audit.jsonl", "run-1")
    bad = Decision(DecisionAction.BLOCK, "R1", "blocked", "")
    with pytest.raises(ValueError):
        audit.decision(bad)


def test_output_filter_decision_is_audited_with_reason(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit = JsonlAuditLog(path, "run-1")
    audit.output_filter(FilterDecision(DecisionAction.BLOCK, "F1", "image removed", "Removed image because it could fetch remote content."), agent="final_answer")
    record = json.loads(path.read_text())
    assert record["event"] == "FINAL_ANSWER_FILTER"
    assert record["reason_human"]
