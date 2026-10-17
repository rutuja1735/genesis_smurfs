import json

import pytest

from core.graph import PlanNode
from core.resolver import Resolver, ResolverError
from core.types import FakeLLM


def node():
    return PlanNode(id="read", function_name="email.read_email",
                    args={"email_id": "<unknown>: string"}, depends_on=["inbox"])


def response(source="inbox"):
    return json.dumps({"resolved_args": {"email_id": {"value": "e1", "source_node": source}}})


def test_incomplete_resolution_is_retried_with_same_dependencies():
    llm = FakeLLM({"resolver": ['{"resolved_args":{}}', response()]})
    result = Resolver(llm).fill(node(), {"inbox": {"emails": [{"id": "e1"}]}})
    assert result.args == {"email_id": "e1"}
    assert result.arg_sources == {"email_id": "inbox"}
    assert len(llm.prompts) == 2


def test_retry_stops_after_two_invalid_responses():
    llm = FakeLLM({"resolver": ['{"resolved_args":{}}'] * 3})
    with pytest.raises(ResolverError, match="two attempts"):
        Resolver(llm).fill(node(), {"inbox": {"emails": [{"id": "e1"}]}})
    assert len(llm.prompts) == 2


def test_retry_never_accepts_undeclared_source():
    llm = FakeLLM({"resolver": [response("other")] * 2})
    with pytest.raises(ResolverError, match="two attempts"):
        Resolver(llm).fill(node(), {"inbox": {"emails": [{"id": "e1"}]}})
