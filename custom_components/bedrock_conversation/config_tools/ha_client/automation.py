"""Automation config transport. Uses HA's /api/config/automation/config/<id> HTTP API.

The file I/O happens inside HA's automation config component, not in our code.
We call the HTTP endpoint via hass.http or the internal view.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def list_automations(hass: "HomeAssistant") -> list[dict]:
    """Return the list of UI-managed automations.

    Uses the same data source as the /api/config/automation/config endpoint.
    """
    raise NotImplementedError("Implement via HA's internal API; see docstring")


async def get_automation(hass: "HomeAssistant", object_id: str) -> dict | None:
    """Return the stored config for a given automation object_id, or None if absent."""
    raise NotImplementedError


async def create_or_update_automation(
    hass: "HomeAssistant", object_id: str, config: dict
) -> None:
    """POST an automation config; creates if absent, updates in place if present."""
    raise NotImplementedError


async def delete_automation(hass: "HomeAssistant", object_id: str) -> None:
    """DELETE an automation config. Raises KeyError if absent."""
    raise NotImplementedError


async def reload_automations(hass: "HomeAssistant") -> None:
    """Fire the automation.reload service."""
    await hass.services.async_call("automation", "reload", blocking=True)
