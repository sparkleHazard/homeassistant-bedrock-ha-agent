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


async def system_info(
    hass: "HomeAssistant",
    domain: str | None = None,
) -> dict[str, Any]:
    """Return a slim system-health summary.

    Default response (voice-pipeline friendly — no domain filter):
        {
          'ha_version': str,
          'integration_count': int,
          'ok_count': int,
          'errors': {domain: first_error_message},  # only integrations reporting an error
        }

    When a `domain` is provided, returns the full info_dict for that one
    integration (for follow-up detail after a summary):
        {'ha_version': str, 'domain': str, 'info': {...}}

    Drops the bulk per-integration info_dicts by default — they can be
    paragraphs of text per integration.
    """
    from homeassistant.components.system_health import DOMAIN, get_info

    if DOMAIN not in hass.data:
        return {"error": "system_health_not_loaded"}

    try:
        info = await get_info(hass)
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Failed to retrieve system_health info")
        return {"error": f"system_health_error: {err}"}

    if domain:
        return {
            "ha_version": hass.config.version,  # type: ignore[attr-defined]  # version exists at runtime
            "domain": domain,
            "info": info.get(domain, {"error": "not_reported"}),
        }

    errors: dict[str, str] = {}
    ok_count = 0
    for d, info_dict in info.items():
        if not info_dict:
            continue
        inner = info_dict.get("info", info_dict) if isinstance(info_dict, dict) else {}
        error_val = inner.get("error") if isinstance(inner, dict) else None
        if error_val:
            msg = str(error_val)
            errors[d] = msg[:140] + ("…" if len(msg) > 140 else "")
        else:
            ok_count += 1

    return {
        "ha_version": hass.config.version,  # type: ignore[attr-defined]  # version exists at runtime
        "integration_count": len(info),
        "ok_count": ok_count,
        "errors": errors,
    }
