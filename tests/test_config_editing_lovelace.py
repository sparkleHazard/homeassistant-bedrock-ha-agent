"""Tests for Lovelace config editing tools."""

import pytest
from unittest.mock import MagicMock, patch

from custom_components.bedrock_ha_agent.config_tools.lovelace import (
    ConfigLovelaceCardAdd,
    ConfigLovelaceCardRemove,
    ConfigLovelaceDashboardCreate,
    get_tools,
)
from homeassistant.helpers import llm

pytest_plugins = ["pytest_homeassistant_custom_component"]


# Fixtures

@pytest.fixture
def mock_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.options = {}
    return entry


@pytest.fixture
def mock_llm_context():
    """Create a mock LLM context."""
    context = MagicMock(spec=llm.LLMContext)
    context.device_id = None
    return context


@pytest.fixture
def sample_dashboard():
    """Sample dashboard config."""
    return {
        "title": "Test Dashboard",
        "views": [
            {
                "path": "home",
                "title": "Home",
                "cards": [
                    {"type": "entities", "entities": ["light.living_room"]},
                ],
            },
            {
                "path": "devices",
                "title": "Devices",
                "cards": [],
            },
        ],
    }


# Test ConfigLovelaceCardAdd

@pytest.mark.asyncio
async def test_add_card_golden_path(mock_entry, mock_llm_context, sample_dashboard):
    """Test AC8: add card to storage-mode dashboard."""
    mock_hass = MagicMock()
    mock_hass.data = {}

    tool = ConfigLovelaceCardAdd()

    new_card = {"type": "weather-forecast", "entity": "weather.home"}
    tool_input = llm.ToolInput(
        tool_name="ConfigLovelaceCardAdd",
        tool_args={
            "url_path": "test-dash",
            "view_path": "home",
            "card": new_card,
        },
    )

    with patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.get_dashboard_mode") as mock_mode, \
         patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.load_dashboard") as mock_load, \
         patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.save_dashboard") as mock_save:

        mock_mode.return_value = "storage"
        mock_load.return_value = sample_dashboard
        mock_save.return_value = None

        # Build states
        pre_state = await tool.build_pre_state(mock_hass, tool_input)
        assert pre_state == sample_dashboard

        proposed = await tool.build_proposed_payload(mock_hass, tool_input)
        assert proposed is not None
        assert len(proposed["views"][0]["cards"]) == 2
        assert proposed["views"][0]["cards"][1] == new_card
        assert proposed["_url_path"] == "test-dash"

        # Validate
        result = await tool.validate(mock_hass, proposed, pre_state)
        assert result.ok

        # Summary and diff
        summary = tool.build_proposed_summary(proposed, pre_state)
        assert "Would add" in summary
        assert "weather-forecast" in summary

        diff = tool.build_proposed_diff(proposed, pre_state)
        assert "+" in diff

        # Apply
        apply_result = await tool.apply_change(mock_hass, proposed, pre_state)
        assert apply_result["status"] == "success"
        mock_save.assert_called_once()

        # Verify saved config has no metadata
        saved_config = mock_save.call_args[0][2]
        assert "_url_path" not in saved_config
        assert len(saved_config["views"][0]["cards"]) == 2


@pytest.mark.asyncio
async def test_add_card_yaml_mode_rejected(mock_entry, mock_llm_context, sample_dashboard):
    """Test AC18: YAML-mode dashboard rejects card add."""
    mock_hass = MagicMock()
    mock_hass.data = {}

    tool = ConfigLovelaceCardAdd()

    new_card = {"type": "button", "entity": "switch.test"}
    tool_input = llm.ToolInput(
        tool_name="ConfigLovelaceCardAdd",
        tool_args={
            "url_path": "lovelace",
            "view_path": "home",
            "card": new_card,
        },
    )

    with patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.get_dashboard_mode") as mock_mode, \
         patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.load_dashboard") as mock_load, \
         patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.save_dashboard") as mock_save:

        mock_mode.return_value = "yaml"
        mock_load.return_value = sample_dashboard

        # Build states
        pre_state = await tool.build_pre_state(mock_hass, tool_input)
        proposed = await tool.build_proposed_payload(mock_hass, tool_input)

        # Validate - should fail with YAML mode error
        result = await tool.validate(mock_hass, proposed, pre_state)
        assert not result.ok
        assert len(result.errors) == 1
        assert result.errors[0].code == "lovelace_yaml_mode"
        assert "configuration.yaml" in result.errors[0].message

        # Verify no load_dashboard or save_dashboard was called during validation
        mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_add_card_unknown_view_rejected(mock_llm_context, sample_dashboard):
    """Test: unknown view path is rejected."""
    mock_hass = MagicMock()
    mock_hass.data = {}

    tool = ConfigLovelaceCardAdd()

    new_card = {"type": "button", "entity": "switch.test"}
    tool_input = llm.ToolInput(
        tool_name="ConfigLovelaceCardAdd",
        tool_args={
            "url_path": None,
            "view_path": "nonexistent",
            "card": new_card,
        },
    )

    with patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.get_dashboard_mode") as mock_mode, \
         patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.load_dashboard") as mock_load:

        mock_mode.return_value = "storage"
        mock_load.return_value = sample_dashboard

        pre_state = await tool.build_pre_state(mock_hass, tool_input)
        proposed = await tool.build_proposed_payload(mock_hass, tool_input)

        # Should have error marker
        assert "_error" in proposed
        assert proposed["_error"].startswith("view_not_found:")

        result = await tool.validate(mock_hass, proposed, pre_state)
        assert not result.ok
        assert result.errors[0].code == "unknown_view"


