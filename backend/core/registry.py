"""Tool metadata registry. Registration is explicit and deterministic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Type

from pydantic import BaseModel

Risk = Literal["read", "write", "high_impact"]
Trust = Literal["trusted", "untrusted"]
SinkKind = Literal["recipient", "address", "url", "amount", "body", "identifier"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    agent: str
    fn: Callable[..., Any] | None
    params_schema: Type[BaseModel]
    risk: Risk
    output_trust: dict[str, Trust] = field(default_factory=dict)
    sink_params: dict[str, SinkKind] = field(default_factory=dict)
    description: str = ""
    intent_verbs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or "." not in self.name:
            raise ValueError("tool name must be namespaced, for example 'email.search'")
        if self.agent != self.name.split(".", 1)[0]:
            raise ValueError("agent must match the tool name namespace")


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec] | None = None) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"tool already registered: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def require(self, name: str) -> ToolSpec:
        spec = self.get(name)
        if spec is None:
            raise KeyError(f"unknown tool: {name}")
        return spec

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def __iter__(self):
        return iter(self._specs.values())

    def names(self) -> set[str]:
        return set(self._specs)
