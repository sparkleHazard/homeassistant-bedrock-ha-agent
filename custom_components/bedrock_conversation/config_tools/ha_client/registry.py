"""Area / label / entity-registry transport."""
from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def list_areas(hass: "HomeAssistant") -> list[dict]:
    """List all areas."""
    from homeassistant.helpers import area_registry as ar

    registry = ar.async_get(hass)
    return [
        {
            "area_id": a.id,
            "name": a.name,
            "aliases": sorted(a.aliases) if a.aliases else [],
            "icon": a.icon,
            "labels": sorted(a.labels) if a.labels else [],
        }
        for a in registry.async_list_areas()
    ]


async def create_area(hass: "HomeAssistant", name: str, **kwargs: Any) -> str:
    """Create an area; return its area_id."""
    from homeassistant.helpers import area_registry as ar

    registry = ar.async_get(hass)
    area = registry.async_create(name, **kwargs)
    return area.id


async def update_area(hass: "HomeAssistant", area_id: str, **updates: Any) -> None:
    """Update an area."""
    from homeassistant.helpers import area_registry as ar

    registry = ar.async_get(hass)
    registry.async_update(area_id, **updates)


async def delete_area(hass: "HomeAssistant", area_id: str) -> None:
    """Delete an area."""
    from homeassistant.helpers import area_registry as ar

    registry = ar.async_get(hass)
    registry.async_delete(area_id)


async def list_labels(hass: "HomeAssistant") -> list[dict]:
    """List all labels."""
    from homeassistant.helpers import label_registry as lr

    registry = lr.async_get(hass)
    return [
        {
            "label_id": lbl.label_id,
            "name": lbl.name,
            "icon": lbl.icon,
            "color": lbl.color,
        }
        for lbl in registry.async_list_labels()
    ]


async def create_label(hass: "HomeAssistant", name: str, **kwargs: Any) -> str:
    """Create a label; return its label_id."""
    from homeassistant.helpers import label_registry as lr

    registry = lr.async_get(hass)
    label = registry.async_create(name, **kwargs)
    return label.label_id


async def update_label(hass: "HomeAssistant", label_id: str, **updates: Any) -> None:
    """Update a label."""
    from homeassistant.helpers import label_registry as lr

    registry = lr.async_get(hass)
    registry.async_update(label_id, **updates)


async def delete_label(hass: "HomeAssistant", label_id: str) -> None:
    """Delete a label."""
    from homeassistant.helpers import label_registry as lr

    registry = lr.async_get(hass)
    registry.async_delete(label_id)


async def get_entity_registry_entry(
    hass: "HomeAssistant", entity_id: str
) -> dict | None:
    """Get entity registry entry, or None if not registered."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is None:
        return None
    return {
        "entity_id": entry.entity_id,
        "name": entry.name,
        "original_name": entry.original_name,
        "area_id": entry.area_id,
        "labels": sorted(entry.labels) if entry.labels else [],
        "hidden_by": entry.hidden_by.value if entry.hidden_by else None,
        "disabled_by": entry.disabled_by.value if entry.disabled_by else None,
    }


async def update_entity_registry(
    hass: "HomeAssistant", entity_id: str, **updates: Any
) -> dict:
    """Update an entity registry record. Returns the new state dict.

    Caveat: `disabled_by` is WS-restricted to USER origin (see plan §3.c).
    Callers must refuse to disable entities whose current disabled_by is non-USER.
    """
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    registry.async_update_entity(entity_id, **updates)
    return await get_entity_registry_entry(hass, entity_id) or {}


async def can_toggle_disabled_by_user(
    hass: "HomeAssistant", entity_id: str
) -> tuple[bool, str | None]:
    """Read-only helper (for pre-validation). Returns (allowed, reason_if_not)."""
    entry = await get_entity_registry_entry(hass, entity_id)
    if entry is None:
        return False, f"entity {entity_id} not in registry"
    current = entry.get("disabled_by")
    if current is None or current == "user":
        return True, None
    return (
        False,
        f"entity disabled_by={current!r}; only USER-origin disables are toggleable",
    )
