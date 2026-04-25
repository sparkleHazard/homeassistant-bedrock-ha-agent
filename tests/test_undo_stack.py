"""Test cases for config_tools.undo in-memory undo stack."""
from __future__ import annotations

from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock

import pytest

from custom_components.bedrock_ha_agent.config_tools.undo import (
    UndoEntry,
    UndoStack,
    collect_non_empty_stacks,
    get_or_create_stack,
)
from custom_components.bedrock_ha_agent.runtime_data import BedrockRuntimeData


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
    """Minimal fake HomeAssistant for testing runtime_data access."""

    def __init__(self):
        self.config_entries = FakeConfigEntries()


def make_entry(
    proposal_id: str,
    *,
    entry_id: str = "test_entry",
    conversation_id: str = "conv1",
    tool_name: str = "test_tool",
    timestamp: datetime | None = None,
    ttl_seconds: int = 3600,
) -> UndoEntry:
    """Factory for test UndoEntry instances."""
    return UndoEntry(
        entry_id=entry_id,
        conversation_id=conversation_id,
        proposal_id=proposal_id,
        tool_name=tool_name,
        before_state={"state": "before"},
        after_state={"state": "after"},
        restore_fn=AsyncMock(),
        timestamp=timestamp or datetime.now(UTC),
        ttl=timedelta(seconds=ttl_seconds),
    )


def test_push_stores_entry():
    """Push one entry; peek returns same, len == 1."""
    stack = UndoStack(max_depth=20, ttl_seconds=3600)
    entry = make_entry("prop1")
    stack.push(entry)

    assert len(stack) == 1
    assert stack.peek() is entry


def test_push_21_evicts_oldest():
    """Push 21 entries; len == 20; first pushed is gone, last pushed is peekable."""
    stack = UndoStack(max_depth=20, ttl_seconds=3600)
    entries = [make_entry(f"prop{i}") for i in range(21)]

    for entry in entries:
        stack.push(entry)

    assert len(stack) == 20
    # First entry (prop0) should be evicted
    assert stack.pop_specific("prop0") is None
    # Last entry (prop20) should be peekable
    assert stack.peek().proposal_id == "prop20"


def test_pop_latest_returns_newest():
    """Push A, B, C; pop_latest returns C, then B, then A, then None."""
    stack = UndoStack(max_depth=20, ttl_seconds=3600)
    entry_a = make_entry("propA")
    entry_b = make_entry("propB")
    entry_c = make_entry("propC")

    stack.push(entry_a)
    stack.push(entry_b)
    stack.push(entry_c)

    assert stack.pop_latest() is entry_c
    assert stack.pop_latest() is entry_b
    assert stack.pop_latest() is entry_a
    assert stack.pop_latest() is None


def test_pop_specific_by_proposal_id():
    """Push A, B, C; pop_specific(B) returns B; pop_latest returns C."""
    stack = UndoStack(max_depth=20, ttl_seconds=3600)
    entry_a = make_entry("propA")
    entry_b = make_entry("propB")
    entry_c = make_entry("propC")

    stack.push(entry_a)
    stack.push(entry_b)
    stack.push(entry_c)

    removed = stack.pop_specific("propB")
    assert removed is entry_b

    # C should still be at the top
    assert stack.pop_latest() is entry_c
    # A should still be available
    assert stack.pop_latest() is entry_a


def test_pop_specific_absent_returns_none():
    """pop_specific for non-existent proposal_id returns None."""
    stack = UndoStack(max_depth=20, ttl_seconds=3600)
    stack.push(make_entry("prop1"))

    assert stack.pop_specific("nonexistent") is None


def test_ttl_expiry_prunes_on_access():
    """Push with ttl_seconds=1; advance time 2s; len == 0; pop_latest returns None."""
    stack = UndoStack(max_depth=20, ttl_seconds=1)
    now = datetime.now(UTC)

    entry = make_entry("prop1", timestamp=now, ttl_seconds=1)
    stack.push(entry, now=now)

    # Advance time 2 seconds
    future = now + timedelta(seconds=2)

    assert len(stack) == 1  # Before expiry check with future time
    assert stack.pop_latest(now=future) is None  # Expired

    # Alternative check via __len__ with future time
    stack.push(entry, now=now)
    # Direct prune call
    stack._prune_expired(now=future)
    assert len(stack) == 0


