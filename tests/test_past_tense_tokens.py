"""Tests for past-tense token consistency (AC D49)."""
from custom_components.bedrock_ha_agent.const import DIAGNOSTICS_LIFECYCLE_PAST_TENSE_TOKENS
from custom_components.bedrock_ha_agent.config_tools.pending import _PAST_TENSE_TOKENS
from custom_components.bedrock_ha_agent.conversation import _PAST_TENSE_REGEX


def test_pending_past_tense_set_includes_lifecycle_tokens():
    """_PAST_TENSE_TOKENS in pending.py includes all lifecycle tokens."""
    required_tokens = {"reloaded", "restarted", "disabled", "enabled"}

    assert required_tokens.issubset(_PAST_TENSE_TOKENS), (
        f"Missing lifecycle tokens in pending.py: {required_tokens - _PAST_TENSE_TOKENS}"
    )


def test_conversation_past_tense_regex_matches_lifecycle_tokens():
    """_PAST_TENSE_REGEX in conversation.py matches lifecycle tokens."""
    test_cases = [
        "I reloaded the integration",
        "I restarted the system",
        "it was disabled by the user",
        "the entity was enabled successfully",
    ]

    for text in test_cases:
        match = _PAST_TENSE_REGEX.search(text)
        assert match is not None, f"Expected regex to match: '{text}'"

        # Verify the matched token is one of the lifecycle tokens
        matched_token = match.group(1).lower()
        assert matched_token in {"reloaded", "restarted", "disabled", "enabled"}, (
            f"Matched unexpected token '{matched_token}' in '{text}'"
        )


def test_diagnostics_lifecycle_past_tense_tokens_defined():
    """DIAGNOSTICS_LIFECYCLE_PAST_TENSE_TOKENS constant contains expected tokens."""
    expected = {"reloaded", "restarted", "disabled", "enabled"}
    assert DIAGNOSTICS_LIFECYCLE_PAST_TENSE_TOKENS == expected, (
        f"DIAGNOSTICS_LIFECYCLE_PAST_TENSE_TOKENS mismatch: "
        f"expected={expected}, actual={DIAGNOSTICS_LIFECYCLE_PAST_TENSE_TOKENS}"
    )
