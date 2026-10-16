from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.llm import BudgetExceeded, LLMError, OpenRouterClient, OpenRouterConfig
from core.logstore import LogStore


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.requests = []

    def create(self, **kwargs):
        self.calls += 1
        self.requests.append(kwargs)
        return self.responses.pop(0)


class FakeOpenAI:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def response(content="hello", *, cost=0.001, prompt=10, completion=5, tools=None):
    message = SimpleNamespace(content=content, tool_calls=tools)
    usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, cost=cost)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage,
                           model="test/model", id="req-1")


def config(**overrides):
    values = dict(api_key="test-key", model="test/model", max_budget_usd=1,
                  price_in_per_m=1, price_out_per_m=1, cache=True, max_retries=0)
    values.update(overrides)
    return OpenRouterConfig(**values)


def test_identical_temperature_zero_call_is_cached_and_spend_recorded_once(tmp_path):
    fake = FakeOpenAI([response()])
    store = LogStore(tmp_path / "index.db")
    llm = OpenRouterClient(config(), store=store, client=fake)

    first = llm.complete("planner", "same prompt")
    second = llm.complete("planner", "same prompt")

    assert first == second == "hello"
    assert fake.chat.completions.calls == 1
    assert store.total_spend() == pytest.approx(0.001)


def test_budget_cap_blocks_next_call_after_spend_reaches_cap(tmp_path):
    fake = FakeOpenAI([response(cost=0.01)])
    store = LogStore(tmp_path / "index.db")
    llm = OpenRouterClient(config(max_budget_usd=0.01, cache=False), store=store, client=fake)

    llm.complete("planner", "first")
    with pytest.raises(BudgetExceeded):
        llm.complete("planner", "second")
    assert fake.chat.completions.calls == 1


def test_json_mode_repairs_fenced_or_surrounded_object(tmp_path):
    fake = FakeOpenAI([response('Here is the result: ```json\n{"ok": true}\n```')])
    llm = OpenRouterClient(config(cache=False), store=LogStore(tmp_path / "index.db"), client=fake)
    assert llm.complete("planner", "json please", json_mode=True) == '{"ok": true}'
    request = fake.chat.completions.requests[0]
    assert request["response_format"] == {"type": "json_object"}
    assert "require_parameters" not in request["extra_body"]


def test_failed_json_response_is_charged_before_repair_budget_check(tmp_path):
    fake = FakeOpenAI([response("not json", cost=0.01), response('{"ok": true}', cost=0.01)])
    store = LogStore(tmp_path / "index.db")
    llm = OpenRouterClient(config(max_budget_usd=0.01, cache=False), store=store, client=fake)
    with pytest.raises(BudgetExceeded):
        llm.complete("planner", "json please", json_mode=True)
    assert fake.chat.completions.calls == 1
    assert store.total_spend() == pytest.approx(0.01)


def test_only_openrouter_base_url_is_allowed():
    with pytest.raises(LLMError, match="OpenRouter"):
        OpenRouterClient(config(base_url="https://api.example.com"), store=LogStore("/tmp/not-used.db"), client=object())


def test_logstore_persists_eval_cursor(tmp_path):
    path = tmp_path / "index.db"
    LogStore(path).set_cursor("suite:mode", 10)
    assert LogStore(path).get_cursor("suite:mode") == 10
