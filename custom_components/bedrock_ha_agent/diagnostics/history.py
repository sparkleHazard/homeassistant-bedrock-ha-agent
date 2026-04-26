"""Read-only diagnostic tools: state history and statistics.

Verified against:
- .venv/lib/python3.13/site-packages/homeassistant/components/recorder/statistics.py:308
  (statistics_during_period signature)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.helpers import config_validation as cv, llm

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from ..const import (
    CONF_DIAGNOSTICS_HISTORY_MAX_HOURS,
    DEFAULT_DIAGNOSTICS_HISTORY_MAX_HOURS,
)
from .base import DiagnosticsReadTool

_LOGGER = logging.getLogger(__name__)


class DiagnosticsStateHistory(DiagnosticsReadTool):
    """Read significant-state history for a single entity over a time window."""

    name = "DiagnosticsStateHistory"
    description = "Read significant-state history for a single entity over a time window."
    parameters = vol.Schema({
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("hours_back", default=24): vol.All(int, vol.Range(min=1, max=168)),
    })

    async def _fetch(self, hass: HomeAssistant, **kwargs: Any) -> dict[str, Any]:
        """Fetch state history."""
        from ..config_tools.ha_client import history as hist

        hours_max = self.entry.options.get(
            CONF_DIAGNOSTICS_HISTORY_MAX_HOURS, DEFAULT_DIAGNOSTICS_HISTORY_MAX_HOURS
        )
        hours = min(kwargs.get("hours_back", 24), hours_max)
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        return await hist.significant_states(hass, kwargs["entity_id"], start, end)


class DiagnosticsStatistics(DiagnosticsReadTool):
    """Read long-term statistics for a statistics-enabled entity.

    Verified against:
    .venv/lib/python3.13/site-packages/homeassistant/components/recorder/statistics.py:308
    Signature: statistics_during_period(hass, start_time, end_time, statistic_ids, period, units, types)
    """

    name = "DiagnosticsStatistics"
    description = "Read long-term statistics (hourly means/min/max/sum) for a statistics-enabled entity. Use for sensor trend questions."
    parameters = vol.Schema({
        vol.Required("statistic_id"): cv.string,
        vol.Optional("hours_back", default=24): vol.All(int, vol.Range(min=1, max=720)),
    })

    async def _fetch(self, hass: HomeAssistant, **kwargs: Any) -> dict[str, Any]:
        """Fetch statistics."""
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistics_during_period

        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=kwargs.get("hours_back", 24))
        statistic_id = kwargs["statistic_id"]

        try:
            # HA 2025.6 signature: statistics_during_period(hass, start, end, statistic_ids, period, units, types)
            stats = await get_instance(hass).async_add_executor_job(
                statistics_during_period,
                hass,
                start,
                end,
                {statistic_id},  # statistic_ids: set[str] | None
                "hour",          # period: Literal["5minute", "day", "hour", "week", "month"]
                None,            # units: dict[str, str] | None
                {"mean", "min", "max", "sum"},  # types: set[Literal[...]]
            )
            result = stats.get(statistic_id, [])
            return {
                "statistic_id": statistic_id,
                "stats": result,
                "count": len(result),
            }
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Statistics fetch failed for %s", statistic_id)
            return {"error": "statistics_unavailable", "reason": str(err)[:200]}


def get_tools(hass: "HomeAssistant", entry: "ConfigEntry") -> list[llm.Tool]:
    """Return the diagnostic tools provided by this module."""
    return [
        DiagnosticsStateHistory(hass, entry),
        DiagnosticsStatistics(hass, entry),
    ]
