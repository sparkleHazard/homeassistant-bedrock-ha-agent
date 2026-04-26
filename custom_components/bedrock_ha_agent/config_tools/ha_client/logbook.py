"""Transport for HA logbook reads.

Verified against: .venv/lib/python3.13/site-packages/homeassistant/components/logbook/processor.py:104
(EventProcessor class) and line 153 (get_events method signature).
"""
from __future__ import annotations
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def get_events(
    hass: "HomeAssistant",
    entity_id: str | None,
    start: datetime,
    end: datetime,
    max_events: int = 100,
) -> dict[str, Any]:
    """Return {'events': [...], 'count': N} via EventProcessor.get_events.

    Pass a single entity_id (v1 limits to one entity — see plan §M14).
    """
    from homeassistant.components.logbook import processor as lb_processor
    from homeassistant.const import EVENT_LOGBOOK_ENTRY, EVENT_STATE_CHANGED

    # EventProcessor.__init__ requires event_types tuple
    event_types = (EVENT_STATE_CHANGED, EVENT_LOGBOOK_ENTRY)
    entity_ids = [entity_id] if entity_id else None

    processor = lb_processor.EventProcessor(
        hass,
        event_types=event_types,
        entity_ids=entity_ids,
        device_ids=None,
        context_id=None,
        timestamp=True,
        include_entity_name=True,
    )

    # get_events is synchronous but we call it via executor to avoid blocking
    events = await hass.async_add_executor_job(processor.get_events, start, end)

    # Cap at max_events
    limited = events[:max_events]
    return {"events": limited, "count": len(limited)}
