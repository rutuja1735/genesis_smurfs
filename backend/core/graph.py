"""Plan graph schema, DAG construction, and deterministic validation."""

from __future__ import annotations

from typing import Any, Literal

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .registry import ToolRegistry


class PlanNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    function_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    arg_sources: dict[str, str] = Field(default_factory=dict)
    risk: Literal["read", "write", "high_impact"] | None = None
    justification: str | None = None

    @field_validator("id", "function_name")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class PlanGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[PlanNode]


class ValidationResult(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)


def build_dag(plan: PlanGraph) -> nx.DiGraph:
    graph = nx.DiGraph()
    for node in plan.nodes:
        graph.add_node(node.id, function_call=node, depends_on=list(node.depends_on), arg_sources=dict(node.arg_sources), risk=node.risk, justification=node.justification)
    for node in plan.nodes:
        for parent in node.depends_on:
            graph.add_edge(parent, node.id)
    return graph


def _unknown_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.strip().startswith("<unknown>")


def _schema_args_for_validation(schema: type[BaseModel], args: dict[str, Any]) -> dict[str, Any]:
    values = dict(args)
    for name, value in list(values.items()):
        if not _unknown_placeholder(value):
            continue
        field = schema.model_fields.get(name)
        annotation = field.annotation if field is not None else str
        if annotation is int:
            values[name] = 0
        elif annotation is float:
            values[name] = 0.0
        elif annotation is bool:
            values[name] = False
        elif annotation is list or getattr(annotation, "__origin__", None) is list:
            values[name] = []
        elif annotation is dict or getattr(annotation, "__origin__", None) is dict:
            values[name] = {}
        else:
            values[name] = "placeholder"
    return values


def _normalized(value: Any) -> str:
    return " ".join(str(value).strip().lower().split())


def validate_plan(plan: PlanGraph, registry: ToolRegistry, user_command: str, trusted_profile: dict[str, Any] | None = None) -> ValidationResult:
    errors: list[str] = []
    by_id: dict[str, PlanNode] = {}
    for node in plan.nodes:
        if node.id in by_id:
            errors.append(f"duplicate node id: {node.id}")
        by_id[node.id] = node
    graph = nx.DiGraph()
    graph.add_nodes_from(by_id)
    for node in plan.nodes:
        for dep in node.depends_on:
            if dep not in by_id:
                errors.append(f"node {node.id}: unknown dependency {dep}")
            else:
                graph.add_edge(dep, node.id)
    if not nx.is_directed_acyclic_graph(graph):
        errors.append("plan contains a dependency cycle")
    for node in plan.nodes:
        if node.function_name not in registry:
            errors.append(f"node {node.id}: unknown tool {node.function_name}")
            continue
        spec = registry.require(node.function_name)
        if node.risk is None:
            errors.append(f"node {node.id}: risk label is missing")
        elif node.risk != spec.risk:
            errors.append(f"node {node.id}: risk label {node.risk!r} does not match registry risk {spec.risk!r}")
        try:
            spec.params_schema.model_validate(_schema_args_for_validation(spec.params_schema, node.args))
        except Exception as exc:
            errors.append(f"node {node.id}: invalid args for {node.function_name}: {exc}")
        for arg in node.args:
            source = node.arg_sources.get(arg)
            if source not in {"user", "profile"} and not (isinstance(source, str) and source.startswith("from_node:")):
                errors.append(f"node {node.id}: arg {arg!r} must declare source user, profile, or from_node:<id>")
        if (spec.risk in {"write", "high_impact"} or node.risk in {"write", "high_impact"}) and not (node.justification or "").strip():
            errors.append(f"node {node.id}: write/high-impact node is missing justification")
        if spec.risk in {"write", "high_impact"}:
            trusted_values = [_normalized(v) for v in (trusted_profile or {}).values() if isinstance(v, (str, int, float))]
            for arg_name, value in node.args.items():
                if arg_name not in spec.sink_params or _unknown_placeholder(value):
                    continue
                candidate = _normalized(value)
                if not candidate or (candidate not in _normalized(user_command) and not any(candidate in item for item in trusted_values)):
                    if not node.arg_sources.get(arg_name, "").startswith("from_node:"):
                        errors.append(f"node {node.id}: literal sink argument {arg_name!r} is not in the user command/profile and has no from_node source")
        for arg, source in node.arg_sources.items():
            if source.startswith("from_node:"):
                source_id = source.split(":", 1)[1]
                if source_id not in by_id:
                    errors.append(f"node {node.id}: arg {arg!r} references unknown source node {source_id}")
                elif source_id not in nx.ancestors(graph, node.id):
                    errors.append(f"node {node.id}: arg {arg!r} source {source_id} is not an ancestor")
    if not any(word in user_command.lower().split() for word in ("send", "pay", "transfer", "wire", "settle", "delete", "remove", "trash", "forward", "post", "invite", "schedule")):
        for node in plan.nodes:
            spec = registry.get(node.function_name)
            if spec and spec.risk == "high_impact":
                errors.append(f"node {node.id}: high-impact action has no matching action verb in the user command")
    return ValidationResult(ok=not errors, errors=errors)
