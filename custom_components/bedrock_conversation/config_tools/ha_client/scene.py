"""Scene config transport."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def list_scenes(hass: "HomeAssistant") -> list[dict]:
    """Return the list of UI-managed scenes."""
    raise NotImplementedError


async def get_scene(hass: "HomeAssistant", object_id: str) -> dict | None:
    """Return the stored config for a given scene object_id, or None if absent."""
    raise NotImplementedError


async def create_scene(hass: "HomeAssistant", config: dict) -> str:
    """Create a scene; return the resulting object_id."""
    raise NotImplementedError


async def update_scene(hass: "HomeAssistant", object_id: str, config: dict) -> None:
    """Update a scene config."""
    raise NotImplementedError


async def delete_scene(hass: "HomeAssistant", object_id: str) -> None:
    """DELETE a scene config. Raises KeyError if absent."""
    raise NotImplementedError


async def reload_scenes(hass: "HomeAssistant") -> None:
    """Fire the scene.reload service."""
    await hass.services.async_call("scene", "reload", blocking=True)
