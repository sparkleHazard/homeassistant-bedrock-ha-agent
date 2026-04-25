"""Tests for PendingChangeManager."""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from custom_components.bedrock_conversation.config_tools.pending import (
    ApprovalOutcome,
    PendingChange,
    PendingChangeManager,
)
from custom_components.bedrock_conversation.runtime_data import BedrockRuntimeData


class FakeEntry:
    """Fake config entry."""

    def __init__(self, entry_id: str) -> None:
        """Initialize fake entry."""
        self.entry_id = entry_id
        self.runtime_data = BedrockRuntimeData()


class FakeConfigEntries:
    """Fake config entries registry."""

    def __init__(self) -> None:
        """Initialize fake registry."""
        self._entries: dict[str, FakeEntry] = {}

    def add_entry(self, entry_id: str) -> FakeEntry:
        """Add a fake entry."""
        entry = FakeEntry(entry_id)
        self._entries[entry_id] = entry
        return entry

    def async_get_entry(self, entry_id: str) -> FakeEntry | None:
        """Get a fake entry."""
        return self._entries.get(entry_id)


class FakeHass:
    """Fake Home Assistant instance."""

    def __init__(self) -> None:
        """Initialize fake hass."""
        self.config_entries = FakeConfigEntries()


@pytest.fixture
def hass() -> FakeHass:
    """Create a fake hass instance."""
    return FakeHass()


@pytest.fixture
def entry_id(hass: FakeHass) -> str:
    """Create a fake entry and return its ID."""
    entry_id = "test_entry_123"
    hass.config_entries.add_entry(entry_id)
    return entry_id


@pytest.fixture
def conversation_id() -> str:
    """Return a test conversation ID."""
    return "conv_456"


@pytest.fixture
def manager(hass: FakeHass, entry_id: str, conversation_id: str) -> PendingChangeManager:
    """Create a PendingChangeManager."""
    return PendingChangeManager.for_entry_conv(hass, entry_id, conversation_id)


def test_create_stores_pending_for_conversation(manager: PendingChangeManager) -> None:
    """Test that create stores a pending change."""
    pending = manager.create(
        tool_name="test_tool",
        proposed_payload={"key": "value"},
        pre_state={"old": "state"},
        proposed_summary="Would create a test item",
        proposed_diff="+ new line",
    )

    assert pending is not None
    assert pending.tool_name == "test_tool"
    assert pending.proposed_payload == {"key": "value"}

    current = manager.get_current()
    assert current is not None
    assert current.proposal_id == pending.proposal_id


def test_supersede_replaces_pending(manager: PendingChangeManager) -> None:
    """Test that a second create replaces the first."""
    pending1 = manager.create(
        tool_name="tool1",
        proposed_payload={"v": 1},
        pre_state=None,
        proposed_summary="Would do thing 1",
        proposed_diff="+ line1",
    )

    pending2 = manager.create(
        tool_name="tool2",
        proposed_payload={"v": 2},
        pre_state=None,
        proposed_summary="Would do thing 2",
        proposed_diff="+ line2",
    )

    current = manager.get_current()
    assert current is not None
    assert current.proposal_id == pending2.proposal_id
    assert current.tool_name == "tool2"
    assert current.proposal_id != pending1.proposal_id


def test_two_conversations_independent(
    hass: FakeHass, entry_id: str, conversation_id: str
) -> None:
    """Test that two conversations maintain separate pending changes."""
    manager_a = PendingChangeManager.for_entry_conv(hass, entry_id, "conv_a")
    manager_b = PendingChangeManager.for_entry_conv(hass, entry_id, "conv_b")

    manager_a.create(
        tool_name="tool_a",
        proposed_payload={},
        pre_state=None,
        proposed_summary="Would do A",
        proposed_diff="+ a",
    )

    assert manager_a.get_current() is not None
    assert manager_b.get_current() is None


def test_past_tense_summary_rejected() -> None:
    """Test that past-tense summaries raise ValueError."""
    with pytest.raises(ValueError, match="past-tense token"):
        PendingChange(
            proposal_id="test_id",
            entry_id="entry",
            conversation_id="conv",
            tool_name="tool",
            proposed_payload={},
            pre_state=None,
            proposed_summary="Added the automation",
            proposed_diff="+ line",
            created_at=datetime.now(UTC),
            ttl=timedelta(seconds=300),
        )

    # M4: Also test mid-sentence past-tense detection
    with pytest.raises(ValueError, match="past-tense token"):
        PendingChange(
            proposal_id="test_id2",
            entry_id="entry",
            conversation_id="conv",
            tool_name="tool",
            proposed_payload={},
            pre_state=None,
            proposed_summary="Will update after automation created",
            proposed_diff="+ line",
            created_at=datetime.now(UTC),
            ttl=timedelta(seconds=300),
        )


def test_imperative_summary_accepted() -> None:
    """Test that imperative/future summaries are accepted."""
    pending = PendingChange(
        proposal_id="test_id",
        entry_id="entry",
        conversation_id="conv",
        tool_name="tool",
        proposed_payload={},
        pre_state=None,
        proposed_summary="Would add the automation",
        proposed_diff="+ line",
        created_at=datetime.now(UTC),
        ttl=timedelta(seconds=300),
    )
    assert pending.proposed_summary == "Would add the automation"


