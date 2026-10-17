import copy

import pytest

from core.final_answer import FinalAnswer
from core.gate import Decision, DecisionAction
from core.output_filter import OutputFilterContext
from core.types import FakeLLM


def test_partial_summary_receives_plain_reason_without_internal_errors():
    data = {"inbox": {"count": 7}, "read": {
        "blocked": True, "error": "BLOCKED_BY_POLICY: R4: untrusted provenance"}}
    original = copy.deepcopy(data)
    decision = Decision(DecisionAction.BLOCK, "R4", "untrusted provenance",
                        "Blocked `email.read_email`: untrusted email_id.")
    llm = FakeLLM({"final_answer": ["There are 7 unread messages. I couldn't read one message because I couldn't verify its reference."]})
    result = FinalAnswer(llm).generate(
        "Summarize my inbox", data,
        OutputFilterContext(executed_calls=["email.list_inbox"], raw_tool_outputs=[data]),
        [decision], [])
    prompt = llm.prompts[-1].prompt
    assert "could not verify a required detail" in prompt
    assert "email.read_email" not in prompt and "email.list_inbox" not in prompt
    assert "R4" not in prompt and "BLOCKED_BY_POLICY" not in prompt
    assert "A completed read or summary does not require a completed write action" in prompt
    assert result.delivered_answer.startswith("There are 7 unread messages.")
    assert data == original  # Internal evidence is retained for the audit.
    assert result.security_notes == (decision.reason_human,)


@pytest.mark.parametrize("action,rule,status,reason", [
    (DecisionAction.BLOCK, "R3", "stopped", "You did not ask me to take this action"),
    (DecisionAction.NEEDS_CONFIRM, "R4b", "awaiting confirmation", "needs independent verification"),
    (DecisionAction.SKIP, "R2", "could not continue", "An earlier step did not finish"),
    (DecisionAction.BLOCK, "R8", "stopped", "contained suspicious instructions"),
])
def test_response_model_receives_reason_and_actual_outcome(action, rule, status, reason):
    llm = FakeLLM()
    FinalAnswer(llm).generate("Review my emails", {}, OutputFilterContext(),
                              [Decision(action, rule, "internal detail", "Internal reason")], [])
    prompt = llm.prompts[-1].prompt
    assert status in prompt and reason in prompt
    assert '"' + rule + '"' not in prompt


def test_friendly_response_still_cannot_claim_an_unexecuted_payment():
    llm = FakeLLM({"final_answer": ["I sent the payment successfully."]})
    result = FinalAnswer(llm).generate("Review my emails", {}, OutputFilterContext(), [], [])
    assert any(decision.rule_id == "F5" for decision in result.filter_decisions)
    assert "not completed" in result.delivered_answer
