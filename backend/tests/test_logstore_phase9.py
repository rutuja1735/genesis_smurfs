import json

from core.audit import AuditLogger
from core.logstore import LogStore


def test_jsonl_audit_is_indexed_and_decision_searchable(tmp_path):
    store = LogStore(tmp_path / "index.db")
    audit = AuditLogger(tmp_path / "runs" / "run1.jsonl", "run1", store=store)
    audit.write("RUN_START", command="read inbox", defense="ours")
    audit.write("GATE_DECISION", decision="BLOCK", rule="R4", tool="banking.send_money",
                reason="unsafe value", reason_human="Blocked the transfer because its recipient was not verified.",
                args={"recipient": "unknown"})

    decisions = store.list_decisions(decision="BLOCK")
    assert len(decisions) == 1
    assert decisions[0]["rule"] == "R4"
    assert decisions[0]["reason_human"].startswith("Blocked the transfer")
    assert decisions[0]["agent"] == "banking"
    assert len(store.events_for_run("run1")) == 2


def test_reindex_rebuilds_run_and_decision_index_from_jsonl(tmp_path):
    logs = tmp_path / "logs"
    run_dir = logs / "runs"
    run_dir.mkdir(parents=True)
    records = [
        {"run_id": "abc", "event": "RUN_START", "ts": "2026-01-01T00:00:00Z", "command": "test", "defense": "ours"},
        {"run_id": "abc", "event": "GATE_DECISION", "ts": "2026-01-01T00:00:01Z", "decision": "BLOCK", "rule": "R4", "tool": "banking.send_money", "reason_human": "Blocked safely."},
    ]
    (run_dir / "abc.jsonl").write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
    store = LogStore(logs / "index.db")
    assert store.reindex(logs) == 2
    assert store.get_run("abc")["command"] == "test"
    assert len(store.list_decisions(decision="BLOCK")) == 1
