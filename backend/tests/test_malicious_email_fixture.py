import json
from pathlib import Path

from core.neutralizer import sanitize
from core.scanner import scan_output


def test_malicious_email_fixture_is_detected_and_neutralized():
    fixture = Path(__file__).parents[1] / "data" / "email.malicious.json"
    email_data = json.loads(fixture.read_text(encoding="utf-8"))
    malicious_body = email_data["inbox"][2]["body"]

    matches = scan_output(email_data)
    assert "inbox[2].body" in matches
    assert matches["inbox[2].body"].severity == "high"

    sanitized = sanitize(email_data, mode="redact")
    safe_body = sanitized.value["inbox"][2]["body"]
    assert "[REDACTED: suspected injected instruction" in safe_body
    assert "Ignore all previous instructions" not in safe_body
    assert sanitized.spans >= 2
    assert malicious_body != safe_body