def test_two_conversations_independent():
    """get_or_create_stack returns distinct instances for different conversation_ids."""
    hass = FakeHass()
    entry_id = "test_entry"

    # Initialize runtime data via config_entries
    hass.config_entries.add_entry(entry_id)

    stack1 = get_or_create_stack(hass, entry_id, "conv1")
    stack2 = get_or_create_stack(hass, entry_id, "conv2")

    assert stack1 is not stack2

    stack1.push(make_entry("prop1", conversation_id="conv1"))

    assert len(stack1) == 1
    assert len(stack2) == 0


def test_collect_non_empty_stacks():
    """Three conversations, two have pushes, one empty; result is dict of 2 entries."""
    hass = FakeHass()
    entry_id = "test_entry"

    hass.config_entries.add_entry(entry_id)

    stack1 = get_or_create_stack(hass, entry_id, "conv1")
    stack2 = get_or_create_stack(hass, entry_id, "conv2")
    stack3 = get_or_create_stack(hass, entry_id, "conv3")

    stack1.push(make_entry("prop1", conversation_id="conv1"))
    stack2.push(make_entry("prop2", conversation_id="conv2"))
    # stack3 remains empty

    result = collect_non_empty_stacks(hass, entry_id)

    assert len(result) == 2
    assert "conv1" in result
    assert "conv2" in result
    assert "conv3" not in result


def test_collect_with_expired_only_excluded():
    """Stack with only expired entries is excluded from collect_non_empty_stacks."""
    hass = FakeHass()
    entry_id = "test_entry"

    hass.config_entries.add_entry(entry_id)

    now = datetime.now(UTC)
    future = now + timedelta(seconds=2)

    stack = get_or_create_stack(hass, entry_id, "conv1", ttl_seconds=1)
    entry = make_entry("prop1", conversation_id="conv1", timestamp=now, ttl_seconds=1)
    stack.push(entry, now=now)

    # Before expiry
    result = collect_non_empty_stacks(hass, entry_id)
    assert "conv1" in result

    # After expiry - force prune via len check which happens in collect
    stack._prune_expired(now=future)
    result = collect_non_empty_stacks(hass, entry_id)
    assert "conv1" not in result


def test_max_depth_1():
    """Construct with max_depth=1; push two; only the last remains."""
    stack = UndoStack(max_depth=1, ttl_seconds=3600)

    entry1 = make_entry("prop1")
    entry2 = make_entry("prop2")

    stack.push(entry1)
    stack.push(entry2)

    assert len(stack) == 1
    assert stack.peek() is entry2


def test_invalid_max_depth_raises():
    """max_depth < 1 raises ValueError."""
    with pytest.raises(ValueError, match="max_depth must be >= 1"):
        UndoStack(max_depth=0, ttl_seconds=3600)


def test_invalid_ttl_raises():
    """ttl_seconds < 1 raises ValueError."""
    with pytest.raises(ValueError, match="ttl_seconds must be >= 1"):
        UndoStack(max_depth=20, ttl_seconds=0)


def test_clear_expired_returns_count():
    """clear_expired prunes expired entries and returns count removed."""
    stack = UndoStack(max_depth=20, ttl_seconds=1)
    now = datetime.now(UTC)
    future = now + timedelta(seconds=2)

    # Push 3 expired entries at time 'now'
    for i in range(3):
        entry = make_entry(f"prop{i}", timestamp=now, ttl_seconds=1)
        stack.push(entry, now=now)

    # Push 2 fresh entries at time 'future' (so they won't be expired at 'future')
    for i in range(3, 5):
        entry = make_entry(f"prop{i}", timestamp=future, ttl_seconds=1)
        # Don't auto-prune when pushing these - use now=now to keep the old entries
        stack._deque.append(entry)

    # Clear expired at 'future' time
    removed = stack.clear_expired(now=future)

    assert removed == 3
    assert len(stack) == 2
