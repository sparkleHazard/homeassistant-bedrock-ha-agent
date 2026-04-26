"""Transport for HA history (significant states).

Verified against: .venv/lib/python3.13/site-packages/homeassistant/components/history/__init__.py:14
(imports history from recorder) and .venv/.../homeassistant/components/recorder/history.py for
get_significant_states_with_session function.
"""
from __future__ import annotations
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def significant_states(
    hass: "HomeAssistant",
    entity_id: str,
    start: datetime,
    end: datetime | None = None,
    minimal_response: bool = True,
) -> dict[str, Any]:
    """Return {'states': [...], 'count': N}."""
    from homeassistant.components.recorder import history
    from homeassistant.components.recorder.util import session_scope  # type: ignore[attr-defined]  # not in __all__ but exists

    def _get_states() -> list[dict[str, Any]]:
        with session_scope(hass=hass, read_only=True) as session:
            result = history.get_significant_states_with_session(
                hass,
                session,
                start,
                end,
                entity_ids=[entity_id],
                filters=None,
                include_start_time_state=True,
                significant_changes_only=True,
                minimal_response=minimal_response,
                no_attributes=False,
            )
            # result is dict[str, list[State]]; extract our entity's states
            states_list = result.get(entity_id, [])
            return [
                {
                    "entity_id": s.entity_id if hasattr(s, "entity_id") else str(s.get("entity_id", "")),
                    "state": s.state if hasattr(s, "state") else str(s.get("state", "")),
                    "attributes": s.attributes if hasattr(s, "attributes") else s.get("attributes", {}),
                    "last_changed": s.last_changed.isoformat() if hasattr(s, "last_changed") else str(s.get("last_changed", "")),
                    "last_updated": s.last_updated.isoformat() if hasattr(s, "last_updated") else str(s.get("last_updated", "")),
                }
                for s in states_list
            ]

    states = await hass.async_add_executor_job(_get_states)
    return {"states": states, "count": len(states)}
