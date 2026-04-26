"""Transport for system-health component (integration self-reports).

Verified against: .venv/lib/python3.13/site-packages/homeassistant/components/system_health/__init__.py:27
(DOMAIN constant) and line 107 (hass.data[DOMAIN] is dict[str, SystemHealthRegistration]).
Also line 121 (get_info function returns dict[str, dict[str, Any]]).
"""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def system_info(hass: "HomeAssistant") -> dict[str, Any]:
    """Return {'integrations': {domain: {'info_dict': ...}}, 'ha_version': str, ...}.

    Use homeassistant.components.system_health.get_info if possible.
    If system_health isn't loaded, return {'error':'system_health_not_loaded'}.
    """
    from homeassistant.components.system_health import DOMAIN

    if DOMAIN not in hass.data:
        return {"error": "system_health_not_loaded"}

    # Use the system_health.get_info helper
    from homeassistant.components.system_health import get_info

    try:
        info = await get_info(hass)
        return {
            "integrations": info,
            "ha_version": hass.config.version,
            "count": len(info),
        }
    except Exception as err:
        _LOGGER.exception("Failed to retrieve system_health info")
        return {"error": f"system_health_error: {err}"}
