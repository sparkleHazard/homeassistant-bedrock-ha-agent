"""Tests for diagnostics reload undo behavior (AC D43)."""
from unittest.mock import MagicMock

import pytest
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bedrock_ha_agent.const import DOMAIN
from custom_components.bedrock_ha_agent.diagnostics.lifecycle import (
    DiagnosticsReloadConfigEntry,
    DiagnosticsReloadIntegration,
)
from custom_components.bedrock_ha_agent.runtime_data import BedrockRuntimeData

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.mark.asyncio
async def test_reload_integration_undo_is_no_op(hass):
    """AC D43: DiagnosticsReloadIntegration's restore_fn is a no-op."""
    entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry")
    entry.runtime_data = BedrockRuntimeData()
    entry.add_to_hass(hass)

    tool = DiagnosticsReloadIntegration()
    llm_context = MagicMock(spec=llm.LLMContext)
    llm_context.device_id = None
    llm_context.conversation_id = "test_conv"

    tool_input = llm.ToolInput(
        tool_name="DiagnosticsReloadIntegration",
        tool_args={"domain": "automation"},
    )

    pre_state = await tool.build_pre_state(hass, tool_input)
    proposed = await tool.build_proposed_payload(hass, tool_input)
    restore_fn = await tool.build_restore_fn(hass, proposed, pre_state)

    assert callable(restore_fn)
    result = await restore_fn()

    # Strict contract: restore_fn returns {"restored": False, "reason": "reload is one-way"}
    assert result == {"restored": False, "reason": "reload is one-way"}, result

    # tool_warnings explicitly signals no-op undo
    warnings = tool.tool_warnings(proposed, pre_state)
    assert any("no-op" in w.lower() and "reload" in w.lower() for w in warnings), warnings


@pytest.mark.asyncio
async def test_reload_config_entry_undo_is_no_op(hass):
    """Same invariant for the entry-scoped reload tool."""
    entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry")
    entry.runtime_data = BedrockRuntimeData()
    entry.add_to_hass(hass)

    tool = DiagnosticsReloadConfigEntry()
    tool_input = llm.ToolInput(
        tool_name="DiagnosticsReloadConfigEntry",
        tool_args={"entry_id": "some-other-entry-id"},
    )

    pre_state = await tool.build_pre_state(hass, tool_input)
    proposed = await tool.build_proposed_payload(hass, tool_input)
    restore_fn = await tool.build_restore_fn(hass, proposed, pre_state)

    result = await restore_fn()
    assert result == {"restored": False, "reason": "reload is one-way"}, result
