"""Read-only diagnostic tools: state reads and integration list.

Verified against HA 2025.6 sources.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.helpers import config_validation as cv, llm

from .base import DiagnosticsReadTool

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


class DiagnosticsStateRead(DiagnosticsReadTool):
    """Read the current state and attributes of a single HA entity."""

    name = "DiagnosticsStateRead"
    description = "Read the current state and attributes of a single HA entity."
    parameters = vol.Schema({vol.Required("entity_id"): cv.entity_id})

    async def _fetch(self, hass: HomeAssistant, **kwargs: Any) -> dict[str, Any]:
        """Fetch entity state."""
        from ..config_tools.ha_client import states

        return await states.get_state(hass, kwargs["entity_id"])


class DiagnosticsIntegrationList(DiagnosticsReadTool):
    """List loaded integrations and their config entries."""

    name = "DiagnosticsIntegrationList"
    description = "List loaded integrations and their config entries, with state (loaded/not_loaded/setup_error)."
    parameters = vol.Schema({})

    async def _fetch(self, hass: HomeAssistant, **kwargs: Any) -> dict[str, Any]:
        """Fetch integrations list."""
        entries = hass.config_entries.async_entries()
        return {
            "integrations": [
                {
                    "entry_id": e.entry_id,
                    "domain": e.domain,
                    "title": e.title,
                    "state": e.state.value,
                    "disabled_by": str(e.disabled_by) if e.disabled_by else None,
                }
                for e in entries
            ],
            "count": len(entries),
        }


def get_tools(hass: "HomeAssistant", entry: "ConfigEntry") -> list[llm.Tool]:
    """Return the diagnostic tools provided by this module."""
    return [
        DiagnosticsStateRead(hass, entry),
        DiagnosticsIntegrationList(hass, entry),
    ]
