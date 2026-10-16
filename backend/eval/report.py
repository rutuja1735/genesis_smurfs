"""Write compact Markdown tables from saved evaluation JSONL records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .metrics import summarize


def read_results(path: str | Path) -> list[dict[str, Any]]:
    file = Path(path)
    if not file.exists():
        return []
    return [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]


def markdown_report(records: list[dict[str, Any]]) -> str:
    metrics = summarize(records)
    lines = ["# Agentgaurd Track A Evaluation", "", "## Summary", "",
             "| Cases | Utility | Utility under attack | ASR | Tool ASR | Output ASR | Blocked | Cost (USD) |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    lines.append("| {cases} | {utility} | {utility_under_attack} | {asr} | {asr_tool_action} | {asr_output_channel} | {blocked} | ${cost_usd:.6f} |".format(**{
        **metrics,
        "utility": _pct(metrics.get("utility")),
        "utility_under_attack": _pct(metrics.get("utility_under_attack")),
        "asr": _pct(metrics.get("asr")),
        "asr_tool_action": _pct(metrics.get("asr_tool_action")),
        "asr_output_channel": _pct(metrics.get("asr_output_channel")),
    }))
    lines.extend(["", "## ASR by suite and attack", "", "| Group | Attack | ASR |", "|---|---|---:|"])
    for group, mapping in (("Suite", metrics.get("asr_by_suite", {})), ("Attack", metrics.get("asr_by_attack", {}))):
        lines.extend(f"| {group} | {name} | {_pct(rate)} |" for name, rate in mapping.items())
    lines.extend(["", "## Failures", ""])
    failures = metrics.get("failures", [])
    if failures:
        lines.extend(f"- `{row.get('case_id')}`: {row.get('goal')} ({row.get('attack')})" for row in failures)
    else:
        lines.append("No attacker goals succeeded in the selected records.")
    lines.extend(["", "## Notes", "", "Metrics describe only the cases present in these JSONL files. They are not a full-suite or cross-model claim unless the full evaluation was run."])
    return "\n".join(lines) + "\n"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="logs/results.jsonl")
    parser.add_argument("--output", default="logs/report.md")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown_report(read_results(args.input)), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
