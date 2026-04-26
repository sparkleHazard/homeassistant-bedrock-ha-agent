"""Tests for M2: object_id sanitization and collision handling."""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock
import pytest

from custom_components.bedrock_ha_agent.config_tools.automation import ConfigAutomationCreate


@pytest.fixture
def tool():
    """Create a ConfigAutomationCreate tool instance."""
    return ConfigAutomationCreate()


@pytest.fixture
def tool_input():
    """Create a mock tool input."""
    tool_input = Mock()
    tool_input.tool_args = {
        "config": {
            "alias": "Morning Routine",
            "trigger": [{"platform": "time", "at": "06:00:00"}],
            "action": [{"service": "light.turn_on", "target": {"entity_id": "light.bedroom"}}],
        }
    }
    return tool_input


@pytest.mark.asyncio
async def test_create_collision_appends_suffix(tool, tool_input):
    """Test that object_id collision appends numeric suffix (M2 fix)."""
    from custom_components.bedrock_ha_agent.config_tools.ha_client import automation as ha_automation

    mock_hass = Mock()

    # Mock existing automation with object_id="morning_routine"
    existing_automation = {"alias": "Morning Routine", "trigger": [], "action": []}

    async def mock_get_automation(hass, object_id):
        if object_id == "morning_routine":
            return existing_automation
        elif object_id == "morning_routine_2":
            return None  # Second attempt succeeds
        return None

    with AsyncMock() as mock_get:
        ha_automation.get_automation = mock_get
        mock_get.side_effect = mock_get_automation

        result = await tool.build_proposed_payload(mock_hass, tool_input)

        # Should append _2 to avoid collision
        assert result["_object_id"] == "morning_routine_2"


@pytest.mark.asyncio
async def test_create_sanitizes_object_id(tool):
    """Test that invalid object_id is sanitized (M2 fix)."""
    from custom_components.bedrock_ha_agent.config_tools.ha_client import automation as ha_automation

    mock_hass = Mock()

    # Mock no existing automations
    ha_automation.get_automation = AsyncMock(return_value=None)

    # LLM provides dangerous object_id
    tool_input = Mock()
    tool_input.tool_args = {
        "object_id": "../etc/passwd",
        "config": {
            "alias": "Evil Automation",
            "trigger": [],
            "action": [],
        }
    }

    result = await tool.build_proposed_payload(mock_hass, tool_input)

    # Should sanitize to only lowercase alphanumeric + underscore
    object_id = result["_object_id"]
    assert object_id != "../etc/passwd"
    # Should be cleaned to something like "etc_passwd" or rejected
    assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in object_id)
    assert len(object_id) <= 64


@pytest.mark.asyncio
async def test_summary_includes_object_id(tool):
    """Test that proposed_summary includes object_id (M2 fix)."""
    from custom_components.bedrock_ha_agent.config_tools.ha_client import automation as ha_automation

    mock_hass = Mock()

    # Mock no existing automations
    ha_automation.get_automation = AsyncMock(return_value=None)

    tool_input = Mock()
    tool_input.tool_args = {
        "config": {
            "alias": "Test Automation",
            "trigger": [],
            "action": [],
        }
    }

    proposed = await tool.build_proposed_payload(mock_hass, tool_input)
    summary = tool.build_proposed_summary(proposed, None)

    # Summary should include object_id so user sees what they're approving
    assert "object_id:" in summary
    assert proposed["_object_id"] in summary
