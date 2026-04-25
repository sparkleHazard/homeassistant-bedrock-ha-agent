"""Tests for M3: past-tense detector prepends correction to speech."""
from __future__ import annotations

from unittest.mock import Mock
import pytest

from custom_components.bedrock_ha_agent.conversation import _check_past_tense_vs_pending
from custom_components.bedrock_ha_agent.runtime_data import BedrockRuntimeData
from custom_components.bedrock_ha_agent.config_tools.pending import PendingChange
from datetime import UTC, datetime, timedelta


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock()
    hass.data = {"bedrock_ha_agent": {}}
    return hass


@pytest.fixture
def entry_id():
    """Return test entry ID."""
    return "test_entry_123"


@pytest.fixture
def conversation_id():
    """Return test conversation ID."""
    return "conv_456"


def test_past_tense_also_prepends_correction_to_speech(mock_hass, entry_id, conversation_id):
    """Test that past-tense detection returns correction text (M3 fix)."""
    # Set up runtime data with a pending change
    runtime_data = BedrockRuntimeData()
    pending = PendingChange(
        proposal_id="test_proposal",
        entry_id=entry_id,
        conversation_id=conversation_id,
        tool_name="ConfigAutomationCreate",
        proposed_payload={},
        pre_state=None,
        proposed_summary="Would create automation",
        proposed_diff="+ new automation",
        created_at=datetime.now(UTC),
        ttl=timedelta(seconds=300),
    )
    runtime_data.pending[conversation_id] = pending

    # Mock _get_runtime_data
    mock_hass.config_entries = Mock()
    mock_entry = Mock()
    mock_entry.entry_id = entry_id
    mock_entry.runtime_data = runtime_data
    mock_hass.config_entries.async_get_entry = Mock(return_value=mock_entry)

    # Text with past-tense claim
    final_text = "I've created the automation for you."

    # M3: Should return correction string
    correction = _check_past_tense_vs_pending(
        mock_hass,
        entry_id,
        conversation_id,
        final_text,
    )

    assert correction is not None
    assert "Heads up" in correction or "waiting for your approval" in correction
    assert "haven't applied" in correction


def test_past_tense_no_pending_returns_none(mock_hass, entry_id, conversation_id):
    """Test that no correction is returned when there's no pending change."""
    # Set up runtime data with NO pending change
    runtime_data = BedrockRuntimeData()
    runtime_data.pending[conversation_id] = None

    mock_hass.config_entries = Mock()
    mock_entry = Mock()
    mock_entry.entry_id = entry_id
    mock_entry.runtime_data = runtime_data
    mock_hass.config_entries.async_get_entry = Mock(return_value=mock_entry)

    final_text = "I've created the automation for you."

    # Should return None (no correction needed)
    correction = _check_past_tense_vs_pending(
        mock_hass,
        entry_id,
        conversation_id,
        final_text,
    )

    assert correction is None
