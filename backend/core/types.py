"""Shared data types and the deterministic FakeLLM used by offline tests."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class FunctionCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    function_name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    ok: bool = True
    value: Any = None
    error: str | None = None


@dataclass(frozen=True)
class PromptRecord:
    role: str
    prompt: str
    json_mode: bool


class LLMClient(Protocol):
    def complete(self, role: str, prompt: str, *, json_mode: bool = False) -> str: ...


class FakeLLM:
    """Role-scripted, zero-cost LLM substitute that records every prompt."""

    def __init__(self, responses: dict[str, list[str] | tuple[str, ...]] | None = None, *, defaults: dict[str, str] | None = None) -> None:
        self._responses: dict[str, deque[str]] = defaultdict(deque)
        for role, values in (responses or {}).items():
            self._responses[role].extend(values)
        self.defaults = defaults or {
            "pre_plan": '{"explicit_requirements":[],"implicit_requirements":[],"output_requirements":[],"known_information":[],"missing_information":[]}',
            "planner": '{"tool_calls":[]}',
            "resolver": '{"resolved_args":{}}',
            "expander": '{"new_tool_calls":[]}',
            "reflection": '{"args":{}}',
            "injection_classifier": '{"detections":[]}',
            "final_answer": "I could not find any relevant information.",
        }
        self.prompts: list[PromptRecord] = []

    def enqueue(self, role: str, *responses: str) -> None:
        self._responses[role].extend(responses)

    def complete(self, role: str, prompt: str, *, json_mode: bool = False) -> str:
        self.prompts.append(PromptRecord(role, prompt, json_mode))
        if self._responses[role]:
            return self._responses[role].popleft()
        if role in self.defaults:
            return self.defaults[role]
        raise KeyError(f"FakeLLM has no response queued for role {role!r}")

    def remaining(self, role: str) -> int:
        return len(self._responses[role])


class PrePlan(BaseModel):
    explicit_requirements: list[str] = Field(default_factory=list)
    implicit_requirements: list[str] = Field(default_factory=list)
    output_requirements: list[str] = Field(default_factory=list)
    known_information: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class ResolvedValue(BaseModel):
    value: Any
    source_node: str


class ResolverResponse(BaseModel):
    resolved_args: dict[str, ResolvedValue] = Field(default_factory=dict)


class ExpansionResponse(BaseModel):
    new_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
