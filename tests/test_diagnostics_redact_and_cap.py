"""Tests for diagnostics base helpers (redaction, byte cap)."""
import json

from custom_components.bedrock_ha_agent.diagnostics.base import (
    redact_secrets,
    enforce_byte_cap,
)


def test_redact_secrets_masks_known_keys():
    """redact_secrets masks api_key, password, access_token, auth_token."""
    input_dict = {
        "api_key": "secret123",
        "ok": "visible",
        "nested": {
            "password": "hunter2",
            "data": "safe",
        },
        "list_of_dicts": [
            {"access_token": "token456", "value": 42},
            {"auth_token": "token789"},
        ],
    }

    result = redact_secrets(input_dict)

    assert result["api_key"] == "***REDACTED***"
    assert result["ok"] == "visible"
    assert result["nested"]["password"] == "***REDACTED***"
    assert result["nested"]["data"] == "safe"
    assert result["list_of_dicts"][0]["access_token"] == "***REDACTED***"
    assert result["list_of_dicts"][0]["value"] == 42
    assert result["list_of_dicts"][1]["auth_token"] == "***REDACTED***"


def test_redact_secrets_preserves_non_mapping_leaves():
    """Redact handles lists, tuples, ints, strings correctly."""
    assert redact_secrets(42) == 42
    assert redact_secrets("plain") == "plain"
    assert redact_secrets([1, 2, 3]) == [1, 2, 3]
    assert redact_secrets(None) is None

    # Nested list of dicts
    nested = [{"api_key": "x", "data": "y"}, {"value": 10}]
    result = redact_secrets(nested)
    assert result[0]["api_key"] == "***REDACTED***"
    assert result[0]["data"] == "y"
    assert result[1]["value"] == 10


def test_enforce_byte_cap_truncates_long_list():
    """enforce_byte_cap truncates large payloads to stay under cap."""
    # Build a dict with a 10000-item list
    big_list = [{"id": i, "data": f"item_{i}"} for i in range(10000)]
    payload = {"items": big_list, "status": "ok"}

    cap = 1024  # 1 KB
    result, truncated = enforce_byte_cap(payload, cap)

    assert truncated is True, "Expected truncated flag to be True"
    result_bytes = len(json.dumps(result, default=str).encode("utf-8"))
    assert result_bytes <= cap, f"Result size {result_bytes} exceeds cap {cap}"
    assert len(result["items"]) < len(big_list), "Expected items list to be truncated"


def test_enforce_byte_cap_under_limit_returns_unchanged():
    """enforce_byte_cap returns unchanged payload when under limit."""
    small_payload = {"status": "ok", "data": [1, 2, 3]}
    cap = 1024

    result, truncated = enforce_byte_cap(small_payload, cap)

    assert truncated is False, "Expected no truncation"
    assert result == small_payload, "Expected payload unchanged"
