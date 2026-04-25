"""Sensor platform: Bedrock token usage + estimated cost.

Surfaces five sensors per config entry:
  - input tokens (today)
  - output tokens (today)
  - cached tokens (today)   -- cache_read + cache_write
  - estimated cost USD (today)
  - estimated cost USD (total since reload)

Counters live on ``entry.runtime_data["usage"]`` (a ``UsageTracker``) and
update whenever ``bedrock_client.async_generate`` records a response. The
sensors subscribe to the tracker so state refreshes are push, not polled.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_DOLLAR
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .usage_tracker import UsageCounters, UsageTracker


@dataclass(frozen=True)
class _SensorSpec:
    key: str
    name: str
    unit: str | None
    device_class: SensorDeviceClass | None
    getter: Callable[[UsageTracker], float | int | str | datetime | None]
    suggested_precision: int | None = None
    state_class: SensorStateClass | None = SensorStateClass.TOTAL


_SENSORS: tuple[_SensorSpec, ...] = (
    _SensorSpec(
        key="input_tokens_today",
        name="Input tokens today",
        unit="tokens",
        device_class=None,
        getter=lambda t: t.today.input_tokens,
    ),
    _SensorSpec(
        key="output_tokens_today",
        name="Output tokens today",
        unit="tokens",
        device_class=None,
        getter=lambda t: t.today.output_tokens,
    ),
    _SensorSpec(
        key="cached_tokens_today",
        name="Cached tokens today",
        unit="tokens",
        device_class=None,
        getter=lambda t: t.today.cache_read_tokens + t.today.cache_write_tokens,
    ),
    _SensorSpec(
        key="cost_today",
        name="Estimated cost today",
        unit=CURRENCY_DOLLAR,
        device_class=SensorDeviceClass.MONETARY,
        getter=lambda t: round(t.today.cost_usd, 4),
        suggested_precision=4,
    ),
    _SensorSpec(
        key="cost_total",
        name="Estimated cost (total)",
        unit=CURRENCY_DOLLAR,
        device_class=SensorDeviceClass.MONETARY,
        getter=lambda t: round(t.total.cost_usd, 4),
        suggested_precision=4,
    ),
    _SensorSpec(
        key="last_success_at",
        name="Last successful request",
        unit=None,
        device_class=SensorDeviceClass.TIMESTAMP,
        getter=lambda t: t.last_success_at,
        state_class=None,
    ),
    _SensorSpec(
        key="last_error",
        name="Last error",
        unit=None,
        device_class=None,
        # HA's state is capped at 255 chars — trim long Bedrock messages.
        getter=lambda t: (t.last_error or "")[:250] or "none",
        state_class=None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Bedrock usage sensors from a config entry."""
    tracker: UsageTracker | None = (entry.runtime_data or {}).get("usage")
    if tracker is None:
        return
    async_add_entities(
        BedrockUsageSensor(entry, tracker, spec) for spec in _SENSORS
    )


class BedrockUsageSensor(SensorEntity):
    """One column of the UsageTracker surfaced as an HA sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        tracker: UsageTracker,
        spec: _SensorSpec,
    ) -> None:
        self._entry = entry
        self._tracker = tracker
        self._spec = spec
        self._attr_unique_id = f"{entry.entry_id}_{spec.key}"
        self._attr_name = spec.name
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_device_class = spec.device_class
        if spec.state_class is not None:
            self._attr_state_class = spec.state_class
        if spec.suggested_precision is not None:
            self._attr_suggested_display_precision = spec.suggested_precision

    async def async_added_to_hass(self) -> None:
        """Subscribe to tracker updates so we re-render on record()."""
        await super().async_added_to_hass()
        self.async_on_remove(self._tracker.add_listener(self._handle_update))

    @property
    def native_value(self):
        return self._spec.getter(self._tracker)

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
