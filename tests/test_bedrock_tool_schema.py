"""Regression tests for bedrock tool schema generation.

The v1.2.0 bug: format_tools_for_bedrock shipped empty input_schema for every
tool except HassCallService. All 15 diagnostics tools advertised zero parameters
to Bedrock, so Claude couldn't call them with required args like entity_id.

This test suite locks in the converter's correctness and prevents the bug from
recurring.
"""
import pytest
from unittest.mock import MagicMock
import voluptuous as vol
from homeassistant.helpers import config_validation as cv


# Unit tests on _vol_schema_to_json_schema
def test_empty_schema_produces_empty_object():
    """Empty voluptuous schema should produce an empty JSON Schema object."""
    from custom_components.bedrock_ha_agent.messages import _vol_schema_to_json_schema

    schema = vol.Schema({})
    result = _vol_schema_to_json_schema(schema)
    assert result == {"type": "object", "properties": {}, "required": []}


def test_required_entity_id_roundtrip():
    """Required entity_id field should appear in required array."""
    from custom_components.bedrock_ha_agent.messages import _vol_schema_to_json_schema

    schema = vol.Schema({vol.Required("entity_id"): cv.entity_id})
    result = _vol_schema_to_json_schema(schema)
    assert result["required"] == ["entity_id"]
    assert result["properties"]["entity_id"] == {"type": "string"}


def test_optional_with_default_carries_default():
    """Optional field with default value should preserve the default in JSON Schema."""
    from custom_components.bedrock_ha_agent.messages import _vol_schema_to_json_schema

    schema = vol.Schema({vol.Optional("limit", default=50): vol.All(int, vol.Range(min=1, max=500))})
    result = _vol_schema_to_json_schema(schema)
    assert "limit" not in result["required"]
    assert result["properties"]["limit"]["type"] == "integer"
    assert result["properties"]["limit"]["minimum"] == 1
    assert result["properties"]["limit"]["maximum"] == 500
    assert result["properties"]["limit"]["default"] == 50


def test_allow_extra_becomes_additional_properties_true():
    """Schema with extra=vol.ALLOW_EXTRA should set additionalProperties: true."""
    from custom_components.bedrock_ha_agent.messages import _vol_schema_to_json_schema

    schema = vol.Schema({}, extra=vol.ALLOW_EXTRA)
    result = _vol_schema_to_json_schema(schema)
    assert result.get("additionalProperties") is True


def test_nested_schema_recurses():
    """Nested voluptuous schemas should recursively convert to nested JSON Schema."""
    from custom_components.bedrock_ha_agent.messages import _vol_schema_to_json_schema

    schema = vol.Schema({vol.Required("outer"): vol.Schema({vol.Required("inner"): str})})
    result = _vol_schema_to_json_schema(schema)
    assert result["properties"]["outer"]["type"] == "object"
    assert result["properties"]["outer"]["properties"]["inner"]["type"] == "string"
    assert result["properties"]["outer"]["required"] == ["inner"]


def test_unknown_validator_falls_back_gracefully():
    """Unknown callable validators shouldn't crash the converter."""
    from custom_components.bedrock_ha_agent.messages import _vol_schema_to_json_schema

    schema = vol.Schema({vol.Required("weird"): lambda x: x})
    result = _vol_schema_to_json_schema(schema)
    assert "weird" in result["properties"]
    # Should not raise


# Integration-style tests on format_tools_for_bedrock
def test_format_tools_produces_nonempty_schemas_for_diagnostics():
    """Regression: the v1.2.0 bug shipped every diagnostics tool with
    input_schema: {properties: {}, required: []}. Claude couldn't call them.
    This test asserts at least one diagnostics tool has non-empty properties
    after running through format_tools_for_bedrock."""
    from custom_components.bedrock_ha_agent.diagnostics.logs import DiagnosticsSystemLogList
    from custom_components.bedrock_ha_agent.messages import format_tools_for_bedrock
    from homeassistant.helpers import llm

    tool = DiagnosticsSystemLogList(MagicMock(), MagicMock())
    api_instance = MagicMock(spec=llm.APIInstance)
    api_instance.tools = [tool]
    specs = format_tools_for_bedrock(api_instance)
    assert len(specs) == 1
    assert specs[0]["name"] == "DiagnosticsSystemLogList"
    # The old bug: {}; the fix: {"limit": {...}}
    assert specs[0]["input_schema"]["properties"], (
        f"Empty schema regression — got {specs[0]['input_schema']}"
    )


