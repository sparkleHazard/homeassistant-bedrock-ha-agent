"""Script config transport. Uses HA's /api/config/script/config/<id> HTTP API.

The file I/O happens inside HA's script config component, not in our code.
We call the HTTP endpoint via hass.http or the internal view.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def list_scripts(hass: "HomeAssistant") -> list[dict]:
    """Return the list of UI-managed scripts.

    Uses the same data source as the /api/config/script/config endpoint.
    """
    raise NotImplementedError("Implement via HA's internal API; see docstring")


async def get_script(hass: "HomeAssistant", object_id: str) -> dict | None:
    """Return the stored config for a given script object_id, or None if absent."""
    raise NotImplementedError


async def create_or_update_script(
    hass: "HomeAssistant", object_id: str, config: dict
) -> None:
    """POST a script config; creates if absent, updates in place if present."""
    raise NotImplementedError


async def delete_script(hass: "HomeAssistant", object_id: str) -> None:
    """DELETE a script config. Raises KeyError if absent."""
    raise NotImplementedError


async def reload_scripts(hass: "HomeAssistant") -> None:
    """Fire the script.reload service."""
    await hass.services.async_call("script", "reload", blocking=True)
