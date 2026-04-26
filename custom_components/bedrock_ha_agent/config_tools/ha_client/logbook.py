"""Transport for HA logbook reads.

Verified against: .venv/lib/python3.13/site-packages/homeassistant/components/logbook/processor.py:104
(EventProcessor class) and line 153 (get_events method signature).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_MSG_CHAR_CAP = 160


async def get_events(
    hass: "HomeAssistant",
    entity_id: str | None,
    start: datetime,
    end: datetime,
    max_events: int = 20,
) -> dict[str, Any]:
    """Return a slim list of logbook events.

    Event shape (minimal — voice-pipeline friendly):
        {'when': iso_str, 'name': str, 'message': str, 'state': str|None}

    Other EventProcessor fields (context_user_id, context_entity_id, domain,
    entity_id, icon, etc.) are dropped — they bloat the response without
    helping a voice summary.
    """
    from homeassistant.components.logbook import processor as lb_processor
    from homeassistant.const import EVENT_LOGBOOK_ENTRY, EVENT_STATE_CHANGED

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
    events = await hass.async_add_executor_job(processor.get_events, start, end)

    trimmed: list[dict[str, Any]] = []
    for event in events[:max_events]:
        message = event.get("message") or ""
        if isinstance(message, str) and len(message) > _MSG_CHAR_CAP:
            message = message[:_MSG_CHAR_CAP] + "…"
        trimmed.append({
            "when": event.get("when"),
            "name": event.get("name"),
            "message": message,
            "state": event.get("state"),
        })
    return {"events": trimmed, "count": len(trimmed)}