def test_intent_approval_token(manager: PendingChangeManager) -> None:
    """Test approval via token like 'yes'."""
    manager.create(
        tool_name="test_tool",
        proposed_payload={},
        pre_state=None,
        proposed_summary="Would create item",
        proposed_diff="+ line",
    )

    result = manager.handle_approval_intent("yes")
    assert result.outcome == ApprovalOutcome.APPLIED
    assert result.intercepted is True
    assert result.proposal_id is not None


def test_intent_approval_bare_phrase(manager: PendingChangeManager) -> None:
    """Test approval via bare phrase like 'do it'."""
    manager.create(
        tool_name="test_tool",
        proposed_payload={},
        pre_state=None,
        proposed_summary="Would create item",
        proposed_diff="+ line",
    )

    result = manager.handle_approval_intent("do it")
    assert result.outcome == ApprovalOutcome.APPLIED
    assert result.intercepted is True


def test_intent_reject_token(manager: PendingChangeManager) -> None:
    """Test rejection via token like 'cancel'."""
    manager.create(
        tool_name="test_tool",
        proposed_payload={},
        pre_state=None,
        proposed_summary="Would create item",
        proposed_diff="+ line",
    )

    result = manager.handle_approval_intent("cancel")
    assert result.outcome == ApprovalOutcome.REJECTED
    assert result.intercepted is True
    assert manager.get_current() is None


def test_intent_long_undo_sentence_not_intercepted(manager: PendingChangeManager) -> None:
    """Test that long sentences with 'undo' are not intercepted."""
    # No pending change
    result = manager.handle_approval_intent(
        "undo the bug in my washing machine automation"
    )
    assert result.outcome == ApprovalOutcome.NOT_INTERCEPTED
    assert result.intercepted is False


def test_intent_bare_undo_no_pending(manager: PendingChangeManager) -> None:
    """Test bare 'undo that' with no pending returns UNDONE."""
    result = manager.handle_approval_intent("undo that")
    assert result.outcome == ApprovalOutcome.UNDONE
    assert result.intercepted is True


def test_intent_no_pending_plain_speech(manager: PendingChangeManager) -> None:
    """Test normal speech with no pending is not intercepted."""
    result = manager.handle_approval_intent("hello, what's the weather?")
    assert result.outcome == ApprovalOutcome.NOT_INTERCEPTED
    assert result.intercepted is False


def test_expired_then_approval_returns_expired(
    hass: FakeHass, entry_id: str, conversation_id: str
) -> None:
    """Test that approval after expiry returns EXPIRED."""
    start_time = datetime.now(UTC)
    current_time = start_time

    def now_fn() -> datetime:
        return current_time

    manager = PendingChangeManager.for_entry_conv(
        hass, entry_id, conversation_id, now_fn=now_fn
    )

    # Create with 1 second TTL
    manager.create(
        tool_name="test_tool",
        proposed_payload={},
        pre_state=None,
        proposed_summary="Would create item",
        proposed_diff="+ line",
        approval_ttl_seconds=1,
    )

    # Advance time by 2 seconds
    current_time = start_time + timedelta(seconds=2)

    # Attempt approval
    result = manager.handle_approval_intent("yes")
    assert result.outcome == ApprovalOutcome.EXPIRED
    assert result.intercepted is True
    assert "expired" in result.user_message.lower()


def test_intent_approval_on_no_pending_not_intercepted(
    manager: PendingChangeManager,
) -> None:
    """Test that 'yes' with no pending is not intercepted."""
    result = manager.handle_approval_intent("yes")
    assert result.outcome == ApprovalOutcome.NOT_INTERCEPTED
    assert result.intercepted is False


def test_intent_yes_with_hedge_not_intercepted(manager: PendingChangeManager) -> None:
    """Test that 'yes but...' with hedge word is NOT intercepted (H1 fix)."""
    manager.create(
        tool_name="test_tool",
        proposed_payload={},
        pre_state=None,
        proposed_summary="Would create item",
        proposed_diff="+ line",
    )

    result = manager.handle_approval_intent("yes but actually never mind")
    assert result.outcome == ApprovalOutcome.NOT_INTERCEPTED
    assert result.intercepted is False
    # Pending should still exist
    assert manager.get_current() is not None


def test_intent_yes_please_apply_accepted(manager: PendingChangeManager) -> None:
    """Test that short approval without hedge is accepted."""
    manager.create(
        tool_name="test_tool",
        proposed_payload={},
        pre_state=None,
        proposed_summary="Would create item",
        proposed_diff="+ line",
    )

    result = manager.handle_approval_intent("yes please apply")
    assert result.outcome == ApprovalOutcome.APPLIED
    assert result.intercepted is True


def test_intent_ok_but_wait_not_intercepted(manager: PendingChangeManager) -> None:
    """Test that 'ok but wait' with hedge word is NOT intercepted."""
    manager.create(
        tool_name="test_tool",
        proposed_payload={},
        pre_state=None,
        proposed_summary="Would create item",
        proposed_diff="+ line",
    )

    result = manager.handle_approval_intent("ok but wait")
    assert result.outcome == ApprovalOutcome.NOT_INTERCEPTED
    assert result.intercepted is False


def test_intent_exact_do_it_still_works(manager: PendingChangeManager) -> None:
    """Test that bare 'do it' phrase still intercepts."""
    manager.create(
        tool_name="test_tool",
        proposed_payload={},
        pre_state=None,
        proposed_summary="Would create item",
        proposed_diff="+ line",
    )

    result = manager.handle_approval_intent("do it")
    assert result.outcome == ApprovalOutcome.APPLIED
    assert result.intercepted is True
