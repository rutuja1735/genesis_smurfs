"""Plan-first AgentDojo pipeline powered exclusively by the configured LLM client."""

from __future__ import annotations

import json
from typing import Any, Sequence

from core.executor import Executor
from core.planner import Planner
from core.types import LLMClient
from .profile import AGENTDOJO_PROFILE
from .tool_specs import build_tool_specs


class SecureAgentPipeline:
    """AgentDojo-compatible pipeline element without importing provider adapters."""

    def __init__(self, llm: LLMClient, *, neutralize_mode: str = "redact", output_filter_enabled: bool = True,
                 audit: Any = None, attack_model_label: str = "gpt-4o-mini-2024-07-18") -> None:
        self.llm = llm
        self.name = attack_model_label  # Used only for AgentDojo attack prompt wording.
        self.neutralize_mode = neutralize_mode
        self.output_filter_enabled = output_filter_enabled
        self.audit = audit

    def query(self, query: str, runtime: Any, env: Any, messages: Sequence[dict] = (), extra_args: dict | None = None):
        registry = build_tool_specs(runtime.functions, runtime=runtime, env=env)
        plan = Planner(self.llm, registry, audit=self.audit).plan(query, AGENTDOJO_PROFILE)
        result = Executor(registry, self.llm, neutralize_mode=self.neutralize_mode,
                          output_filter_enabled=self.output_filter_enabled, audit=self.audit).run(query, plan, AGENTDOJO_PROFILE)
        from agentdojo.types import ChatMessage  # optional dependency, loaded only for an actual Track B run
        transcript: list[ChatMessage] = list(messages)
        transcript.append({"role": "user", "content": query})
        completed_calls = [
            {"id": node.id, "function": node.function_name.split(".", 1)[-1], "args": node.args}
            for node in result.plan.nodes if result.node_status.get(node.id) == "DONE"
        ]
        if completed_calls:
            transcript.append({"role": "assistant", "content": None, "tool_calls": completed_calls})
        transcript.append({"role": "assistant", "content": result.final.delivered_answer, "tool_calls": None})
        return result.final.delivered_answer, runtime, env, transcript, extra_args or {}
