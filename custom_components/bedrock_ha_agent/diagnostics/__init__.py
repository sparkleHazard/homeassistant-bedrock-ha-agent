"""Diagnostics tools (gated by CONF_ENABLE_DIAGNOSTICS)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.helpers import llm

from ..const import CONF_ENABLE_DIAGNOSTICS, DIAGNOSTICS_TOOL_NAMES

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


_LOGGER = logging.getLogger(__name__)


def get_tools(hass: HomeAssistant, entry: ConfigEntry) -> list[llm.Tool]:
    """Return the list of diagnostics tools for a config entry.

    Returns an empty list when CONF_ENABLE_DIAGNOSTICS is False (kill switch).
    """
    if not entry.options.get(CONF_ENABLE_DIAGNOSTICS, False):
        return []

    # Phase 2 subclasses are imported lazily here. For Phase 1, this function returns
    # an empty list even when the flag is True — the real tool classes arrive in Phase 2.
    tools: list[llm.Tool] = []
    try:
        # Phase 2 will fill these in.
        from . import history as _history
        from . import lifecycle as _lifecycle
        from . import logs as _logs
        from . import services as _services
        from . import states as _states

        for module in (_logs, _states, _history, _services, _lifecycle):
            register_fn = getattr(module, "get_tools", None)
            if callable(register_fn):
                tools.extend(register_fn(hass, entry))

        # Validate exported class names match DIAGNOSTICS_TOOL_NAMES
        exported_names = {tool.__class__.__name__ for tool in tools}
        if exported_names != DIAGNOSTICS_TOOL_NAMES:
            missing = DIAGNOSTICS_TOOL_NAMES - exported_names
            extra = exported_names - DIAGNOSTICS_TOOL_NAMES
            raise RuntimeError(
                f"diagnostics tool name mismatch: missing={missing}, extra={extra}"
            )
    except ImportError:
        # Phase 2 not yet landed; that's fine — flag-on with no tools is a valid state.
        _LOGGER.warning(
            "CONF_ENABLE_DIAGNOSTICS is True but diagnostics tool modules not found; "
            "returning empty tool list"
        )
    return tools
