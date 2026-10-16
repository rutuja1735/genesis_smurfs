from types import SimpleNamespace

from pydantic import BaseModel

from agentdojo_adapter.tool_specs import build_tool_specs


class Args(BaseModel):
    query: str
    value: str


def test_agentdojo_tools_default_to_fail_closed_and_add_sinks():
    functions = [
        SimpleNamespace(name="read_file", parameters=Args, description="read"),
        SimpleNamespace(name="unknown_action", parameters=Args, description="unknown"),
        SimpleNamespace(name="send_money", parameters=Args, description="transfer"),
    ]
    registry = build_tool_specs(functions)
    assert registry.require("agentdojo.read_file").risk == "read"
    assert registry.require("agentdojo.unknown_action").risk == "high_impact"
    assert registry.require("agentdojo.unknown_action").sink_params == {"query": "identifier", "value": "identifier"}
    assert registry.require("agentdojo.send_money").risk == "write"
