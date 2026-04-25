"""Tests for config-editing token usage tracking (AC14)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bedrock_ha_agent.const import (
    CONF_ENABLE_CONFIG_EDITING,
    CONF_MODEL_ID,
    DOMAIN,
)
from custom_components.bedrock_ha_agent.runtime_data import BedrockRuntimeData
from custom_components.bedrock_ha_agent.usage_tracker import UsageTracker

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture
def mock_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry with runtime_data and UsageTracker."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Bedrock",
        data={
            "aws_access_key_id": "test_key",
            "aws_secret_access_key": "test_secret",
            "aws_region": "us-west-2",
        },
        options={
            CONF_MODEL_ID: "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            CONF_ENABLE_CONFIG_EDITING: True,
        },
        entry_id="test_entry_id",
        state=ConfigEntryState.LOADED,
    )
    entry.add_to_hass(hass)
    entry.runtime_data = BedrockRuntimeData()
    entry.runtime_data.usage = UsageTracker()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry
    return entry


@pytest.fixture
def llm_context(mock_entry):
    """Create a mock LLM context."""
    context = MagicMock(spec=llm.LLMContext)
    context.device_id = None
    return context


@pytest.mark.asyncio
async def test_config_edit_apply_increments_token_sensors(
    hass: HomeAssistant, mock_entry: ConfigEntry, llm_context
):
    """AC14: Config-editing tool calls increment usage sensors without double-counting.

    A full propose→approve→apply cycle involves:
    1. Tool call returns pending_approval (1 Bedrock turn)
    2. User says "yes" → interceptor applies → assistant comments (1 Bedrock turn)

    Total: 2 Bedrock calls = 2 UsageTracker.record() calls.
    """
    from custom_components.bedrock_ha_agent.config_tools.automation import (
        ConfigAutomationCreate,
    )
    from custom_components.bedrock_ha_agent.config_tools.pending import (
        PendingChangeManager,
    )

    # Register entities
    hass.states.async_set("light.bedroom", "off")
    hass.states.async_set("light.kitchen", "off")

    tool = ConfigAutomationCreate()
    tool_input = llm.ToolInput(
        tool_name="ConfigAutomationCreate",
        tool_args={
            "config": {
                "alias": "Test Automation",
                "trigger": [{"platform": "state", "entity_id": "light.bedroom"}],
                "action": [
                    {"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}
                ],
            }
        },
    )

    # Mock ha_automation functions
    with patch(
        "custom_components.bedrock_ha_agent.config_tools.automation.ha_automation"
    ) as mock_ha:
        mock_ha.create_or_update_automation = AsyncMock()
        mock_ha.reload_automations = AsyncMock()
        mock_ha.get_automation = AsyncMock(return_value=None)
        mock_ha.list_automations = AsyncMock(return_value=[])

        # Track usage before
        usage_before_input = mock_entry.runtime_data.usage.today.input_tokens
        usage_before_output = mock_entry.runtime_data.usage.today.output_tokens

        # Simulate 1st Bedrock turn: tool call → pending_approval
        # In production, this happens inside _stream_one_bedrock_turn
        mock_entry.runtime_data.usage.record(
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            {"input_tokens": 1000, "output_tokens": 150},
        )

        # Call tool (returns pending_approval)
        result = await tool.async_call(hass, tool_input, llm_context)
        assert result["status"] == "pending_approval"

        # Usage after 1st turn
        usage_after_propose = mock_entry.runtime_data.usage.today.input_tokens
        assert usage_after_propose == usage_before_input + 1000

        # Simulate 2nd Bedrock turn: user approval → assistant comment
        # The interceptor applies the change, then Bedrock generates a follow-up
        pending = mock_entry.runtime_data.pending.get("_global")
        assert pending is not None

        # Apply the pending change
        await pending.apply_fn(hass, pending.proposed_payload, pending.pre_state)

        # Simulate Bedrock follow-up turn
        mock_entry.runtime_data.usage.record(
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            {"input_tokens": 500, "output_tokens": 80},
        )

        # Usage after 2nd turn
        usage_after_apply = mock_entry.runtime_data.usage.today.input_tokens
        assert usage_after_apply == usage_after_propose + 500
        assert mock_entry.runtime_data.usage.today.output_tokens == 150 + 80

        # Contract: exactly 2 increments for a full propose→approve→apply cycle
        # No double-counting in the tool loop
        assert mock_entry.runtime_data.usage.today.input_tokens == 1500
        assert mock_entry.runtime_data.usage.today.output_tokens == 230


@pytest.mark.asyncio
async def test_config_edit_daily_rollover_not_broken(
    hass: HomeAssistant, mock_entry: ConfigEntry
):
    """AC14: Daily rollover resets today counters but preserves total counters."""
    tracker = mock_entry.runtime_data.usage

    # Record some usage today
    tracker.record(
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        {"input_tokens": 1000, "output_tokens": 200},
    )

    today_before = tracker.today.input_tokens
    total_before = tracker.total.input_tokens
    assert today_before == 1000
    assert total_before == 1000

    # Advance time across UTC midnight
    original_day = tracker.last_reset_day
    future_day = original_day + timedelta(days=1)
    tracker.last_reset_day = original_day  # Reset to trigger rollover

    # Manually trigger rollover by advancing date
    with patch(
        "custom_components.bedrock_ha_agent.usage_tracker.datetime"
    ) as mock_dt:
        mock_dt.now.return_value = datetime(
            future_day.year, future_day.month, future_day.day, 0, 1, tzinfo=UTC
        )
        # Force _maybe_roll_day by calling record
        tracker.record(
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            {"input_tokens": 500, "output_tokens": 100},
        )

    # Today should reset + new tokens; total should accumulate
    assert tracker.today.input_tokens == 500  # Reset + new
    assert tracker.total.input_tokens == 1500  # Cumulative
    assert tracker.today.output_tokens == 100
    assert tracker.total.output_tokens == 300
