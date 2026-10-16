from eval.metrics import summarize


def test_summary_reports_detection_and_actual_redaction_separately():
    result = summarize([{
        "mode": "attack_defended",
        "security": False,
        "utility": True,
        "injection_expected": True,
        "injection_detected": True,
        "injections_detected": 2,
        "redacted_spans": 1,
    }])
    assert result["injections_detected"] == 2
    assert result["cases_with_injection_detected"] == 1
    assert result["injection_detection_rate"] == 1.0
    assert result["redacted_spans"] == 1
    assert result["asr"] == 0.0
