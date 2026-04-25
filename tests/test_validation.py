"""Tests for config_tools.validation module."""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

pytest_plugins = ["pytest_homeassistant_custom_component"]

from custom_components.bedrock_conversation.config_tools.validation import (
    ValidationError,
    ValidationResult,
    extract_entity_ids_from_automation,
    validate_automation,
    validate_entities_exist,
    validate_entity_exists,
    validate_helper,
    validate_lovelace_card,
    validate_scene,
    validate_script,
)


# ---------------------------------------------------------------------------
# Automation validation tests
# ---------------------------------------------------------------------------


def test_validate_automation_minimal_valid():
    """Minimal valid automation passes schema validation."""
    payload = {
        "alias": "Test Automation",
        "triggers": [{"platform": "time", "at": "12:00:00"}],
        "actions": [{"service": "light.turn_on"}],
    }
    result = validate_automation(payload)
    assert result.ok
    assert not result.errors


def test_validate_automation_missing_trigger_fails():
    """Automation without trigger fails schema validation."""
    payload = {
        "alias": "Test Automation",
        "actions": [{"service": "light.turn_on"}],
    }
    result = validate_automation(payload)
    assert not result.ok
    assert len(result.errors) == 1
    assert result.errors[0].code == "schema_invalid"
    assert "trigger" in result.errors[0].message.lower()


def test_validate_automation_bad_trigger_fails():
    """Automation with invalid trigger structure fails."""
    payload = {
        "alias": "Test Automation",
        "triggers": "not a list",  # triggers must be a list
        "actions": [{"service": "light.turn_on"}],
    }
    result = validate_automation(payload)
    assert not result.ok
    assert len(result.errors) == 1
    assert result.errors[0].code == "schema_invalid"


# ---------------------------------------------------------------------------
# Script validation tests
# ---------------------------------------------------------------------------


def test_validate_script_minimal_valid():
    """Minimal valid script passes schema validation."""
    payload = {
        "sequence": [{"service": "light.turn_on"}],
    }
    result = validate_script(payload)
    assert result.ok
    assert not result.errors


def test_validate_script_with_alias():
    """Script with alias and sequence passes."""
    payload = {
        "alias": "Turn on lights",
        "sequence": [
            {"service": "light.turn_on", "target": {"entity_id": "light.living_room"}}
        ],
    }
    result = validate_script(payload)
    assert result.ok


# ---------------------------------------------------------------------------
# Scene validation tests
# ---------------------------------------------------------------------------


def test_validate_scene_valid():
    """Valid scene with name and entities passes."""
    payload = {
        "name": "Evening",
        "entities": {
            "light.porch": "on",
            "light.living_room": {"state": "on", "brightness": 128},
        },
    }
    result = validate_scene(payload)
    assert result.ok
    assert not result.errors


def test_validate_scene_missing_entities_fails():
    """Scene without entities dict fails validation."""
    payload = {
        "name": "Evening",
    }
    result = validate_scene(payload)
    assert not result.ok
    assert len(result.errors) == 1
    assert result.errors[0].code == "missing_field"
    assert result.errors[0].path == "entities"


def test_validate_scene_missing_name_fails():
    """Scene without name fails validation."""
    payload = {
        "entities": {"light.porch": "on"},
    }
    result = validate_scene(payload)
    assert not result.ok
    assert len(result.errors) == 1
    assert result.errors[0].code == "missing_field"
    assert result.errors[0].path == "name"


def test_validate_scene_not_dict_fails():
    """Scene that is not a dict fails."""
    payload = "not a dict"
    result = validate_scene(payload)
    assert not result.ok
    assert result.errors[0].code == "schema_invalid"


# ---------------------------------------------------------------------------
# Helper validation tests
# ---------------------------------------------------------------------------


def test_validate_helper_unsupported_type():
    """Unsupported helper type fails validation."""
    result = validate_helper("input_unknown", {"name": "Test"})
    assert not result.ok
    assert len(result.errors) == 1
    assert result.errors[0].code == "unsupported_helper_type"
    assert result.errors[0].path == "helper_type"


def test_validate_helper_input_number_requires_min_max():
    """input_number requires min and max fields."""
    payload = {"name": "Volume"}
    result = validate_helper("input_number", payload)
    assert not result.ok
    assert len(result.errors) == 1
    assert result.errors[0].code == "missing_field"
    assert "min" in result.errors[0].message or "max" in result.errors[0].message