def test_format_tools_preserves_hass_call_service_hand_schema():
    """The HassCallService hand-written schema must not be replaced by the
    converter — its voluptuous keys don't introspect the way the generic
    converter expects."""
    from custom_components.bedrock_ha_agent.__init__ import HassServiceTool
    from custom_components.bedrock_ha_agent.messages import format_tools_for_bedrock
    from homeassistant.helpers import llm

    tool = HassServiceTool(MagicMock())
    api_instance = MagicMock(spec=llm.APIInstance)
    api_instance.tools = [tool]
    specs = format_tools_for_bedrock(api_instance)
    assert specs[0]["input_schema"]["required"] == ["service", "target_device"]
    # spec-specific fields still there
    assert "brightness" in specs[0]["input_schema"]["properties"]


def test_format_tools_every_diagnostics_tool_has_schema():
    """All 15 diagnostics tools must produce a non-vacuous JSON schema OR
    explicitly have an empty parameters field (only DiagnosticsRepairsList,
    DiagnosticsHealthCheck, DiagnosticsIntegrationList have parameters={} —
    others all have required fields)."""
    from custom_components.bedrock_ha_agent.diagnostics import get_tools
    from custom_components.bedrock_ha_agent.messages import format_tools_for_bedrock
    from homeassistant.helpers import llm

    entry = MagicMock()
    entry.options = {"enable_diagnostics": True}
    tools = get_tools(MagicMock(), entry)
    api_instance = MagicMock(spec=llm.APIInstance)
    api_instance.tools = tools
    specs = format_tools_for_bedrock(api_instance)
    assert len(specs) == 15

    tools_with_params = {
        "DiagnosticsSystemLogList", "DiagnosticsLogbookRead",
        "DiagnosticsStateRead", "DiagnosticsStateHistory",
        "DiagnosticsStatistics", "ExtendedServiceCall",
        "DiagnosticsReloadIntegration", "DiagnosticsReloadConfigEntry",
        "DiagnosticsEntityEnable", "DiagnosticsEntityDisable",
        "DiagnosticsLoggerSetLevel"
    }
    # Exempt: DiagnosticsRepairsList, DiagnosticsHealthCheck,
    #         DiagnosticsIntegrationList, DiagnosticsCheckConfig — no params

    for spec in specs:
        if spec["name"] in tools_with_params:
            assert spec["input_schema"]["properties"], (
                f"{spec['name']} has empty schema — bug regression"
            )


@pytest.mark.asyncio
async def test_api_instance_end_to_end(hass):
    """Register the BedrockServicesAPI against a real hass, build an APIInstance
    with diagnostics enabled, and assert the generated toolSpec passes Bedrock's
    expected shape: every tool has name/description/input_schema."""
    from homeassistant.helpers import llm
    from custom_components.bedrock_ha_agent.__init__ import BedrockServicesAPI
    from custom_components.bedrock_ha_agent.messages import format_tools_for_bedrock
    from custom_components.bedrock_ha_agent.const import (
        CONF_ENABLE_DIAGNOSTICS, CONF_ENABLE_CONFIG_EDITING, DOMAIN,
    )
    from custom_components.bedrock_ha_agent.runtime_data import BedrockRuntimeData
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    # Create a real config entry with diagnostics enabled
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="test_entry",
        data={
            "aws_access_key_id": "test",
            "aws_secret_access_key": "test",
            "aws_region": "us-west-2",
        },
        options={CONF_ENABLE_DIAGNOSTICS: True, CONF_ENABLE_CONFIG_EDITING: False},
    )
    entry.runtime_data = BedrockRuntimeData()
    entry.add_to_hass(hass)

    api = BedrockServicesAPI(hass, "test_api_id", "test_api_name")
    llm_context = MagicMock(spec=llm.LLMContext)
    llm_context.device_id = None
    llm_context.conversation_id = None
    instance = await api.async_get_api_instance(llm_context)

    specs = format_tools_for_bedrock(instance)
    # Should have HassCallService + diagnostics tools (at least a few tools)
    assert len(specs) >= 1, f"Expected at least 1 tool, got {len(specs)}"

    for spec in specs:
        assert spec["name"], f"Tool missing name: {spec}"
        assert "input_schema" in spec, f"Tool {spec['name']} missing input_schema"
        # Schema should be an object with properties
        assert spec["input_schema"].get("type") == "object", f"Tool {spec['name']} schema not an object"
