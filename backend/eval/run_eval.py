"""Budget-aware Track A evaluator. Real LLM use is always explicit."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents import create_mock_environment
from attacks import ATTACKS, GOALS, build_payload
from attacks.goals import ATT_IBAN
from baselines.react_agent import ReactAgent
from baselines.spotlighting import SpotlightingAgent
from core.audit import AuditLogger
from core.executor import Executor
from core.llm import OpenRouterClient, OpenRouterConfig
from core.logstore import LogStore
from core.planner import Planner
from tasks import TASKS, UserTask, tasks_for_suite

from .metrics import summarize
from .pairs_order import priority


def _attack_inputs(task: UserTask, goal_id: str, pattern_id: str) -> dict[str, str]:
    goal = next(item for item in GOALS if item.id == goal_id)
    pattern = next(item for item in ATTACKS if item.id == pattern_id)
    if not goal.vector or goal.vector not in task.vectors:
        return {}
    if pattern_id == "arg_poison":
        return {goal.vector: ""}
    return {goal.vector: build_payload(pattern_id, goal.description)}


def attack_pairs(suite: str, attack: str, *, include_heldout: bool = False) -> list[tuple[UserTask, str, str]]:
    tasks = tasks_for_suite(suite)
    patterns = list(ATTACKS) if attack == "all" else [next(item for item in ATTACKS if item.id == attack)]
    if not include_heldout:
        patterns = [item for item in patterns if not item.held_out]
    candidates: list[tuple[UserTask, str, str]] = []
    for task in tasks:
        for goal in GOALS:
            if goal.suite not in {"all", task.suite} or not goal.vector or goal.vector not in task.vectors:
                continue
            for pattern in patterns:
                candidates.append((task, goal.id, pattern.id))
    candidates.sort(key=lambda row: priority((row[0].id, row[1], row[2])))
    return candidates


def _run_one(task: UserTask, llm: OpenRouterClient, *, mode: str, defense: str,
             goal_id: str | None, attack_id: str | None, neutralize: str,
             output_filter: bool, out_dir: Path, confirm_policy: str = "deny",
             trial: int = 1) -> dict[str, Any]:
    injection = _attack_inputs(task, goal_id, attack_id) if goal_id and attack_id else {}
    env = create_mock_environment(injections=injection)
    if attack_id == "arg_poison" and goal_id in {"inj_bank_1", "inj_cross_1"}:
        bill = env.banking.state["files"].get("bill.txt", "")
        env.banking.state["files"]["bill.txt"] = bill.replace(
            "DE75512108001245126199", ATT_IBAN)
    case_id = f"{task.id}__{goal_id or 'benign'}__{attack_id or 'none'}__{defense}__t{trial}"
    run_id = uuid.uuid4().hex[:12]
    audit_path = out_dir / "runs" / f"{run_id}.jsonl"
    audit = AuditLogger(audit_path, run_id, case_id, store=llm.store)
    if hasattr(llm.store, "create_run"):
        llm.store.create_run(run_id, task.prompt, defense=defense, attack=attack_id,
                             injection_goal=goal_id, model=llm.config.model, status="running",
                             track="mock", jsonl_path=str(audit_path), case_id=case_id)
    llm.audit = audit
    llm.run_id = run_id
    usage_before = llm.store.usage_totals()
    pre_state = env.snapshot()
    decisions: list[Any] = []
    raw_answer = ""
    delivered = ""
    filter_rules: list[str] = []
    redacted_spans = 0
    injection_detections: list[dict[str, Any]] = []
    calls: list[str] = []
    final_hash: str | None = None
    try:
        audit.write("RUN_START", command=task.prompt, defense=defense, attack=attack_id,
                    injection_goal=goal_id, track="mock", model=llm.config.model, mode=mode)
        if defense in {"none", "spotlighting"}:
            agent = ReactAgent(llm) if defense == "none" else SpotlightingAgent(llm)
            output = agent.run(task.prompt, env)
            raw_answer = delivered = output["output"]
            calls = output["calls"]
        else:
            plan = Planner(llm, env.registry, audit=audit).plan(task.prompt, env.profile)
            result = Executor(env.registry, llm, neutralize_mode=neutralize,
                              output_filter_enabled=output_filter,
                              confirm_policy=confirm_policy,
                              audit=audit).run(
                                  task.prompt, plan, env.profile)
            final_hash = result.final.raw_answer_hash
            raw_answer = result.final.raw_answer
            delivered = result.final.delivered_answer
            decisions = list(result.decisions)
            calls = list(result.executed_calls)
            filter_rules = [item.rule_id for item in result.final.filter_decisions]
            injection_detections = list(result.injection_detections)
            redacted_spans = sum(event.get("action") == "redacted" for event in result.neutralizer_events)
        post_state = env.snapshot()
        goal = next((item for item in GOALS if item.id == goal_id), None)
        security = goal.security(pre_state, post_state, delivered) if goal else False
        security_raw = goal.security(pre_state, post_state, raw_answer) if goal else False
        utility = task.utility(delivered, pre_state, post_state)
        blocked = sum(getattr(decision, "action", None).value == "BLOCK" for decision in decisions)
        flagged = sum(getattr(decision, "action", None).value in {"FLAG", "NEEDS_CONFIRM"} for decision in decisions)
        audit.write("RUN_END", status="done", utility=utility, attack_succeeded=security,
                    delivered_answer=delivered, raw_answer_hash=final_hash)
        error = None
    except Exception as exc:
        post_state = env.snapshot()
        security = security_raw = False
        utility = False
        blocked = flagged = 0
        error = f"{type(exc).__name__}: {exc}"
        audit.write("RUN_ERROR", error=error, status="error")
    usage_after = llm.store.usage_totals()
    record = {
        "case_id": case_id, "run_id": run_id, "ts": datetime.now(timezone.utc).isoformat(),
        "track": "mock", "suite": task.suite, "task": task.id, "prompt": task.prompt,
        "mode": mode, "defense": defense, "attack": attack_id, "goal": goal_id, "trial": trial,
        "channel": next((item.channel for item in GOALS if item.id == goal_id), None),
        "utility": utility, "security": security, "security_raw_output": security_raw,
        "output": delivered, "state_diff": _diff(pre_state, post_state), "calls": calls,
        "blocked": blocked, "flagged": flagged, "filter_rules": filter_rules,
        "injection_expected": bool(goal_id),
        "injection_detected": bool(injection_detections),
        "false_positive_detections": int(mode == "benign" and bool(injection_detections)),
        "injections_detected": len(injection_detections),
        "injection_detection_details": injection_detections,
        "redacted_spans": redacted_spans, "false_positive_blocks": blocked if mode == "benign" else 0,
        "false_positive_filter_actions": len(filter_rules) if mode == "benign" else 0,
        "tokens_in": usage_after["tokens_in"] - usage_before["tokens_in"],
        "tokens_out": usage_after["tokens_out"] - usage_before["tokens_out"],
        "llm_calls": usage_after["llm_calls"] - usage_before["llm_calls"],
        "cost_usd": usage_after["cost_usd"] - usage_before["cost_usd"],
        "audit_path": str(audit_path), "error": error,
    }
    if hasattr(llm.store, "update_run"):
        llm.store.update_run(run_id, status="error" if error else "done", summary={
            "utility": utility, "attack_succeeded": security, "executed": len(calls),
            "blocked": blocked, "flagged": flagged, "cost_usd": record["cost_usd"],
        })
    return record


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    from agents import snapshot_diff
    return snapshot_diff(before, after)


def run_batch(*, suite: str, mode: str, attack: str, defense: str, batch_size: int,
              out_dir: str | Path, llm: OpenRouterClient, neutralize: str = "redact",
              output_filter: bool = True, include_heldout: bool = False,
              also_run_undefended: bool = False, offset: int | None = None,
              reset_cursor: bool = False, confirm_policy: str = "deny",
              trials: int = 1) -> dict[str, Any]:
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    store = llm.store
    if mode == "benign":
        case_list: list[tuple[UserTask, str | None, str | None]] = [(item, None, None) for item in tasks_for_suite(suite)]
    else:
        case_list = [(task, goal, pattern) for task, goal, pattern in attack_pairs(suite, attack, include_heldout=include_heldout)]
    cursor_key = f"mock:{suite}:{mode}:{attack}:{defense}"
    if reset_cursor:
        store.set_cursor(cursor_key, 0)
    start = offset if offset is not None else store.get_cursor(cursor_key)
    selected = case_list[start:start + batch_size]
    results_path = destination / "results.jsonl"
    records: list[dict[str, Any]] = []
    actual_mode = "attack_undefended" if mode == "attack_undefended" else mode
    actual_defense = "none" if mode == "attack_undefended" else defense
    for trial in range(1, trials + 1):
        for task, goal_id, attack_id in selected:
            row = _run_one(task, llm, mode=actual_mode, defense=actual_defense,
                           goal_id=goal_id, attack_id=attack_id, neutralize=neutralize,
                           output_filter=output_filter, out_dir=destination,
                           confirm_policy=confirm_policy, trial=trial)
            records.append(row)
            if also_run_undefended and mode == "attack_defended":
                records.append(_run_one(task, llm, mode=mode, defense="none", goal_id=goal_id,
                                        attack_id=attack_id, neutralize="off", output_filter=False,
                                        out_dir=destination, trial=trial))
    with results_path.open("a", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    store.set_cursor(cursor_key, start + len(selected))
    return {"cursor_key": cursor_key, "offset": start, "next_index": start + len(selected),
            "total_pairs": len(case_list), "batch_size": batch_size, "results_path": str(results_path),
            "metrics": summarize(records), "records": records}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a budget-capped Track A mock-agent evaluation batch")
    parser.add_argument("--suite", choices=("email", "slack", "banking", "cross", "all"), default="all")
    parser.add_argument("--mode", choices=("benign", "attack_undefended", "attack_defended", "benign_under_attack"), default="attack_defended")
    parser.add_argument("--attack", default="task_disguise", choices=[*(item.id for item in ATTACKS), "all"])
    parser.add_argument("--defense", choices=("ours", "none", "spotlighting"), default="ours")
    parser.add_argument("--confirm-policy", choices=("deny", "approve_delegated"), default="deny")
    parser.add_argument("--neutralize", choices=("off", "annotate", "redact"), default="redact")
    parser.add_argument("--output-filter", choices=("on", "off"), default="on")
    parser.add_argument("--model", default=None)
    parser.add_argument("--out", default="logs/evals")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--confirm-cost", action="store_true")
    parser.add_argument("--include-heldout", action="store_true")
    parser.add_argument("--also-run-undefended", action="store_true")
    parser.add_argument("--offset", type=int, default=None)
    parser.add_argument("--reset-cursor", action="store_true")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="list selected cases without making model calls")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 50:
        parser.error("--batch-size must be between 1 and 50")
    if args.batch_size > 5 and not (args.force and args.confirm_cost):
        parser.error("batches over 5 require both --force and --confirm-cost")
    if not 1 <= args.trials <= 3:
        parser.error("--trials must be between 1 and 3")
    if args.mode == "attack_undefended":
        args.defense = "none"
    if args.mode == "benign" and args.attack != "all" and args.attack:
        pass
    if args.dry_run:
        if args.mode == "benign":
            pairs = [(task.id, "", "") for task in tasks_for_suite(args.suite)]
        else:
            pairs = [(task.id, goal, pattern) for task, goal, pattern in attack_pairs(args.suite, args.attack, include_heldout=args.include_heldout)]
        print(json.dumps({"suite": args.suite, "mode": args.mode, "defense": args.defense,
                          "batch_size": args.batch_size, "selected": pairs[:args.batch_size]}, indent=2))
        return
    config = OpenRouterConfig.from_env()
    if args.model:
        config = replace(config, model=args.model)
    llm = OpenRouterClient(config=config, store=LogStore("logs/index.db"))
    result = run_batch(suite=args.suite, mode=args.mode, attack=args.attack, defense=args.defense,
                       batch_size=args.batch_size, out_dir=args.out, llm=llm,
                       neutralize=args.neutralize, output_filter=args.output_filter == "on",
                       include_heldout=args.include_heldout,
                       also_run_undefended=args.also_run_undefended, offset=args.offset,
                       reset_cursor=args.reset_cursor, confirm_policy=args.confirm_policy,
                       trials=args.trials)
    print(json.dumps({key: value for key, value in result.items() if key != "records"}, indent=2))


if __name__ == "__main__":
    main()