def test_validate_helper_input_number_valid():
    """Valid input_number passes."""
    payload = {"name": "Volume", "min": 0, "max": 100}
    result = validate_helper("input_number", payload)
    assert result.ok


def test_validate_helper_input_select_requires_options():
    """input_select requires non-empty options list."""
    payload = {"name": "Mode"}
    result = validate_helper("input_select", payload)
    assert not result.ok
    assert len(result.errors) == 1
    assert result.errors[0].code == "missing_field"
    assert result.errors[0].path == "options"


def test_validate_helper_input_select_empty_options_fails():
    """input_select with empty options list fails."""
    payload = {"name": "Mode", "options": []}
    result = validate_helper("input_select", payload)
    assert not result.ok
    assert result.errors[0].code == "missing_field"
    assert result.errors[0].path == "options"


def test_validate_helper_input_select_valid():
    """Valid input_select passes."""
    payload = {"name": "Mode", "options": ["Home", "Away", "Sleep"]}
    result = validate_helper("input_select", payload)
    assert result.ok


def test_validate_helper_input_boolean_minimal():
    """Minimal input_boolean with just name passes."""
    payload = {"name": "Guest Mode"}
    result = validate_helper("input_boolean", payload)
    assert result.ok


def test_validate_helper_missing_name():
    """Helper without name fails."""
    payload = {}
    result = validate_helper("input_boolean", payload)
    assert not result.ok
    assert result.errors[0].code == "missing_field"
    assert result.errors[0].path == "name"


def test_validate_helper_empty_name():
    """Helper with empty/whitespace name fails."""
    payload = {"name": "   "}
    result = validate_helper("input_boolean", payload)
    assert not result.ok
    assert result.errors[0].code == "missing_field"


# ---------------------------------------------------------------------------
# Lovelace card validation tests
# ---------------------------------------------------------------------------


def test_validate_lovelace_card_valid():
    """Valid Lovelace card with type passes."""
    card = {"type": "entities", "entities": ["light.porch"]}
    result = validate_lovelace_card(card)
    assert result.ok
    assert not result.errors


def test_validate_lovelace_card_missing_type():
    """Lovelace card without type fails."""
    card = {"entities": ["light.porch"]}
    result = validate_lovelace_card(card)
    assert not result.ok
    assert len(result.errors) == 1
    assert result.errors[0].code == "missing_field"
    assert result.errors[0].path == "type"


def test_validate_lovelace_card_empty_type():
    """Lovelace card with empty type fails."""
    card = {"type": ""}
    result = validate_lovelace_card(card)
    assert not result.ok
    assert result.errors[0].code == "missing_field"


def test_validate_lovelace_card_not_dict():
    """Lovelace card that is not a dict fails."""
    card = "not a dict"
    result = validate_lovelace_card(card)
    assert not result.ok
    assert result.errors[0].code == "schema_invalid"


# ---------------------------------------------------------------------------
# ValidationResult tests
# ---------------------------------------------------------------------------


def test_validation_result_to_tool_result_dict():
    """ValidationResult serializes to correct tool_result shape."""
    errors = [
        ValidationError(code="schema_invalid", message="Bad format"),
        ValidationError(code="missing_field", message="Missing 'name'", path="name"),
    ]
    result = ValidationResult.failure(errors)

    tool_dict = result.to_tool_result_dict()

    assert tool_dict["status"] == "validation_failed"
    assert len(tool_dict["errors"]) == 2
    assert tool_dict["errors"][0]["code"] == "schema_invalid"
    assert tool_dict["errors"][0]["message"] == "Bad format"
    assert "path" not in tool_dict["errors"][0]
    assert tool_dict["errors"][1]["code"] == "missing_field"
    assert tool_dict["errors"][1]["path"] == "name"


def test_validation_result_success():
    """ValidationResult.success() creates ok result with no errors."""
    result = ValidationResult.success()
    assert result.ok
    assert not result.errors


# ---------------------------------------------------------------------------
# Entity extraction tests
# ---------------------------------------------------------------------------


