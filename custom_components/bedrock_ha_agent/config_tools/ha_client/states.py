"""Transport for in-memory state reads (no recorder hit)."""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def get_state(hass: "HomeAssistant", entity_id: str) -> dict[str, Any]:
    """Return {'entity_id','state','attributes','last_changed','last_updated','context'} or {'error':'not_found'}."""
    state = hass.states.get(entity_id)
    if state is None:
        return {"error": "not_found", "entity_id": entity_id}

    # S-loose: Strip GPS/SSID from person/device_tracker entities
    attributes = dict(state.attributes)
    redacted_attrs = []
    if entity_id.startswith("person.") or entity_id.startswith("device_tracker."):
        location_keys = {"latitude", "longitude", "gps_accuracy", "elevation", "altitude", "ssid", "mac_address", "ip"}
        for key in location_keys:
            if key in attributes:
                attributes.pop(key)
                redacted_attrs.append(key)

    result = {
        "entity_id": state.entity_id,
        "state": state.state,
        "attributes": attributes,
        "last_changed": state.last_changed.isoformat(),
        "last_updated": state.last_updated.isoformat(),
        "context": {
            "id": state.context.id,
            "parent_id": state.context.parent_id,
            # S8: Strip user_id to prevent user enumeration
        },
    }

    if redacted_attrs:
        result["_redacted_attributes"] = redacted_attrs

    return result


async def list_states(
    hass: "HomeAssistant",
    domain: str | None = None,
    area_id: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Return {'states': [...], 'count': N}. Cap at `limit`."""
    from homeassistant.helpers import entity_registry as er

    all_states = hass.states.async_all()

    # Filter by domain if specified
    if domain:
        all_states = [s for s in all_states if s.domain == domain]

    # Filter by area_id if specified
    if area_id:
        from homeassistant.helpers import device_registry as dr
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)

        # Get entities in the area (both directly and via device)
        entities_in_area = set()
        for entity in ent_reg.entities.values():
            if entity.area_id == area_id:
                entities_in_area.add(entity.entity_id)
            elif entity.device_id:
                device = dev_reg.async_get(entity.device_id)
                if device and device.area_id == area_id:
                    entities_in_area.add(entity.entity_id)

        all_states = [s for s in all_states if s.entity_id in entities_in_area]

    # Cap at limit
    limited = all_states[:limit]

    states = [
        {
            "entity_id": s.entity_id,
            "state": s.state,
            "attributes": dict(s.attributes),
            "last_changed": s.last_changed.isoformat(),
            "last_updated": s.last_updated.isoformat(),
        }
        for s in limited
    ]

    return {"states": states, "count": len(states)}
