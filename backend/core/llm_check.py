"""Small explicit sanity check for OpenRouter JSON output and tool calling."""

from __future__ import annotations

import argparse
import json

from .llm import OpenRouterClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Check OpenRouter JSON and tool-call support")
    parser.add_argument("--no-tool-check", action="store_true", help="only verify JSON mode")
    args = parser.parse_args()
    client = OpenRouterClient()
    json_result = client.chat(
        [{"role": "user", "content": 'Return a JSON object with key "ok" and boolean value true.'}],
        role="llm_check", json_mode=True,
    )
    parsed = json.loads(json_result.text)
    if parsed.get("ok") is not True:
        raise SystemExit(f"JSON sanity check returned unexpected content: {parsed!r}")
    print(f"JSON output: OK ({json_result.model}, cost ${json_result.cost:.6f})")
    if not args.no_tool_check:
        tool_result = client.chat(
            [{"role": "user", "content": "Call the ping tool once with value ready."}],
            role="llm_check", tools=[{
                "type": "function",
                "function": {"name": "ping", "description": "A harmless capability check.",
                             "parameters": {"type": "object", "properties": {"value": {"type": "string"}},
                                            "required": ["value"], "additionalProperties": False}},
            }],
        )
        if not tool_result.tool_calls or tool_result.tool_calls[0]["function"]["name"] != "ping":
            raise SystemExit("Model did not return the expected ping tool call; choose a tool-capable model.")
        print(f"Tool calling: OK ({tool_result.model}, cost ${tool_result.cost:.6f})")
    print(f"Spend so far: ${client.store.total_spend():.6f} / ${client.config.max_budget_usd:.2f}")


if __name__ == "__main__":
    main()
