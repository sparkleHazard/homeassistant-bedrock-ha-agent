"""Lovelace dashboards + cards transport via WebSocket commands.

Commands used (verified in plan §3.b against installed HA):
  - lovelace/dashboards            (list; NOT /list)
  - lovelace/config                (get)
  - lovelace/config/save           (full-config replace; rejected for YAML-mode)
  - lovelace/dashboards/create
  - lovelace/dashboards/update
  - lovelace/dashboards/delete
"""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


_LOGGER = logging.getLogger(__name__)


async def list_dashboards(hass: "HomeAssistant") -> list[dict]:
    """Return the list of registered dashboards: [{'url_path', 'mode', 'title', ...}, ...].

    Mirrors the `lovelace/dashboards` WS command. We look up the lovelace component's
    internal dashboards dict directly rather than round-tripping through WS.
    """
    from homeassistant.components.lovelace import DOMAIN as LOVELACE_DOMAIN

    data = hass.data.get(LOVELACE_DOMAIN)
    if data is None:
        return []

    # Modern HA (2024+): data is a dataclass with `.dashboards` dict.
    dashboards = getattr(data, "dashboards", None)
    if dashboards is None:
        # Older HA: try dict access
        dashboards = data.get("dashboards") if isinstance(data, dict) else None
    if dashboards is None:
        return []

    result: list[dict] = []
    for url_path, dashboard in dashboards.items():
        mode = getattr(dashboard, "mode", None) or "storage"
        title = getattr(dashboard, "config", None)
        title_str = ""
        if isinstance(title, dict):
            title_str = title.get("title", "") or ""
        result.append({
            "url_path": url_path,
            "mode": mode,
            "title": title_str,
        })
    return result


async def get_dashboard_mode(hass: "HomeAssistant", url_path: str | None) -> str | None:
    """Return the mode ('storage' or 'yaml') for a dashboard, or None if unknown.

    `url_path=None` means the default dashboard (Overview).
    """
    dashboards = await list_dashboards(hass)
    for d in dashboards:
        if d["url_path"] == url_path:
            return d["mode"]
    # Default dashboard path: may not appear in the list. Fall back to the lovelace
    # component's global mode flag.
    from homeassistant.components.lovelace import DOMAIN as LOVELACE_DOMAIN

    data = hass.data.get(LOVELACE_DOMAIN)
    global_mode = getattr(data, "mode", None) if data is not None else None
    return global_mode


async def load_dashboard(hass: "HomeAssistant", url_path: str | None) -> dict:
    """Return the full stored config for a dashboard."""
    raise NotImplementedError


async def save_dashboard(
    hass: "HomeAssistant", url_path: str | None, config: dict
) -> None:
    """Replace the stored config. Rejected by HA on YAML-mode dashboards.

    Callers MUST check get_dashboard_mode() first and refuse YAML-mode via
    validation_failed before reaching this function (AC18).
    """
    raise NotImplementedError


async def create_dashboard(hass: "HomeAssistant", payload: dict) -> str:
    """Create a dashboard; return its url_path."""
    raise NotImplementedError


async def update_dashboard(hass: "HomeAssistant", url_path: str, payload: dict) -> None:
    """Update a dashboard."""
    raise NotImplementedError


async def delete_dashboard(hass: "HomeAssistant", url_path: str) -> None:
    """Delete a dashboard."""
    raise NotImplementedError
