"""Transport for HA system_log reads.

Verified against: .venv/lib/python3.13/site-packages/homeassistant/components/system_log/__init__.py:263
(LogErrorHandler class) and line 276 (records: DedupStore attribute).
"""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def list_entries(hass: "HomeAssistant", limit: int = 50) -> dict[str, Any]:
    """Return {'entries': [...], 'count': N} with at most `limit` entries, most recent first.

    entry shape: {'level': 'ERROR'|'WARNING'|..., 'timestamp': iso_str, 'logger': str, 'message': str, 'source': str}
    """
    from homeassistant.components.system_log import DATA_SYSTEM_LOG

    handler = hass.data.get(DATA_SYSTEM_LOG)
    if handler is None:
        return {"entries": [], "count": 0, "reason": "system_log not loaded"}

    # handler.records is a DedupStore with .to_list() method (returns reversed LIFO list)
    entries = handler.records.to_list()
    limited = entries[:limit]
    return {"entries": limited, "count": len(limited)}


async def clear(hass: "HomeAssistant") -> None:
    """Call system_log.clear service."""
    await hass.services.async_call("system_log", "clear", blocking=True)
