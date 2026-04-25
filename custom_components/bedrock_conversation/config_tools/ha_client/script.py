"""Script config transport."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def list_scripts(hass: "HomeAssistant") -> list[dict]:
    """Return the list of UI-managed scripts."""
    raise NotImplementedError


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
