import pytest

from agents import create_mock_environment
from core.neutralizer import sanitize
from core.scanner import scan_output


@pytest.mark.parametrize("source", ["email", "slack", "banking"])
def test_default_tool_outputs_expose_and_neutralize_embedded_attacks(source):
    env = create_mock_environment()
    if source == "email":
        outputs = [env.email.read_email(email_id) for email_id in ("e18", "e19")]
        assert env.email.list_inbox(unread_only=True)["count"] == 7
        assert len(env.email.list_inbox()["emails"]) == 7
        assert "one-time login code" in env.email.read_email("e17")["body"]
    elif source == "slack":
        outputs = [env.slack.read_channel_messages(name)
                   for name in ("general", "project-atlas", "finance-help")]
        outputs += [env.slack.read_inbox("emma"),
                    env.slack.get_webpage("https://www.atlas-review.example")]
    else:
        outputs = [env.banking.read_file(name) for name in
                   ("bill.txt", "landlord-notices.txt", "account-verification.txt",
                    "reimbursement-release.txt")]
        outputs.append(env.banking.get_most_recent_transactions(2))

    before = env.snapshot()
    for output in outputs:
        matches = scan_output(output)
        assert any(result.severity == "high" for result in matches.values())
        view = sanitize(output, mode="redact")
        assert view.redacted_spans > 0
        assert view.value != output
    # Sanitization must leave the raw evidence in the agent state intact.
    assert env.snapshot() == before
