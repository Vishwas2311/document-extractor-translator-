from app.core.logging import _redact_sensitive


def test_redact_sensitive_scrubs_known_secret_keys() -> None:
    event_dict = {
        "event": "test_event",
        "api_key": "secret-abc",
        "Authorization": "Bearer secret-token",
        "safe_field": "visible-value",
    }

    result = _redact_sensitive(object(), "info", event_dict)

    assert result["api_key"] == "***redacted***"
    assert result["Authorization"] == "***redacted***"
    assert result["safe_field"] == "visible-value"
    assert result["event"] == "test_event"


def test_redact_sensitive_leaves_unrelated_keys_untouched() -> None:
    event_dict = {"document_id": "doc-1", "status_code": 403}

    result = _redact_sensitive(object(), "info", event_dict)

    assert result == {"document_id": "doc-1", "status_code": 403}
