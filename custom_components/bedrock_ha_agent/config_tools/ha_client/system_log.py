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


# Per-message content cap (in chars) — keeps voice responses short.
_MSG_CHAR_CAP = 200


def _first_or_str(value: Any) -> str:
    """system_log records' `message` is a list of strings; take the first."""
    if isinstance(value, list):
        return value[0] if value else ""
    return str(value) if value is not None else ""


async def list_entries(
    hass: "HomeAssistant",
    limit: int = 10,
    level_filter: str | None = None,
    logger_contains: str | None = None,
) -> dict[str, Any]:
    """Return a slim list of recent system_log entries.

    Returned entry shape (minimal by design — voice-pipeline friendly):
        {'level': 'ERROR', 'logger': str, 'timestamp': float, 'message': str}

    Verbose fields (`source`, `exception`, `first_occurred`, `count`) are
    dropped; callers can ask for a specific entry later if they need detail.

    Filters:
        level_filter: 'ERROR' | 'WARNING' | 'INFO' (case-insensitive).
        logger_contains: substring match against the logger name.
    """
    from homeassistant.components.system_log import DATA_SYSTEM_LOG

    handler = hass.data.get(DATA_SYSTEM_LOG)
    if handler is None:
        return {"entries": [], "count": 0, "reason": "system_log not loaded"}

    raw = handler.records.to_list()  # reversed LIFO

    if level_filter:
        level_u = level_filter.upper()
        raw = [e for e in raw if e.get("level") == level_u]
    if logger_contains:
        needle = logger_contains.lower()
        raw = [e for e in raw if needle in (e.get("name", "") or "").lower()]

    trimmed: list[dict[str, Any]] = []
    for entry in raw[:limit]:
        message = _first_or_str(entry.get("message"))
        if len(message) > _MSG_CHAR_CAP:
            message = message[:_MSG_CHAR_CAP] + "…"
        trimmed.append({
            "level": entry.get("level"),
            "logger": entry.get("name"),
            "timestamp": entry.get("timestamp"),
            "message": message,
        })
    return {"entries": trimmed, "count": len(trimmed)}


async def clear(hass: "HomeAssistant") -> None:
    """Call system_log.clear service."""
    await hass.services.async_call("system_log", "clear", blocking=True)
