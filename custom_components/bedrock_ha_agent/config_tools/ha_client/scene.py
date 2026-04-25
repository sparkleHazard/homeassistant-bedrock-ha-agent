"""Scene config transport."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def list_scenes(hass: "HomeAssistant") -> list[dict]:
    """Return the list of UI-managed scenes.

    Uses the same data source as the /api/config/scene/config endpoint.
    """
    raise NotImplementedError("TODO: HA 2026.2 storage path")


async def get_scene(hass: "HomeAssistant", object_id: str) -> dict | None:
    """Return the stored config for a given scene object_id, or None if absent."""
    raise NotImplementedError("TODO: HA 2026.2 storage path")


async def create_or_update_scene(
    hass: "HomeAssistant", object_id: str, config: dict
) -> None:
    """POST a scene config; creates if absent, updates in place if present."""
    raise NotImplementedError("TODO: HA 2026.2 storage path")


async def delete_scene(hass: "HomeAssistant", object_id: str) -> None:
    """DELETE a scene config. Raises KeyError if absent."""
    raise NotImplementedError("TODO: HA 2026.2 storage path")


async def reload_scenes(hass: "HomeAssistant") -> None:
    """Fire the scene.reload service."""
    await hass.services.async_call("scene", "reload", blocking=True)
