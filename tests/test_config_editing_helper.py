"""Tests for helper entity config-editing tools."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.bedrock_ha_agent.config_tools.helper import (
    ConfigHelperCreate,
    ConfigHelperDelete,
    ConfigHelperEdit,
    get_tools,
)
from custom_components.bedrock_ha_agent.runtime_data import BedrockRuntimeData
from custom_components.bedrock_ha_agent.const import DOMAIN
from homeassistant.helpers import llm

pytest_plugins = ["pytest_homeassistant_custom_component"]


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
def mock_helper_client():
    """Mock the ha_client.helper module."""
    with patch(
        "custom_components.bedrock_ha_agent.config_tools.helper.ha_helper"
    ) as mock:
        mock.list_helpers = AsyncMock(return_value=[])
        mock.get_helper = AsyncMock(return_value=None)
        mock.create_helper = AsyncMock(return_value="test_helper")
        mock.update_helper = AsyncMock()
        mock.delete_helper = AsyncMock()
        mock.reload_helper_domain = AsyncMock()
        yield mock


async def test_input_boolean_create_golden_path(hass, mock_entry, llm_context, mock_helper_client):
    """Test creating an input_boolean via ConfigHelperCreate (AC7)."""
    tool = ConfigHelperCreate()
    tool_input = llm.ToolInput(
        tool_name="ConfigHelperCreate",
        tool_args={
            "domain": "input_boolean",
            "config": {"name": "Test Boolean", "icon": "mdi:toggle-switch"},
        },
    )

    # Call should return pending_approval
    result = await tool.async_call(hass, tool_input, llm_context)
    assert result["status"] == "pending_approval"
    assert "input_boolean" in result["proposed_summary"].lower()
    assert "Test Boolean" in result["proposed_summary"]

    # Extract the pending change and apply it
    pending = mock_entry.runtime_data.pending.get("_global")
    assert pending is not None

    # Apply the change
    apply_result = await pending.apply_fn(hass, pending.proposed_payload, pending.pre_state)
    assert apply_result["status"] == "applied"
    assert apply_result["domain"] == "input_boolean"
    assert apply_result["object_id"] == "test_helper"

    # Verify create_helper and reload were called
    mock_helper_client.create_helper.assert_called_once()
    call_args = mock_helper_client.create_helper.call_args
    assert call_args[0][1] == "input_boolean"  # domain
    assert call_args[0][2]["name"] == "Test Boolean"  # config

    mock_helper_client.reload_helper_domain.assert_called_once_with(hass, "input_boolean")

    # Verify restore function (undo) would call delete
    await pending.restore_fn()
    mock_helper_client.delete_helper.assert_called_once_with(hass, "input_boolean", "test_helper")


async def test_input_number_missing_min_max_rejected(hass, mock_entry, llm_context, mock_helper_client):
    """Test input_number without min/max is rejected with validation_failed."""
    tool = ConfigHelperCreate()
    tool_input = llm.ToolInput(
        tool_name="ConfigHelperCreate",
        tool_args={
            "domain": "input_number",
            "config": {"name": "Test Number"},  # Missing min/max
        },
    )

    result = await tool.async_call(hass, tool_input, llm_context)
    assert result["status"] == "validation_failed"
    assert any(e["code"] == "missing_field" for e in result["errors"])
    assert any("min" in e["message"] or "max" in e["message"] for e in result["errors"])


async def test_input_select_missing_options_rejected(hass, mock_entry, llm_context, mock_helper_client):
    """Test input_select without options is rejected."""
    tool = ConfigHelperCreate()
    tool_input = llm.ToolInput(
        tool_name="ConfigHelperCreate",
        tool_args={
            "domain": "input_select",
            "config": {"name": "Test Select"},  # Missing options
        },
    )

    result = await tool.async_call(hass, tool_input, llm_context)
    assert result["status"] == "validation_failed"
    assert any(e["code"] == "missing_field" for e in result["errors"])
    assert any("options" in e["message"].lower() for e in result["errors"])


async def test_timer_create_golden_path(hass, mock_entry, llm_context, mock_helper_client):
    """Test creating a timer."""
    tool = ConfigHelperCreate()
    tool_input = llm.ToolInput(
        tool_name="ConfigHelperCreate",
        tool_args={
            "domain": "timer",
            "config": {"name": "Cooking Timer", "duration": "00:10:00"},
        },
    )

    result = await tool.async_call(hass, tool_input, llm_context)
    assert result["status"] == "pending_approval"
    assert "timer" in result["proposed_summary"].lower()


async def test_counter_create_golden_path(hass, mock_entry, llm_context, mock_helper_client):
    """Test creating a counter."""
    tool = ConfigHelperCreate()
    tool_input = llm.ToolInput(
        tool_name="ConfigHelperCreate",
        tool_args={
            "domain": "counter",
            "config": {"name": "Visit Counter", "initial": 0, "step": 1},
        },
    )

    result = await tool.async_call(hass, tool_input, llm_context)
    assert result["status"] == "pending_approval"
    assert "counter" in result["proposed_summary"].lower()


async def test_input_button_create_golden_path(hass, mock_entry, llm_context, mock_helper_client):
    """Test creating an input_button (D11 coverage)."""
    tool = ConfigHelperCreate()
    tool_input = llm.ToolInput(
        tool_name="ConfigHelperCreate",
        tool_args={
            "domain": "input_button",
            "config": {"name": "Reset Button", "icon": "mdi:restart"},
        },
    )

    result = await tool.async_call(hass, tool_input, llm_context)
    assert result["status"] == "pending_approval"
    assert "input_button" in result["proposed_summary"].lower()


async def test_helper_unsupported_domain_rejected_by_schema(hass, mock_entry, llm_context, mock_helper_client):
    """Test that unsupported domain is rejected at the parameter schema level."""
    tool = ConfigHelperCreate()
    tool_input = llm.ToolInput(
        tool_name="ConfigHelperCreate",
        tool_args={
            "domain": "light",  # Not a helper domain
            "config": {"name": "Test Light"},
        },
    )

    # The voluptuous schema should raise vol.Invalid which gets caught by the base class
    result = await tool.async_call(hass, tool_input, llm_context)
    assert result["status"] == "validation_failed"


async def test_helper_edit_diff_shows_name_change(hass, mock_entry, llm_context, mock_helper_client):
    """Test editing a helper shows a diff of the name change."""
    # Mock get_helper to return existing config
    mock_helper_client.get_helper.return_value = {
        "name": "Old Name",
        "min": 0,
        "max": 100,
    }

    tool = ConfigHelperEdit()
    tool_input = llm.ToolInput(
        tool_name="ConfigHelperEdit",
        tool_args={
            "domain": "input_number",
            "object_id": "test_number",
            "config": {"name": "New Name", "min": 0, "max": 100},
        },
    )

    result = await tool.async_call(hass, tool_input, llm_context)
    assert result["status"] == "pending_approval"
    assert "update" in result["proposed_summary"].lower()
    # Diff should show the name change
    assert "Old Name" in result["proposed_diff"] or "New Name" in result["proposed_diff"]


async def test_helper_delete_unknown_object_id_rejected(hass, mock_entry, llm_context, mock_helper_client):
    """Test deleting a non-existent helper is rejected."""
    # Mock get_helper to return None (not found)
    mock_helper_client.get_helper.return_value = None

    tool = ConfigHelperDelete()
    tool_input = llm.ToolInput(
        tool_name="ConfigHelperDelete",
        tool_args={
            "domain": "input_boolean",
            "object_id": "nonexistent",
        },
    )

    result = await tool.async_call(hass, tool_input, llm_context)
    assert result["status"] == "validation_failed"
    assert any(e["code"] == "unknown_helper" for e in result["errors"])


async def test_helper_delete_has_id_regeneration_warning(hass, mock_entry, llm_context, mock_helper_client):
    """Test deleting a helper includes the id-regeneration warning."""
    # Mock get_helper to return existing config
    mock_helper_client.get_helper.return_value = {"name": "Test Boolean"}

    tool = ConfigHelperDelete()
    tool_input = llm.ToolInput(
        tool_name="ConfigHelperDelete",
        tool_args={
            "domain": "input_boolean",
            "object_id": "test_bool",
        },
    )

    result = await tool.async_call(hass, tool_input, llm_context)
    assert result["status"] == "pending_approval"

    # Extract the pending change and check warnings
    pending = mock_entry.runtime_data.pending.get("_global")
    assert pending is not None
    assert hasattr(pending, "warnings")
    assert len(pending.warnings) > 0
    assert any("id" in w.lower() and "regen" in w.lower() or "differ" in w.lower() for w in pending.warnings)


async def test_get_tools_returns_three_instances(hass, mock_entry):
    """Test that get_tools returns exactly three tool instances."""
    tools = get_tools(hass, mock_entry)
    assert len(tools) == 3
    assert isinstance(tools[0], ConfigHelperCreate)
    assert isinstance(tools[1], ConfigHelperEdit)
    assert isinstance(tools[2], ConfigHelperDelete)
