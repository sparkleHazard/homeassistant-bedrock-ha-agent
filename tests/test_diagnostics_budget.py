"""Tests for per-turn diagnostic tool-call budget (AC D47)."""
import pytest
from unittest.mock import MagicMock
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import llm

from custom_components.bedrock_ha_agent.const import (
    CONF_DIAGNOSTICS_CALL_BUDGET_PER_TURN,
    CONF_ENABLE_DIAGNOSTICS,
    DOMAIN,
)
from custom_components.bedrock_ha_agent.diagnostics.base import (
    check_and_consume_budget,
    reset_turn_budget,
)
from custom_components.bedrock_ha_agent.runtime_data import BedrockRuntimeData

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture
async def mock_entry_with_budget(hass):
    """Create a mock config entry with budget=3."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            CONF_ENABLE_DIAGNOSTICS: True,
            CONF_DIAGNOSTICS_CALL_BUDGET_PER_TURN: 3,
        },
        entry_id="test_budget_entry",
        state=ConfigEntryState.LOADED,
    )
    entry.runtime_data = BedrockRuntimeData()
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def llm_context_conv_a():
    """Create a mock LLM context for conversation A."""
    context = MagicMock(spec=llm.LLMContext)
    context.conversation_id = "conv_a"
    context.device_id = None
    return context


@pytest.fixture
def llm_context_conv_b():
    """Create a mock LLM context for conversation B."""
    context = MagicMock(spec=llm.LLMContext)
    context.conversation_id = "conv_b"
    context.device_id = None
    return context


async def test_budget_allows_first_three_calls(hass, mock_entry_with_budget, llm_context_conv_a):
    """Budget allows first 3 calls, all return None (no error)."""
    for i in range(3):
        result = check_and_consume_budget(hass, mock_entry_with_budget, llm_context_conv_a)
        assert result is None, f"Call {i+1} should succeed (return None)"


async def test_budget_rejects_fourth_call(hass, mock_entry_with_budget, llm_context_conv_a):
    """The 4th call returns budget_exceeded error."""
    # Consume budget
    for _ in range(3):
        check_and_consume_budget(hass, mock_entry_with_budget, llm_context_conv_a)

    # 4th call should fail
    result = check_and_consume_budget(hass, mock_entry_with_budget, llm_context_conv_a)
    assert result is not None, "Expected error on 4th call"
    assert result["status"] == "budget_exceeded"
    assert "budget" in result
    assert result["budget"] == 3


async def test_reset_turn_budget_clears_counter(hass, mock_entry_with_budget, llm_context_conv_a):
    """After reset_turn_budget, the next call succeeds."""
    # Exhaust budget
    for _ in range(3):
        check_and_consume_budget(hass, mock_entry_with_budget, llm_context_conv_a)

    # Verify 4th call fails
    result = check_and_consume_budget(hass, mock_entry_with_budget, llm_context_conv_a)
    assert result is not None and result["status"] == "budget_exceeded"

    # Reset
    reset_turn_budget(hass, mock_entry_with_budget, llm_context_conv_a.conversation_id)

    # Next call should succeed
    result = check_and_consume_budget(hass, mock_entry_with_budget, llm_context_conv_a)
    assert result is None, "Expected success after reset"


async def test_budget_is_per_conversation(hass, mock_entry_with_budget, llm_context_conv_a, llm_context_conv_b):
    """conv_a at 3 calls is exhausted; conv_b still gets its full 3."""
    # Exhaust conv_a
    for _ in range(3):
        check_and_consume_budget(hass, mock_entry_with_budget, llm_context_conv_a)

    result_a = check_and_consume_budget(hass, mock_entry_with_budget, llm_context_conv_a)
    assert result_a is not None and result_a["status"] == "budget_exceeded"

    # conv_b should still have full budget
    for i in range(3):
        result_b = check_and_consume_budget(hass, mock_entry_with_budget, llm_context_conv_b)
        assert result_b is None, f"conv_b call {i+1} should succeed"
