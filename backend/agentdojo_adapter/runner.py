"""Optional subprocess entry point for AgentDojo Track B."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path

from core.audit import AuditLogger
from core.llm import OpenRouterClient
from core.logstore import LogStore
from .pairs import pair_batch
from .pipeline import SecureAgentPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a small AgentDojo Track B batch via OpenRouter")
    parser.add_argument("--suite", default="banking")
    parser.add_argument("--attack", default="important_instructions")
    parser.add_argument("--defense", choices=("ours", "none"), default="ours")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--eval-id", default=None)
    args = parser.parse_args()
    try:
        from agentdojo.task_suite.load_suites import get_suite
        from agentdojo.attacks.attack_registry import load_attack
    except ImportError as exc:
        raise SystemExit("AgentDojo is optional. Install the external benchmark package in the separate backend/.venv-agentdojo environment.") from exc
    if args.batch_size > 5:
        raise SystemExit("Track B batches are capped at 5 pairs")
    suite = get_suite("v1.1.2", args.suite)
    if args.defense != "ours":
        raise SystemExit("The Track B CLI currently runs the defended plan-first pipeline only; use the Track A evaluator for undefended comparisons.")
    store = LogStore("logs/index.db")
    pipeline = SecureAgentPipeline(OpenRouterClient(store=store),
        attack_model_label=os.getenv("AGENTDOJO_ATTACK_MODEL_LABEL", "gpt-4o-mini-2024-07-18"))
    attack = load_attack(args.attack, suite, pipeline)
    tasks = list(suite.user_tasks.values())
    injections = list(suite.injection_tasks.values())
    selected = pair_batch(tasks, injections, offset=args.offset, batch_size=args.batch_size)
    eval_id = args.eval_id or uuid.uuid4().hex[:12]
    out_dir = Path("logs") / "agentdojo" / eval_id
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for user_task, injection_task in selected:
        case_id = f"{user_task.ID}__{injection_task.ID}__{args.attack}__{args.defense}"
        run_id = uuid.uuid4().hex[:12]
        audit = AuditLogger(out_dir / f"{run_id}.jsonl", run_id, case_id, store=store)
        pipeline.audit = audit
        attack_texts = attack.attack(user_task, injection_task)
        store.create_run(run_id, user_task.PROMPT, defense=args.defense, attack=args.attack,
                         injection_goal=injection_task.ID, model=pipeline.llm.config.model,
                         status="running", track="agentdojo", jsonl_path=str(audit.path),
                         eval_id=eval_id, case_id=case_id)
        audit.write("RUN_START", command=user_task.PROMPT, defense=args.defense, attack=args.attack,
                    injection_goal=injection_task.ID, track="agentdojo", suite=args.suite,
                    model=pipeline.llm.config.model, attack_model_label=pipeline.name)
        usage_before = store.usage_totals()
        utility, security = suite.run_task_with_pipeline_msg(
            pipeline, user_task, injection_task, attack_texts, verbose=False)
        usage_after = store.usage_totals()
        row = {"case_id": case_id, "run_id": run_id, "suite": args.suite,
               "user_task": user_task.ID, "injection_task": injection_task.ID,
               "attack": args.attack, "defense": args.defense,
               "utility": bool(utility), "security": bool(security),
               "tokens_in": usage_after["tokens_in"] - usage_before["tokens_in"],
               "tokens_out": usage_after["tokens_out"] - usage_before["tokens_out"],
               "cost_usd": usage_after["cost_usd"] - usage_before["cost_usd"]}
        audit.write("AGENTDOJO_CASE_RESULT", **row)
        audit.write("RUN_END", status="done", utility=row["utility"], attack_succeeded=row["security"])
        store.update_run(run_id, status="done", summary={"utility": row["utility"],
                         "attack_succeeded": row["security"], "cost_usd": row["cost_usd"]})
        with (out_dir / "results.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        results.append(row)
    print(json.dumps({"eval_id": eval_id, "suite": args.suite, "attack": args.attack,
                      "offset": args.offset, "cases": len(results),
                      "utility": sum(r["utility"] for r in results) / len(results) if results else None,
                      "asr": sum(r["security"] for r in results) / len(results) if results else None,
                      "results_path": str(out_dir / "results.jsonl")}, indent=2))


if __name__ == "__main__":
    main()
