"""Per-entry mutable state typed as a dataclass. Populated in async_setup_entry (Phase 3)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .bedrock_client import BedrockClient
    from .config_tools.pending import PendingChange
    from .config_tools.undo import UndoStack
    from .usage_tracker import UsageTracker


@dataclass
class BedrockRuntimeData:
    """Runtime data for bedrock_ha_agent integration."""

    pending: dict[str, "PendingChange | None"] = field(default_factory=dict)  # keyed by conversation_id
    undo: dict[str, "UndoStack"] = field(default_factory=dict)  # keyed by conversation_id
    last_config_editing_flag: bool = False
    last_model_warned_for: str | None = None
    lovelace_mode: str | None = None
    bedrock_client: "BedrockClient | None" = None
    usage: "UsageTracker | None" = None
    # per-turn diagnostic tool-call budget tracker, keyed by (conversation_id, bedrock_turn_id)
    # value is the count of diagnostic tool calls consumed so far in that turn
    diagnostics_turn_counts: dict[tuple[str, str], int] = field(default_factory=dict)
    # transition bookkeeping for CONF_ENABLE_DIAGNOSTICS (matches last_config_editing_flag pattern)
    last_diagnostics_flag: bool = False
    # AWS access_key_id snapshot captured at async_setup_entry, used by the
    # update listener to detect credential changes and flush the shared
    # aws_cache before reload. None means "not yet initialised".
    last_access_key_id: str | None = None


def _get_runtime_data(hass: "HomeAssistant", entry_id: str) -> BedrockRuntimeData:
    """Retrieve runtime data for a bedrock_ha_agent config entry."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise RuntimeError(f"bedrock_ha_agent entry not found: {entry_id}")
    rd = getattr(entry, "runtime_data", None)
    if not isinstance(rd, BedrockRuntimeData):
        raise RuntimeError(
            f"bedrock_ha_agent runtime_data missing for entry {entry_id}; "
            "Phase 3 setup may not have run"
        )
    return rd