def test_extract_entity_ids_from_automation():
    """Extract entity_ids from automation triggers and actions."""
    payload = {
        "alias": "Test",
        "trigger": [
            {"platform": "state", "entity_id": "binary_sensor.motion"},
            {"platform": "state", "entity_id": ["light.porch", "light.garage"]},
        ],
        "condition": [
            {"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}
        ],
        "action": [
            {
                "service": "light.turn_on",
                "target": {"entity_id": "light.living_room"},
            },
            {
                "service": "notify.mobile_app",
                "data": {"message": "Motion detected"},
            },
        ],
    }

    entity_ids = extract_entity_ids_from_automation(payload)

    # Should extract all entity_ids, sorted
    expected = [
        "binary_sensor.motion",
        "light.garage",
        "light.living_room",
        "light.porch",
        "sun.sun",
    ]
    assert entity_ids == expected


def test_extract_entity_ids_filters_non_entities():
    """extract_entity_ids filters out non-entity strings."""
    payload = {
        "trigger": [
            {"platform": "device", "device_id": "abc123-device-uuid"},
        ],
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.porch"}},
        ],
    }

    entity_ids = extract_entity_ids_from_automation(payload)

    # device_id should be filtered out
    assert entity_ids == ["light.porch"]


def test_extract_entity_ids_empty_payload():
    """extract_entity_ids returns empty list for payload with no entities."""
    payload = {
        "trigger": [{"platform": "time", "at": "12:00:00"}],
        "action": [{"delay": {"seconds": 5}}],
    }

    entity_ids = extract_entity_ids_from_automation(payload)

    assert entity_ids == []


# ---------------------------------------------------------------------------
# Entity existence validation tests (require hass fixture)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_entity_exists_via_registry(hass: HomeAssistant):
    """Entity in registry passes validation."""
    registry = er.async_get(hass)
    registry.async_get_or_create(
        domain="light",
        platform="test",
        unique_id="test_light_1",
        suggested_object_id="living_room",
    )

    result = validate_entity_exists(hass, "light.living_room")

    assert result.ok
    assert not result.errors


@pytest.mark.asyncio
async def test_validate_entity_exists_via_states(hass: HomeAssistant):
    """Entity only in states (not registry) passes validation."""
    hass.states.async_set("light.porch", "on")

    result = validate_entity_exists(hass, "light.porch")

    assert result.ok
    assert not result.errors


@pytest.mark.asyncio
async def test_validate_entity_exists_missing(hass: HomeAssistant):
    """Missing entity fails validation."""
    result = validate_entity_exists(hass, "light.nonexistent")

    assert not result.ok
    assert len(result.errors) == 1
    assert result.errors[0].code == "unknown_entity"
    assert "light.nonexistent" in result.errors[0].message


@pytest.mark.asyncio
async def test_validate_entity_exists_malformed_id(hass: HomeAssistant):
    """Malformed entity_id fails validation."""
    result = validate_entity_exists(hass, "not_an_entity")

    assert not result.ok
    assert result.errors[0].code == "invalid_entity_id"


@pytest.mark.asyncio
async def test_validate_entities_exist_multiple(hass: HomeAssistant):
    """Bulk validation returns all failures."""
    registry = er.async_get(hass)
    registry.async_get_or_create(
        domain="light",
        platform="test",
        unique_id="test_light_1",
        suggested_object_id="living_room",
    )
    hass.states.async_set("light.porch", "on")

    result = validate_entities_exist(
        hass,
        [
            "light.living_room",  # exists in registry
            "light.porch",  # exists in states
            "light.missing1",  # does not exist
            "light.missing2",  # does not exist
        ],
    )

    assert not result.ok
    assert len(result.errors) == 2
    assert all(e.code == "unknown_entity" for e in result.errors)
    error_messages = [e.message for e in result.errors]
    assert any("missing1" in msg for msg in error_messages)
    assert any("missing2" in msg for msg in error_messages)


@pytest.mark.asyncio
async def test_validate_entities_exist_all_valid(hass: HomeAssistant):
    """Bulk validation passes when all entities exist."""
    registry = er.async_get(hass)
    registry.async_get_or_create(
        domain="light",
        platform="test",
        unique_id="test_light_1",
        suggested_object_id="living_room",
    )
    hass.states.async_set("light.porch", "on")

    result = validate_entities_exist(hass, ["light.living_room", "light.porch"])

    assert result.ok
    assert not result.errors
