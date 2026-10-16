"""Synchronous agent execution wrapper used by FastAPI background threads."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agents import create_mock_environment
from attacks import ATTACKS, GOALS, build_payload
from attacks.goals import ATT_IBAN
from baselines.react_agent import ReactAgent
from baselines.spotlighting import SpotlightingAgent
from core.audit import AuditLogger
from core.executor import Executor
from core.planner import Planner
from core.registry import ToolRegistry
from tasks import TASKS


def injections_for(attack: str | None, goal_id: str | None) -> dict[str, str]:
    if not attack or not goal_id:
        return {}
    goal = next((item for item in GOALS if item.id == goal_id), None)
    pattern = next((item for item in ATTACKS if item.id == attack), None)
    if goal is None or pattern is None or not goal.vector:
        raise ValueError("unknown attack pattern or injection goal")
    payload = "" if attack == "arg_poison" else build_payload(attack, goal.description)
    return {goal.vector: payload}


def execute_run(run: dict[str, Any], *, store: Any, event_bus: Any, llm_factory: Any,
                logs_dir: Path) -> dict[str, Any]:
    run_id = run["run_id"]
    audit = AuditLogger(logs_dir / "runs" / f"{run_id}.jsonl", run_id,
                        store=store, event_bus=event_bus)
    store.update_run(run_id, status="running")
    track = "real" if (run.get("email_agent") == "real" or run.get("track") == "real" or (os.environ.get("EMAIL_AGENT", "").lower() == "real" and not run.get("attack"))) else "mock"
    audit.write("RUN_START", command=run["command"], defense=run["defense"], attack=run.get("attack"),
                injection_goal=run.get("injection_goal"), track=track)
    try:
        injection_values = injections_for(run.get("attack"), run.get("injection_goal"))
        env = create_mock_environment(
            injections=injection_values if not run.get("session_state") else None,
            email_agent_type=run.get("email_agent"),
        )
        selected_agents = set(run.get("agents") or ["email", "slack", "banking"])
        unknown_agents = selected_agents - {"email", "slack", "banking"}
        if unknown_agents:
            raise ValueError(f"unknown agents: {', '.join(sorted(unknown_agents))}")
        env.registry = ToolRegistry([spec for spec in env.registry if spec.agent in selected_agents])
        saved = run.get("session_state") or {}
        if saved:
            env.profile = saved.get("profile", env.profile)
            for name, target in (("email", env.email), ("slack", env.slack), ("banking", env.banking)):
                if name in saved:
                    target.state = saved[name]
            _apply_injections(env, injection_values)
        if run.get("attack") == "arg_poison" and run.get("injection_goal") in {"inj_bank_1", "inj_cross_1"}:
            env.banking.state["files"]["bill.txt"] = env.banking.state["files"].get("bill.txt", "").replace(
                "DE75512108001245126199", ATT_IBAN)
        before = env.snapshot()
        llm = llm_factory(audit=audit, run_id=run_id, store=store)
        audit.write("MODEL_CONFIG", model=getattr(getattr(llm, "config", None), "model", "fake"))
        if run["defense"] in {"none", "spotlighting"}:
            agent = ReactAgent(llm) if run["defense"] == "none" else SpotlightingAgent(llm)
            output = agent.run(run["command"], env)
            answer = output["output"]
            result = {"answer": answer, "raw_answer": answer, "plan": None,
                      "executed_calls": output.get("calls", []), "decisions": []}
        else:
            plan = Planner(llm, env.registry, audit=audit).plan(run["command"], env.profile)
            executed = Executor(env.registry, llm, neutralize_mode=run.get("neutralize", "redact"),
                                output_filter_enabled=run.get("output_filter", True),
                                confirm_policy=run.get("confirm_policy", "deny"), audit=audit).run(
                                    run["command"], plan, env.profile)
            result = {"answer": executed.final.delivered_answer, "raw_answer": executed.final.raw_answer,
                      "plan": plan.model_dump(), "node_status": executed.node_status,
                      "executed_calls": list(executed.executed_calls),
                      "decisions": [asdict(decision) for decision in executed.decisions],
                      "neutralizer_events": list(executed.neutralizer_events)}
        after = env.snapshot()
        result["state_diff"] = _diff(before, after)
        result["before"] = before
        result["after"] = after
        result["attack_succeeded"] = False
        if run.get("injection_goal"):
            goal = next((item for item in GOALS if item.id == run["injection_goal"]), None)
            if goal:
                result["attack_succeeded"] = goal.security(before, after, result["answer"])
        matched_task = next((task for task in TASKS if task.prompt == run["command"]), None)
        result["utility"] = matched_task.utility(result["answer"], before, after) if matched_task else None
        result["summary"] = {"executed": len(result["executed_calls"]),
                              "blocked": sum(1 for row in store.list_decisions(run_id=run_id) if row.get("decision") == "BLOCK"),
                             "attack_succeeded": result["attack_succeeded"], "utility": result["utility"]}
        audit.write("RUN_RESULT", answer=result["answer"], attack_succeeded=result["attack_succeeded"],
                    state_diff=result["state_diff"], executed_calls=result["executed_calls"])
        audit.write("RUN_END", status="done", **result["summary"])
        result["run_id"] = run_id
        result["status"] = "done"
        store.update_run(run_id, status="done", summary=result["summary"])
        return result
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        audit.write("RUN_ERROR", reason=message, reason_human="The run could not complete; check backend configuration and logs.")
        audit.write("RUN_END", status="error")
        store.update_run(run_id, status="error", summary={"error": message})
        raise


def _apply_injections(env: Any, injections: dict[str, str]) -> None:
    if not injections:
        return
    def replace(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, str):
            for vector, payload in injections.items():
                value = value.replace(vector, payload)
            return value
        return value
    env.email.state = replace(env.email.state)
    env.slack.state = replace(env.slack.state)
    env.banking.state = replace(env.banking.state)
    if injections and next(iter(injections.values()), None) == "":
        env.banking.state["files"]["bill.txt"] = env.banking.state["files"].get("bill.txt", "").replace(
            "DE75512108001245126199", ATT_IBAN)


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    from agents import snapshot_diff
    return snapshot_diff(before, after)
