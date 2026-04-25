"""Phase 5 Step 5.2: AC16 concurrent voice conversation isolation tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bedrock_conversation.config_tools.pending import (
    ApprovalOutcome,
    PendingChangeManager,
)
from custom_components.bedrock_conversation.config_tools.undo import (
    UndoEntry,
    get_or_create_stack,
)
from custom_components.bedrock_conversation.const import (
    CONF_ENABLE_CONFIG_EDITING,
    CONF_MODEL_ID,
    DOMAIN,
)
from custom_components.bedrock_conversation.runtime_data import BedrockRuntimeData

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture
def mock_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry with runtime_data."""
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
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry
    return entry


@pytest.mark.asyncio
async def test_two_conversations_do_not_cross_contaminate(
    hass: HomeAssistant, mock_entry: MockConfigEntry
):
    """Test AC16: two conversations with distinct conversation_ids are isolated.

    A's "yes" applies A only, leaves B's PendingChange intact.
    """
    # Create two pending changes in different conversations
    manager_a = PendingChangeManager.for_entry_conv(
        hass, mock_entry.entry_id, "voice-kitchen-abc"
    )
    manager_b = PendingChangeManager.for_entry_conv(
        hass, mock_entry.entry_id, "voice-office-xyz"
    )

    apply_fn_a = AsyncMock(return_value={"status": "success"})
    apply_fn_b = AsyncMock(return_value={"status": "success"})
    restore_fn_a = AsyncMock()
    restore_fn_b = AsyncMock()

    pending_a = manager_a.create(
        tool_name="ConfigAutomationCreate",
        proposed_payload={"automation": "A"},
        pre_state=None,
        proposed_summary="Would add automation A",
        proposed_diff="+ automation A",
        approval_ttl_seconds=300,
    )
    pending_a.apply_fn = apply_fn_a  # type: ignore[attr-defined]
    pending_a.restore_fn = restore_fn_a  # type: ignore[attr-defined]
    pending_a.warnings = []  # type: ignore[attr-defined]

    pending_b = manager_b.create(
        tool_name="ConfigSceneCreate",
        proposed_payload={"scene": "B"},
        pre_state=None,
        proposed_summary="Would add scene B",
        proposed_diff="+ scene B",
        approval_ttl_seconds=300,
    )
    pending_b.apply_fn = apply_fn_b  # type: ignore[attr-defined]
    pending_b.restore_fn = restore_fn_b  # type: ignore[attr-defined]
    pending_b.warnings = []  # type: ignore[attr-defined]

    # A approves (handle_approval_intent returns APPLIED outcome; apply happens in interceptor)
    outcome_a = manager_a.handle_approval_intent("yes")
    assert outcome_a.intercepted
    assert outcome_a.outcome == ApprovalOutcome.APPLIED

    # Simulate interceptor applying A's change
    await apply_fn_a(hass, pending_a.proposed_payload, pending_a.pre_state)

    # Push to A's undo stack (simulating what interceptor does)
    stack_a = get_or_create_stack(hass, mock_entry.entry_id, "voice-kitchen-abc")
    from datetime import UTC, datetime, timedelta
    undo_entry_a = UndoEntry(
        entry_id=mock_entry.entry_id,
        conversation_id="voice-kitchen-abc",
        proposal_id=pending_a.proposal_id,
        tool_name="ConfigAutomationCreate",
        before_state=None,
        after_state=pending_a.proposed_payload,
        restore_fn=restore_fn_a,
        timestamp=datetime.now(UTC),
        ttl=timedelta(seconds=3600),
        warnings=[],
    )
    stack_a.push(undo_entry_a)
    manager_a.clear_current()

    # Verify A's pending is cleared
    assert manager_a.get_current() is None

    # Verify B's pending is still intact
    assert manager_b.get_current() is not None
    assert manager_b.get_current().tool_name == "ConfigSceneCreate"
    apply_fn_b.assert_not_called()

    # Verify A's undo stack has entry, B's is empty
    stack_b = get_or_create_stack(hass, mock_entry.entry_id, "voice-office-xyz")
    assert len(stack_a._deque) == 1
    assert len(stack_b._deque) == 0

    # B rejects
    outcome_b = manager_b.handle_approval_intent("cancel")
    assert outcome_b.intercepted

    # Verify B's pending is cleared without apply
    assert manager_b.get_current() is None
    apply_fn_b.assert_not_called()


@pytest.mark.asyncio
async def test_undo_ambiguous_when_two_undo_stacks_nonempty(
    hass: HomeAssistant, mock_entry: MockConfigEntry
):
    """Test AC16: undo service without conversation_id returns ambiguous error when ≥2 stacks non-empty."""
    from custom_components.bedrock_conversation import _async_register_undo_service

    await _async_register_undo_service(hass)

    # Push to two different conversation stacks
    for conv_id in ["voice-kitchen-abc", "voice-office-xyz"]:
        stack = get_or_create_stack(hass, mock_entry.entry_id, conv_id)
        undo_entry = UndoEntry(
            entry_id=mock_entry.entry_id,
            conversation_id=conv_id,
            proposal_id=f"prop_{conv_id}",
            tool_name="TestTool",
            before_state={},
            after_state={},
            restore_fn=AsyncMock(),
            timestamp=datetime.now(UTC),
            ttl=timedelta(seconds=3600),
            warnings=[],
        )
        stack.push(undo_entry)

    # Call service without conversation_id
    response = await hass.services.async_call(
        DOMAIN,
        "undo_last_config_change",
        {"config_entry_id": mock_entry.entry_id},
        blocking=True,
        return_response=True,
    )

    # Verify ambiguous error
    assert response["undone"] is False
    assert response["error"] == "ambiguous_conversation"
    assert set(response["conversation_ids"]) == {"voice-kitchen-abc", "voice-office-xyz"}


@pytest.mark.asyncio
async def test_explicit_conversation_id_disambiguates(
    hass: HomeAssistant, mock_entry: MockConfigEntry
):
    """Test that explicit conversation_id in undo service disambiguates."""
    from custom_components.bedrock_conversation import _async_register_undo_service

    await _async_register_undo_service(hass)

    # Push to two stacks
    restore_fn_a = AsyncMock()
    restore_fn_b = AsyncMock()

    for conv_id, restore_fn in [
        ("voice-kitchen-abc", restore_fn_a),
        ("voice-office-xyz", restore_fn_b),
    ]:
        stack = get_or_create_stack(hass, mock_entry.entry_id, conv_id)
        undo_entry = UndoEntry(
            entry_id=mock_entry.entry_id,
            conversation_id=conv_id,
            proposal_id=f"prop_{conv_id}",
            tool_name="TestTool",
            before_state={},
            after_state={},
            restore_fn=restore_fn,
            timestamp=datetime.now(UTC),
            ttl=timedelta(seconds=3600),
            warnings=[],
        )
        stack.push(undo_entry)

    # Call with explicit conversation_id for kitchen
    response = await hass.services.async_call(
        DOMAIN,
        "undo_last_config_change",
        {"config_entry_id": mock_entry.entry_id, "conversation_id": "voice-kitchen-abc"},
        blocking=True,
        return_response=True,
    )

    # Verify only A's restore was called
    assert response["undone"] is True
    restore_fn_a.assert_called_once()
    restore_fn_b.assert_not_called()

    # Verify only A's stack is empty
    stack_a = get_or_create_stack(hass, mock_entry.entry_id, "voice-kitchen-abc")
    stack_b = get_or_create_stack(hass, mock_entry.entry_id, "voice-office-xyz")
    assert len(stack_a._deque) == 0
    assert len(stack_b._deque) == 1
