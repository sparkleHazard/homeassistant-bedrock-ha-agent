"""Pending change approval management for config editing tools."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from ..const import (
    APPROVAL_TOKENS,
    BARE_APPROVAL_UTTERANCES,
    BARE_UNDO_UTTERANCES,
    UNDO_TOKENS,
)
from ..runtime_data import _get_runtime_data

_LOGGER = logging.getLogger(__name__)

# Past-tense tokens rejected in proposal summaries
_PAST_TENSE_TOKENS = {
    "added",
    "created",
    "renamed",
    "deleted",
    "saved",
    "applied",
    "configured",
    "done",
    "updated",
    "removed",
}


def _normalize(s: str) -> str:
    """Normalize a user message for intent matching."""
    return s.strip().lower().rstrip(".!?,")


@dataclass
class PendingChange:
    """A config change awaiting user approval."""

    proposal_id: str
    entry_id: str
    conversation_id: str
    tool_name: str
    proposed_payload: dict
    pre_state: dict | None
    proposed_summary: str
    proposed_diff: str
    created_at: datetime
    ttl: timedelta

    def __post_init__(self) -> None:
        """Validate summary phrasing."""
        normalized = _normalize(self.proposed_summary)
        first_token = normalized.split()[0] if normalized else ""
        if first_token in _PAST_TENSE_TOKENS:
            raise ValueError(
                f"proposed_summary must not start with past-tense token: {first_token!r}"
            )

    def is_expired(self, now: datetime) -> bool:
        """Check if this pending change has expired."""
        return now >= self.created_at + self.ttl


class ApprovalOutcome(Enum):
    """Outcome of processing an approval intent."""

    NOT_INTERCEPTED = "not_intercepted"
    APPLIED = "applied"
    REJECTED = "rejected"
    UNDONE = "undone"
    NO_PENDING_CHANGE = "no_pending_change"
    EXPIRED = "expired"
    AMBIGUOUS = "ambiguous"


@dataclass
class ApprovalOutcomeResult:
    """Result of handling an approval intent."""

    outcome: ApprovalOutcome
    intercepted: bool
    user_message: str
    proposal_id: str | None = None
    tool_result: dict | None = None

    def __init__(
        self,
        outcome: ApprovalOutcome,
        user_message: str,
        proposal_id: str | None = None,
        tool_result: dict | None = None,
    ) -> None:
        """Initialize with derived intercepted flag."""
        self.outcome = outcome
        self.intercepted = outcome != ApprovalOutcome.NOT_INTERCEPTED
        self.user_message = user_message
        self.proposal_id = proposal_id
        self.tool_result = tool_result


class PendingChangeManager:
    """Manages pending config changes for a specific (entry_id, conversation_id) scope."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        conversation_id: str,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize manager (use for_entry_conv classmethod instead)."""
        self._hass = hass
        self._entry_id = entry_id
        self._conversation_id = conversation_id
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._just_expired = False

    @classmethod
    def for_entry_conv(
        cls,
        hass: HomeAssistant,
        entry_id: str,
        conversation_id: str,
        now_fn: Callable[[], datetime] | None = None,
    ) -> PendingChangeManager:
        """Construct a manager for the given entry and conversation."""
        # Validate runtime_data exists (will raise if not)
        _get_runtime_data(hass, entry_id)
        return cls(hass, entry_id, conversation_id, now_fn)

    def create(
        self,
        tool_name: str,
        proposed_payload: dict,
        pre_state: dict | None,
        proposed_summary: str,
        proposed_diff: str,
        approval_ttl_seconds: int = 300,
    ) -> PendingChange:
        """Create and store a new pending change (supersedes any existing one)."""
        runtime_data = _get_runtime_data(self._hass, self._entry_id)
        proposal_id = uuid.uuid4().hex
        now = self._now_fn()

        pending = PendingChange(
            proposal_id=proposal_id,
            entry_id=self._entry_id,
            conversation_id=self._conversation_id,
            tool_name=tool_name,
            proposed_payload=proposed_payload,
            pre_state=pre_state,
            proposed_summary=proposed_summary,
            proposed_diff=proposed_diff,
            created_at=now,
            ttl=timedelta(seconds=approval_ttl_seconds),
        )

        # Supersede any existing pending change
        old_pending = runtime_data.pending.get(self._conversation_id)
        if old_pending is not None:
            _LOGGER.debug(
                "Superseding pending proposal %s with %s",
                old_pending.proposal_id,
                proposal_id,
            )

        runtime_data.pending[self._conversation_id] = pending
        return pending

    def get_current(self) -> PendingChange | None:
        """Get the current pending change, evicting if expired."""
        runtime_data = _get_runtime_data(self._hass, self._entry_id)
        pending = runtime_data.pending.get(self._conversation_id)

        if pending is not None and pending.is_expired(self._now_fn()):
            _LOGGER.debug("Evicting expired proposal %s", pending.proposal_id)
            runtime_data.pending[self._conversation_id] = None
            self._just_expired = True
            return None

        return pending

    def evict_expired(self) -> None:
        """Evict expired pending change (side-effect only)."""
        self.get_current()

    def handle_approval_intent(self, message: str) -> ApprovalOutcomeResult:
        """
        Process a user message to detect approval/rejection/undo intents.

        Returns an outcome indicating what action (if any) should be taken.
        Does NOT actually apply changes or manipulate undo stacks.
        """
        # Evict expired first
        self.evict_expired()

        # Normalize message
        normalized = _normalize(message)
        tokens = normalized.split()
        n = len(tokens)
        first_token = tokens[0] if tokens else ""

        current = self.get_current()

        # If there's a pending change
        if current is not None:
            # Check for approval
            if (n <= 5 and first_token in APPROVAL_TOKENS) or normalized in BARE_APPROVAL_UTTERANCES:
                return ApprovalOutcomeResult(
                    outcome=ApprovalOutcome.APPLIED,
                    user_message=f"Applying {current.tool_name}...",
                    proposal_id=current.proposal_id,
                )

            # Check for rejection/cancel
            if n <= 5 and first_token in UNDO_TOKENS:
                self.clear_current()
                return ApprovalOutcomeResult(
                    outcome=ApprovalOutcome.REJECTED,
                    user_message="OK, I've cancelled that proposal.",
                )

            # Not an approval or rejection
            return ApprovalOutcomeResult(
                outcome=ApprovalOutcome.NOT_INTERCEPTED,
                user_message="",
            )

        # No pending change
        # Check if user said "undo" without pending (signal to pop undo stack)
        if normalized in BARE_UNDO_UTTERANCES:
            return ApprovalOutcomeResult(
                outcome=ApprovalOutcome.UNDONE,
                user_message="(interceptor will pop undo stack)",
            )

        # Check if this looks like an approval but we just expired
        if self._just_expired and (
            (n <= 5 and first_token in APPROVAL_TOKENS) or normalized in BARE_APPROVAL_UTTERANCES
        ):
            self._just_expired = False
            return ApprovalOutcomeResult(
                outcome=ApprovalOutcome.EXPIRED,
                user_message="That change expired; please ask again if you still want it.",
            )

        # Normal speech
        return ApprovalOutcomeResult(
            outcome=ApprovalOutcome.NOT_INTERCEPTED,
            user_message="",
        )

    def clear_current(self) -> None:
        """Clear the current pending change."""
        runtime_data = _get_runtime_data(self._hass, self._entry_id)
        runtime_data.pending[self._conversation_id] = None