@pytest.mark.asyncio
async def test_add_card_missing_type_rejected(mock_llm_context, sample_dashboard):
    """Test: card without 'type' field is rejected."""
    mock_hass = MagicMock()
    mock_hass.data = {}

    tool = ConfigLovelaceCardAdd()

    # Card missing 'type'
    invalid_card = {"entity": "switch.test"}
    tool_input = llm.ToolInput(
        tool_name="ConfigLovelaceCardAdd",
        tool_args={
            "url_path": None,
            "view_path": "home",
            "card": invalid_card,
        },
    )

    with patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.get_dashboard_mode") as mock_mode, \
         patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.load_dashboard") as mock_load:

        mock_mode.return_value = "storage"
        mock_load.return_value = sample_dashboard

        pre_state = await tool.build_pre_state(mock_hass, tool_input)
        proposed = await tool.build_proposed_payload(mock_hass, tool_input)

        result = await tool.validate(mock_hass, proposed, pre_state)
        assert not result.ok
        assert result.errors[0].code == "missing_field"
        assert "type" in result.errors[0].message


# Test ConfigLovelaceCardRemove

@pytest.mark.asyncio
async def test_remove_card_golden_path(mock_llm_context, sample_dashboard):
    """Test: remove card from dashboard."""
    mock_hass = MagicMock()
    mock_hass.data = {}

    tool = ConfigLovelaceCardRemove()

    tool_input = llm.ToolInput(
        tool_name="ConfigLovelaceCardRemove",
        tool_args={
            "url_path": "test-dash",
            "view_path": "home",
            "card_index": 0,
        },
    )

    with patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.get_dashboard_mode") as mock_mode, \
         patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.load_dashboard") as mock_load, \
         patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.save_dashboard") as mock_save:

        mock_mode.return_value = "storage"
        mock_load.return_value = sample_dashboard
        mock_save.return_value = None

        pre_state = await tool.build_pre_state(mock_hass, tool_input)
        assert len(pre_state["views"][0]["cards"]) == 1

        proposed = await tool.build_proposed_payload(mock_hass, tool_input)
        assert len(proposed["views"][0]["cards"]) == 0

        result = await tool.validate(mock_hass, proposed, pre_state)
        assert result.ok

        await tool.apply_change(mock_hass, proposed, pre_state)
        mock_save.assert_called_once()

        saved_config = mock_save.call_args[0][2]
        assert len(saved_config["views"][0]["cards"]) == 0


@pytest.mark.asyncio
async def test_remove_card_index_out_of_range_rejected(mock_llm_context, sample_dashboard):
    """Test: card index out of range is rejected."""
    mock_hass = MagicMock()
    mock_hass.data = {}

    tool = ConfigLovelaceCardRemove()

    tool_input = llm.ToolInput(
        tool_name="ConfigLovelaceCardRemove",
        tool_args={
            "url_path": None,
            "view_path": "home",
            "card_index": 99,
        },
    )

    with patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.get_dashboard_mode") as mock_mode, \
         patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.load_dashboard") as mock_load:

        mock_mode.return_value = "storage"
        mock_load.return_value = sample_dashboard

        pre_state = await tool.build_pre_state(mock_hass, tool_input)
        proposed = await tool.build_proposed_payload(mock_hass, tool_input)

        assert "_error" in proposed
        assert "card_index_out_of_range" in proposed["_error"]

        result = await tool.validate(mock_hass, proposed, pre_state)
        assert not result.ok
        assert result.errors[0].code == "card_index_out_of_range"


# Test ConfigLovelaceDashboardCreate

@pytest.mark.asyncio
async def test_dashboard_create_golden_path(mock_llm_context):
    """Test: create new dashboard."""
    mock_hass = MagicMock()
    mock_hass.data = {}

    tool = ConfigLovelaceDashboardCreate()

    tool_input = llm.ToolInput(
        tool_name="ConfigLovelaceDashboardCreate",
        tool_args={
            "url_path": "new-dash",
            "title": "New Dashboard",
            "icon": "mdi:home",
            "show_in_sidebar": True,
            "require_admin": False,
        },
    )

    with patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.list_dashboards") as mock_list, \
         patch("custom_components.bedrock_ha_agent.config_tools.ha_client.lovelace.create_dashboard") as mock_create:

        mock_list.return_value = []  # No existing dashboards
        mock_create.return_value = "new-dash"

        pre_state = await tool.build_pre_state(mock_hass, tool_input)
        assert pre_state is None

        proposed = await tool.build_proposed_payload(mock_hass, tool_input)
        assert proposed["url_path"] == "new-dash"
        assert proposed["title"] == "New Dashboard"
        assert proposed["icon"] == "mdi:home"

        result = await tool.validate(mock_hass, proposed, pre_state)
        assert result.ok

        summary = tool.build_proposed_summary(proposed, pre_state)
        assert "Would create" in summary
        assert "New Dashboard" in summary

        apply_result = await tool.apply_change(mock_hass, proposed, pre_state)
        assert apply_result["url_path"] == "new-dash"
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_get_tools_returns_three_instances(mock_entry):
    """Test: get_tools returns three tool instances."""
    mock_hass = MagicMock()
    mock_hass.data = {}

    tools = get_tools(mock_hass, mock_entry)
    assert len(tools) == 3
    assert isinstance(tools[0], ConfigLovelaceCardAdd)
    assert isinstance(tools[1], ConfigLovelaceCardRemove)
    assert isinstance(tools[2], ConfigLovelaceDashboardCreate)
