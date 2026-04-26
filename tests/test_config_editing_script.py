"""Tests for script configuration editing tools."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers import llm

from custom_components.bedrock_ha_agent.config_tools.script import (
    ConfigScriptCreate,
    ConfigScriptDelete,
    ConfigScriptEdit,
    get_tools,
)

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture
def mock_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    return entry


@pytest.fixture
def llm_context():
    """Create a mock LLM context."""
    return llm.LLMContext(
        platform="bedrock_ha_agent",
        context=None,
        language="en",
        assistant="conversation",
        device_id=None,
    )


@pytest.mark.asyncio
async def test_script_create_golden_path(llm_context):
    """Test AC7 - script create golden path returns pending_approval, apply fires create + reload."""
    mock_hass = MagicMock()
    mock_hass.services = MagicMock()
    mock_hass.services.async_call = AsyncMock()

    tool = ConfigScriptCreate()

    # Mock ha_client functions
    with patch(
        "custom_components.bedrock_ha_agent.config_tools.script.ha_script.get_script",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "custom_components.bedrock_ha_agent.config_tools.script.ha_script.create_or_update_script",
        new_callable=AsyncMock,
    ) as mock_create, patch(
        "custom_components.bedrock_ha_agent.config_tools.script.ha_script.reload_scripts",
        new_callable=AsyncMock,
    ) as mock_reload:

        # Build payloads
        tool_input = llm.ToolInput(
            tool_name="ConfigScriptCreate",
            tool_args={
                "object_id": "test_script",
                "alias": "Test Script",
                "sequence": [{"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}],
            },
        )

        pre_state = await tool.build_pre_state(mock_hass, tool_input)
        assert pre_state is None  # Script doesn't exist yet

        proposed = await tool.build_proposed_payload(mock_hass, tool_input)
        assert proposed["object_id"] == "test_script"
        assert proposed["alias"] == "Test Script"
        assert "sequence" in proposed

        # Validate
        with patch(
            "custom_components.bedrock_ha_agent.config_tools.validation.validate_entities_exist",
            return_value=MagicMock(ok=True),
        ):
            result = await tool.validate(mock_hass, proposed, pre_state)
            assert result.ok

        # Build summary and diff
        summary = tool.build_proposed_summary(proposed, pre_state)
        assert "Would add" in summary
        assert "Test Script" in summary

        diff = tool.build_proposed_diff(proposed, pre_state)
        assert len(diff) > 0

        # Build restore function
        restore_fn = await tool.build_restore_fn(mock_hass, proposed, pre_state)
        assert callable(restore_fn)

        # Apply the change
        result = await tool.apply_change(mock_hass, proposed, pre_state)
        assert result["object_id"] == "test_script"
        assert result["entity_id"] == "script.test_script"

        # Verify create was called
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        assert call_args[0][1] == "test_script"  # object_id
        assert "alias" in call_args[0][2]  # config

        # Verify reload was called
        mock_reload.assert_called_once()


@pytest.mark.asyncio
async def test_script_edit_diff_shows_both_sides(llm_context):
    """Test that script edit diff shows both before and after states."""
    mock_hass = MagicMock()
    mock_hass.services = MagicMock()
    mock_hass.services.async_call = AsyncMock()

    tool = ConfigScriptEdit()

    existing_script = {
        "alias": "Old Alias",
        "sequence": [{"service": "light.turn_off"}],
    }

    with patch(
        "custom_components.bedrock_ha_agent.config_tools.script.ha_script.get_script",
        new_callable=AsyncMock,
        return_value=existing_script,
    ):
        tool_input = llm.ToolInput(
            tool_name="ConfigScriptEdit",
            tool_args={
                "object_id": "test_script",
                "alias": "New Alias",
            },
        )

        pre_state = await tool.build_pre_state(mock_hass, tool_input)
        assert pre_state["alias"] == "Old Alias"

        proposed = await tool.build_proposed_payload(mock_hass, tool_input)
        assert proposed["alias"] == "New Alias"

        diff = tool.build_proposed_diff(proposed, pre_state)
        assert "-alias: Old Alias" in diff or "- alias: Old Alias" in diff
        assert "+alias: New Alias" in diff or "+ alias: New Alias" in diff


@pytest.mark.asyncio
async def test_script_delete_unknown_object_id(llm_context):
    """Test that deleting unknown script returns validation_failed with unknown_script code."""
    mock_hass = MagicMock()
    mock_hass.services = MagicMock()
    mock_hass.services.async_call = AsyncMock()

    tool = ConfigScriptDelete()

    # v1.1.15: unknown_entry_error consults hass.states.get — simulate a real
    # HA in which the entity also doesn't exist in the state registry, so the
    # error stays `unknown_script` (not the "exists-but-not-in-our-file" code).
    mock_hass.states.get = MagicMock(return_value=None)
    with patch(
        "custom_components.bedrock_ha_agent.config_tools.script.ha_script.get_script",
        new_callable=AsyncMock,
        return_value=None,
    ):
        tool_input = llm.ToolInput(
            tool_name="ConfigScriptDelete",
            tool_args={"object_id": "nonexistent"},
        )

        pre_state = await tool.build_pre_state(mock_hass, tool_input)
        assert pre_state is None

        proposed = await tool.build_proposed_payload(mock_hass, tool_input)

        result = await tool.validate(mock_hass, proposed, pre_state)
        assert not result.ok
        assert len(result.errors) > 0
        assert result.errors[0].code == "unknown_script"


@pytest.mark.asyncio
async def test_script_sequence_with_unknown_entity_fails(llm_context):
    """Test that script with unknown entity in sequence fails validation."""
    mock_hass = MagicMock()
    mock_hass.services = MagicMock()
    mock_hass.services.async_call = AsyncMock()

    tool = ConfigScriptCreate()

    with patch(
        "custom_components.bedrock_ha_agent.config_tools.script.ha_script.get_script",
        new_callable=AsyncMock,
        return_value=None,
    ):
        tool_input = llm.ToolInput(
            tool_name="ConfigScriptCreate",
            tool_args={
                "object_id": "test_script",
                "alias": "Test Script",
                "sequence": [
                    {"service": "light.turn_on", "target": {"entity_id": "light.notreal"}}
                ],
            },
        )

        pre_state = await tool.build_pre_state(mock_hass, tool_input)
        proposed = await tool.build_proposed_payload(mock_hass, tool_input)

        # Mock both schema validation (pass) and entity validation (fail)
        with patch(
            "custom_components.bedrock_ha_agent.config_tools.script.validate_script",
            return_value=MagicMock(ok=True),
        ), patch(
            "custom_components.bedrock_ha_agent.config_tools.script.validate_entities_exist"
        ) as mock_validate:
            from custom_components.bedrock_ha_agent.config_tools.validation import (
                ValidationError,
                ValidationResult,
            )

            mock_validate.return_value = ValidationResult.failure(
                [
                    ValidationError(
                        code="unknown_entity",
                        message="Entity light.notreal does not exist",
                    )
                ]
            )

            result = await tool.validate(mock_hass, proposed, pre_state)
            assert not result.ok
            assert any(e.code == "unknown_entity" for e in result.errors)


def test_get_tools_returns_three_instances(mock_entry):
    """Test that get_tools returns exactly three tool instances."""
    mock_hass = MagicMock()
    mock_hass.services = MagicMock()
    mock_hass.services.async_call = AsyncMock()

    tools = get_tools(mock_hass, mock_entry)

    assert len(tools) == 3
    assert isinstance(tools[0], ConfigScriptCreate)
    assert isinstance(tools[1], ConfigScriptEdit)
    assert isinstance(tools[2], ConfigScriptDelete)

    # Verify tool names
    assert tools[0].name == "ConfigScriptCreate"
    assert tools[1].name == "ConfigScriptEdit"
    assert tools[2].name == "ConfigScriptDelete"
