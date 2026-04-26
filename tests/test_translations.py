"""AC15: strings.json + translations/en.json contain every key the integration uses."""
import json
from pathlib import Path



STRINGS_PATH = Path("custom_components/bedrock_ha_agent/strings.json")
EN_PATH = Path("custom_components/bedrock_ha_agent/translations/en.json")


REQUIRED_OPTION_KEYS = {
    "enable_config_editing",
    "config_undo_depth",
    "config_undo_ttl_seconds",
    "config_approval_ttl_seconds",
}
REQUIRED_NOTIFICATION_KEYS = {"haiku_config_advisory"}
REQUIRED_CONVERSATION_RESPONSE_KEYS = {
    "approval_applied", "approval_rejected", "approval_expired",
    "undo_success", "undo_nothing_to_undo",
    "undo_nothing_to_undo_for_conversation", "undo_ambiguous",
    "apply_failed_restored", "validation_failed",
}
REQUIRED_SERVICE_KEYS = {"undo_last_config_change"}


def _load(path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_strings_has_new_option_fields():
    data = _load(STRINGS_PATH)
    fields = data["options"]["step"]["init"]["data"]
    missing = REQUIRED_OPTION_KEYS - set(fields.keys())
    assert not missing, f"strings.json missing option keys: {missing}"


def test_strings_has_option_data_descriptions():
    data = _load(STRINGS_PATH)
    descriptions = data["options"]["step"]["init"].get("data_description", {})
    missing = REQUIRED_OPTION_KEYS - set(descriptions.keys())
    assert not missing, f"strings.json missing option data_description entries: {missing}"


def test_strings_has_notifications_block():
    data = _load(STRINGS_PATH)
    assert "notifications" in data
    missing = REQUIRED_NOTIFICATION_KEYS - set(data["notifications"].keys())
    assert not missing


def test_strings_has_conversation_responses_block():
    data = _load(STRINGS_PATH)
    assert "conversation_responses" in data
    missing = REQUIRED_CONVERSATION_RESPONSE_KEYS - set(data["conversation_responses"].keys())
    assert not missing


def test_strings_has_services_block():
    data = _load(STRINGS_PATH)
    assert "services" in data
    missing = REQUIRED_SERVICE_KEYS - set(data["services"].keys())
    assert not missing


def test_en_translations_mirror_strings():
    strings = _load(STRINGS_PATH)
    en = _load(EN_PATH)
    # For every new block we added, the en.json mirror should have the same top-level keys.
    for block in ("notifications", "conversation_responses", "services"):
        assert block in en, f"translations/en.json missing top-level block: {block}"


def test_en_translations_option_fields_mirror():
    strings = _load(STRINGS_PATH)
    en = _load(EN_PATH)
    en_fields = en["options"]["step"]["init"]["data"]
    missing = REQUIRED_OPTION_KEYS - set(en_fields.keys())
    assert not missing
