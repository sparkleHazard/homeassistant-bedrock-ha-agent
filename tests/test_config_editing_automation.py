"""Tests for automation config-editing tools."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from homeassistant.helpers import llm

pytest_plugins = ["pytest_homeassistant_custom_component"]

from custom_components.bedrock_conversation.config_tools.automation import (
    ConfigAutomationCreate,
    ConfigAutomationEdit,
    ConfigAutomationDelete,
    get_tools,
)
from custom_components.bedrock_conversation.runtime_data import BedrockRuntimeData
from custom_components.bedrock_conversation.const import DOMAIN


@pytest.fixture
async def mock_entry(hass):
    """Create a mock config entry with runtime_data."""
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={"enable_config_editing": True},
        entry_id="test_entry_id",
        state=ConfigEntryState.LOADED,
    )
    entry.runtime_data = BedrockRuntimeData()
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def llm_context(mock_entry):
    """Create a mock LLM context."""
    context = MagicMock(spec=llm.LLMContext)
    context.device_id = None
    return context


@pytest.fixture
def mock_ha_automation():
    """Mock all ha_client.automation functions."""
    with patch("custom_components.bedrock_conversation.config_tools.automation.ha_automation") as mock:
        mock.create_or_update_automation = AsyncMock()
        mock.delete_automation = AsyncMock()
        mock.reload_automations = AsyncMock()
        mock.get_automation = AsyncMock(return_value=None)
        mock.list_automations = AsyncMock(return_value=[])
        yield mock


@pytest.mark.asyncio
async def test_automation_create_golden_path(hass, mock_entry, llm_context, mock_ha_automation):
    """AC1: Create automation golden path — pending approval, no writes until apply."""
    # Register the entities used in the automation
    hass.states.async_set("light.bedroom", "off")
    hass.states.async_set("light.kitchen", "off")

    tool = ConfigAutomationCreate()

    tool_input = llm.ToolInput(
        tool_name="ConfigAutomationCreate",
        tool_args={
            "config": {
                "alias": "Test Automation",
                "trigger": [{"platform": "state", "entity_id": "light.bedroom"}],
                "action": [{"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}],
            }
        },
    )

    # Call the tool
    result = await tool.async_call(hass, tool_input, llm_context)

    # Should return pending_approval
    assert result["status"] == "pending_approval"
    assert "proposed_summary" in result
    assert result["proposed_summary"].startswith("Would add")
    assert "Test Automation" in result["proposed_summary"]
    assert "proposal_id" in result

    # Should NOT have called create yet
    mock_ha_automation.create_or_update_automation.assert_not_called()
    mock_ha_automation.reload_automations.assert_not_called()

    # Should have stored a PendingChange
    pending = mock_entry.runtime_data.pending.get("_global")
    assert pending is not None
    assert pending.tool_name == "ConfigAutomationCreate"

    # Now simulate approval by calling apply_fn
    apply_result = await pending.apply_fn(hass, pending.proposed_payload, pending.pre_state)

    # NOW create should be called
    assert mock_ha_automation.create_or_update_automation.call_count == 1
    assert mock_ha_automation.reload_automations.call_count == 1

    call_args = mock_ha_automation.create_or_update_automation.call_args
    object_id = call_args[0][1]
    config = call_args[0][2]

    assert object_id == "test_automation"
    assert config["alias"] == "Test Automation"
    assert "_object_id" not in config  # Internal marker should be stripped


@pytest.mark.asyncio
async def test_automation_create_validation_failure(hass, mock_entry, llm_context, mock_ha_automation):
    """AC2: Pre-validation failure — unknown entity referenced."""
    tool = ConfigAutomationCreate()

    tool_input = llm.ToolInput(
        tool_name="ConfigAutomationCreate",
        tool_args={
            "config": {
                "alias": "Bad Automation",
                "trigger": [{"platform": "state", "entity_id": "light.notreal"}],
                "action": [{"service": "light.turn_on", "target": {"entity_id": "light.also_fake"}}],
            }
        },
    )

    result = await tool.async_call(hass, tool_input, llm_context)

    # Should return validation_failed
    assert result["status"] == "validation_failed"
    assert "errors" in result
    assert len(result["errors"]) > 0
    assert result["errors"][0]["code"] == "unknown_entity"

    # Should NOT have called create
    mock_ha_automation.create_or_update_automation.assert_not_called()


@pytest.mark.asyncio
async def test_automation_create_restore_on_failure(hass, mock_entry, llm_context, mock_ha_automation):
    """AC3-lite: Post-apply failure → restore called."""
    # Register the entity used in the automation
    hass.states.async_set("light.bedroom", "off")

    tool = ConfigAutomationCreate()

    tool_input = llm.ToolInput(
        tool_name="ConfigAutomationCreate",
        tool_args={
            "config": {
                "alias": "Will Fail",
                "trigger": [{"platform": "state", "entity_id": "light.bedroom"}],
                "action": [{"service": "light.turn_on"}],
            }
        },
    )

    # Make create_or_update_automation raise
    mock_ha_automation.create_or_update_automation.side_effect = RuntimeError("Write failed")

    result = await tool.async_call(hass, tool_input, llm_context)
    pending = mock_entry.runtime_data.pending.get("_global")

    # Try to apply — should raise
    with pytest.raises(RuntimeError, match="Write failed"):
        await pending.apply_fn(hass, pending.proposed_payload, pending.pre_state)

    # Now call restore_fn
    await pending.restore_fn()

    # Restore should have called delete (to undo the create)
    assert mock_ha_automation.delete_automation.call_count == 1


@pytest.mark.asyncio
async def test_automation_edit_happy_path(hass, mock_entry, llm_context, mock_ha_automation):
    """ConfigAutomationEdit happy path with diff."""
    # Register the entity used in the automation
    hass.states.async_set("light.bedroom", "off")

    # Mock get_automation to return existing automation
    mock_ha_automation.get_automation.return_value = {
        "id": "existing_auto",
        "alias": "Old Alias",
        "trigger": [{"platform": "state", "entity_id": "light.bedroom"}],
        "action": [{"service": "light.turn_on"}],
    }

    tool = ConfigAutomationEdit()
    tool_input = llm.ToolInput(
        tool_name="ConfigAutomationEdit",
        tool_args={
            "object_id": "existing_auto",
            "config": {
                "alias": "New Alias",
                "trigger": [{"platform": "state", "entity_id": "light.bedroom"}],
                "action": [{"service": "light.turn_off"}],
            }
        },
    )

    result = await tool.async_call(hass, tool_input, llm_context)

    assert result["status"] == "pending_approval"
    assert "Would update" in result["proposed_summary"]

    # Diff should show both old and new
    diff = result["proposed_diff"]
    assert "-alias: Old Alias" in diff or "Old Alias" in diff
    assert "+alias: New Alias" in diff or "New Alias" in diff


@pytest.mark.asyncio
async def test_automation_delete_happy_path(hass, mock_entry, llm_context, mock_ha_automation):
    """ConfigAutomationDelete happy path."""
    mock_ha_automation.get_automation.return_value = {
        "id": "to_delete",
        "alias": "Doomed",
        "trigger": [{"platform": "state", "entity_id": "light.bedroom"}],
        "action": [{"service": "light.turn_on"}],
    }

    tool = ConfigAutomationDelete()
    tool_input = llm.ToolInput(
        tool_name="ConfigAutomationDelete",
        tool_args={"object_id": "to_delete"},
    )

    result = await tool.async_call(hass, tool_input, llm_context)

    assert result["status"] == "pending_approval"
    assert "Would delete" in result["proposed_summary"]

    # Apply
    pending = mock_entry.runtime_data.pending.get("_global")
    apply_result = await pending.apply_fn(hass, pending.proposed_payload, pending.pre_state)

    # Should have called delete
    mock_ha_automation.delete_automation.assert_called_once_with(hass, "to_delete")
    mock_ha_automation.reload_automations.assert_called_once()


@pytest.mark.asyncio
async def test_automation_delete_unknown_object_id(hass, mock_entry, llm_context, mock_ha_automation):
    """ConfigAutomationDelete with unknown object_id fails validation."""
    mock_ha_automation.get_automation.return_value = None

    tool = ConfigAutomationDelete()
    tool_input = llm.ToolInput(
        tool_name="ConfigAutomationDelete",
        tool_args={"object_id": "nonexistent"},
    )

    result = await tool.async_call(hass, tool_input, llm_context)

    assert result["status"] == "validation_failed"
    assert "errors" in result
    assert result["errors"][0]["code"] == "unknown_automation"


@pytest.mark.asyncio
async def test_get_tools_returns_three(hass, mock_entry):
    """get_tools returns three tool instances."""
    tools = get_tools(hass, mock_entry)

    assert len(tools) == 3
    names = {tool.name for tool in tools}
    assert names == {
        "ConfigAutomationCreate",
        "ConfigAutomationEdit",
        "ConfigAutomationDelete",
    }
