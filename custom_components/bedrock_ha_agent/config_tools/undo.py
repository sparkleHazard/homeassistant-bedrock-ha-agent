"""In-memory undo stack per (entry_id, conversation_id).

Spec (Round 4 decision): in-memory only, no filesystem persistence. Cleared on HA restart.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


RestoreFn = Callable[[], Awaitable[None]]


@dataclass
class UndoEntry:
    """A single applied change that can be undone."""
    entry_id: str
    conversation_id: str
    proposal_id: str           # same proposal_id as the PendingChange that spawned it
    tool_name: str
    before_state: dict[str, Any] | None  # None if the original op was a "create" (restore = delete)
    after_state: dict[str, Any] | None   # None if the original op was a "delete" (restore = create)
    restore_fn: RestoreFn      # async callable invoked by pop to reverse the mutation
    timestamp: datetime        # UTC
    ttl: timedelta             # expiry window; stale entries are swept on every access
    warnings: list[str] = field(default_factory=list)  # user-visible caveats (e.g. label-id regen, area-id regen)

    def is_expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        return (current - self.timestamp) > self.ttl


class UndoStack:
    """Bounded FIFO undo stack scoped to a single (entry_id, conversation_id).

    `maxlen` oldest-evicts on push (collections.deque semantics).
    TTL expiry is lazy: expired entries are pruned on push/pop/peek/len.
    """

    def __init__(self, *, max_depth: int = 20, ttl_seconds: int = 3600) -> None:
        if max_depth < 1:
            raise ValueError("max_depth must be >= 1")
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be >= 1")
        self._deque: deque[UndoEntry] = deque(maxlen=max_depth)
        self._max_depth = max_depth
        self._ttl = timedelta(seconds=ttl_seconds)

    @property
    def max_depth(self) -> int:
        return self._max_depth

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    def _prune_expired(self, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        while self._deque and self._deque[0].is_expired(current):
            self._deque.popleft()

    def push(self, entry: UndoEntry, *, now: datetime | None = None) -> None:
        """Append; oldest entry is evicted automatically by deque maxlen."""
        # Normalize timestamp / ttl if caller didn't set them to match this stack's ttl
        if entry.ttl != self._ttl:
            entry.ttl = self._ttl
        self._prune_expired(now)
        self._deque.append(entry)

    def pop_latest(self, *, now: datetime | None = None) -> UndoEntry | None:
        """Return and remove the most recent non-expired entry, or None if empty."""
        self._prune_expired(now)
        if not self._deque:
            return None
        return self._deque.pop()

    def pop_specific(self, proposal_id: str, *, now: datetime | None = None) -> UndoEntry | None:
        """Remove and return the entry with the given proposal_id; None if absent."""
        self._prune_expired(now)
        for i, entry in enumerate(self._deque):
            if entry.proposal_id == proposal_id:
                # deque has no efficient mid-removal, reassemble
                removed = self._deque[i]
                new_items = [e for j, e in enumerate(self._deque) if j != i]
                self._deque.clear()
                self._deque.extend(new_items)
                return removed
        return None

    def peek(self, *, now: datetime | None = None) -> UndoEntry | None:
        self._prune_expired(now)
        return self._deque[-1] if self._deque else None

    def clear_expired(self, *, now: datetime | None = None) -> int:
        """Prune all expired entries; return count removed."""
        current = now or datetime.now(UTC)
        before = len(self._deque)
        remaining = [e for e in self._deque if not e.is_expired(current)]
        self._deque.clear()
        self._deque.extend(remaining)
        return before - len(self._deque)

    def __len__(self) -> int:
        self._prune_expired()
        return len(self._deque)

    def __bool__(self) -> bool:
        return len(self) > 0


def collect_non_empty_stacks(
    hass: "HomeAssistant", entry_id: str
) -> dict[str, UndoStack]:
    """Return only per-conversation stacks that have at least one unexpired entry.

    Used by `bedrock_ha_agent.undo_last_config_change` service handler to
    decide whether to demand a `conversation_id` parameter for disambiguation.
    """
    from custom_components.bedrock_ha_agent.runtime_data import _get_runtime_data

    rd = _get_runtime_data(hass, entry_id)
    return {
        conv_id: stack
        for conv_id, stack in rd.undo.items()
        if len(stack) > 0
    }


def get_or_create_stack(
    hass: "HomeAssistant",
    entry_id: str,
    conversation_id: str,
    *,
    max_depth: int = 20,
    ttl_seconds: int = 3600,
) -> UndoStack:
    """Resolve (or lazily create) the UndoStack for a given (entry, conversation)."""
    from custom_components.bedrock_ha_agent.runtime_data import _get_runtime_data

    rd = _get_runtime_data(hass, entry_id)
    stack = rd.undo.get(conversation_id)
    if stack is None:
        stack = UndoStack(max_depth=max_depth, ttl_seconds=ttl_seconds)
        rd.undo[conversation_id] = stack
    return stack
