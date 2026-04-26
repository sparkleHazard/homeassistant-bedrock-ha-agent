"""strings.json + translations/en.json contain every key the integration uses.

HA's strings schema only allows the ``config``, ``options``, ``services``,
``entity``, ``device_automation``, ``selector``, etc. top-level keys (see
``hassfest`` checks). Custom top-level blocks like ``notifications`` and
``conversation_responses`` — which earlier drafts tried to use — fail the
hassfest validator and never reach the HA runtime, so we keep strings.json
focused on what HA actually serves.
"""
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


def test_strings_has_services_block():
    data = _load(STRINGS_PATH)
    assert "services" in data
    missing = REQUIRED_SERVICE_KEYS - set(data["services"].keys())
    assert not missing


def test_en_translations_mirrors_services():
    en = _load(EN_PATH)
    assert "services" in en, "translations/en.json missing top-level services block"


def test_en_translations_option_fields_mirror():
    en = _load(EN_PATH)
    en_fields = en["options"]["step"]["init"]["data"]
    missing = REQUIRED_OPTION_KEYS - set(en_fields.keys())
    assert not missing
