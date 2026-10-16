"""Conservative, zero-network estimate for a planned Track A batch."""

from __future__ import annotations

import argparse
import os


def estimate(batch_size: int, *, trials: int = 1, compare_baseline: bool = False) -> dict[str, float | int]:
    calls_per_case = 6  # planner pre-plan + graph, up to three tool steps, final answer
    if compare_baseline:
        calls_per_case += 5
    calls = batch_size * trials * calls_per_case
    tokens_in = calls * 1800
    tokens_out = calls * 350
    input_price = float(os.getenv("PRICE_IN_PER_M", "0.15"))
    output_price = float(os.getenv("PRICE_OUT_PER_M", "0.60"))
    cost = tokens_in * input_price / 1_000_000 + tokens_out * output_price / 1_000_000
    return {"batch_size": batch_size, "trials": trials, "calls_estimate": calls,
            "tokens_in_estimate": tokens_in, "tokens_out_estimate": tokens_out,
            "estimated_cost_usd": round(cost, 6)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate OpenRouter usage without making requests")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--also-run-undefended", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1 or args.trials < 1:
        parser.error("batch size and trials must be positive")
    import json
    print(json.dumps(estimate(args.batch_size, trials=args.trials,
                              compare_baseline=args.also_run_undefended), indent=2))


if __name__ == "__main__":
    main()
