"""Convert AgentDojo Functions objects to fail-closed core ToolSpecs."""

from __future__ import annotations

from typing import Any

from core.registry import ToolRegistry, ToolSpec
from .risk_overrides import READ_TOOLS, WRITE_TOOLS
from .sinks import sink_map
from .trust import output_trust


def build_tool_specs(functions: list[Any] | dict[str, Any], *, runtime: Any = None, env: Any = None) -> ToolRegistry:
    entries = functions.values() if isinstance(functions, dict) else functions
    specs = []
    for function in entries:
        name = str(function.name)
        params = function.parameters
        if name in READ_TOOLS:
            risk = "read"
        elif name in WRITE_TOOLS:
            risk = "write"
        else:
            risk = "high_impact"

        def dispatch(_name=name, **kwargs):
            if runtime is None:
                raise RuntimeError("AgentDojo runtime is required to execute adapter tools")
            result, error = runtime.run_function(env, _name, kwargs, raise_on_error=True)
            if error:
                raise RuntimeError(error)
            return result

        specs.append(ToolSpec(
            name=f"agentdojo.{name}", agent="agentdojo", fn=dispatch,
            params_schema=params, risk=risk,
            output_trust=output_trust(name, params), sink_params=sink_map(params, risk == "high_impact"),
            description=str(getattr(function, "description", "")),
        ))
    return ToolRegistry(specs)
