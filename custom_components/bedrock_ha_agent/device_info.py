"""Exposed-entity enumeration and attribute formatting for the system prompt.

Split out of ``bedrock_client.py`` so the Bedrock client itself stays focused
on AWS I/O. The system-prompt generator calls ``get_exposed_devices`` to
produce the device list that Jinja renders into ``<devices>``.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import area_registry as ar, entity_registry as er

from .utils import closest_color

if TYPE_CHECKING:
    _FormatFn = Callable[[object], str | None]


@dataclass
class DeviceInfo:
    """Serialisable summary of one exposed entity."""

    entity_id: str
    name: str
    state: str
    attributes: list[str]
    area_id: str | None = None
    area_name: str | None = None


# (attribute-name, domain-restriction-or-None, formatter).
# formatter(raw) -> str | None; returning None skips the attribute.
def _brightness(raw: object) -> str | None:
    if raw is None:
        return None
    # raw is typically an int (0-255), but cast defensively
    return f"{int(float(raw) * 100 / 255)}%"  # type: ignore[arg-type]


def _rgb(raw: object) -> str | None:
    if not raw:
        return None
    try:
        # raw should be a sequence like [255, 0, 0]; cast to tuple for closest_color
        if not isinstance(raw, (list, tuple)) or len(raw) < 3:
            return None
        return closest_color((int(raw[0]), int(raw[1]), int(raw[2])))
    except Exception:  # noqa: BLE001 — bad data → skip, not fatal
        return None


def _temperature(raw: object) -> str | None:
    return None if raw is None else f"{raw}°"


def _temperature_with_prefix(prefix: str) -> _FormatFn:
    def fmt(raw: object) -> str | None:
        return None if raw is None else f"{prefix}:{raw}°"

    return fmt


def _humidity(raw: object) -> str | None:
    return None if raw is None else f"{raw}%RH"


def _labelled(label: str) -> _FormatFn:
    def fmt(raw: object) -> str | None:
        return None if not raw else f"{label}:{raw}"

    return fmt


def _volume(raw: object) -> str | None:
    return None if raw is None else f"vol:{int(float(raw) * 100)}%"  # type: ignore[arg-type]


# (state attribute key, domain filter, formatter).
# Using a table keeps the dispatch declarative and makes it trivial to add
# new attributes later.
_ATTRIBUTE_FORMATTERS: tuple[tuple[str, str | None, _FormatFn], ...] = (
    ("brightness", "light", _brightness),
    ("rgb_color", "light", _rgb),
    ("temperature", None, _temperature),
    ("current_temperature", None, _temperature_with_prefix("current")),
    ("target_temperature", None, _temperature_with_prefix("target")),
    ("humidity", None, _humidity),
    ("fan_mode", None, _labelled("fan")),
    ("hvac_mode", None, _labelled("hvac")),
    ("hvac_action", None, _labelled("action")),
    ("preset_mode", None, _labelled("preset")),
    ("media_title", None, _labelled("playing")),
    ("media_artist", None, _labelled("artist")),
    ("volume_level", None, _volume),
)


def render_devices_section(
    devices: list["DeviceInfo"],
    *,
    mode: str = "full",
    max_tokens: int = 0,
) -> str:
    """Render a plain-text device list for the system prompt.

    Used when ``CONF_DEVICE_PROMPT_MODE`` is not ``full`` (the full mode
    still goes through the Jinja ``DEVICES_PROMPT`` template to preserve the
    pre-existing format). Modes trade token cost vs. fidelity:

    - ``full``:        (template-driven, not handled here)
    - ``compact``:     "[area] name (entity_id): state"
    - ``names_only``:  "[area] name (entity_id)"

    ``max_tokens`` is a soft cap: once the running char-count exceeds roughly
    ``max_tokens * 4`` we stop and append "(+N more)" so the model knows
    something was elided. ``0`` disables the cap.
    """
    if not devices:
        return "The user has no exposed devices."

    lines: list[str] = ["The user has the following devices:", ""]
    char_budget = max_tokens * 4 if max_tokens > 0 else None
    used = sum(len(line) + 1 for line in lines)
    emitted = 0

    for device in devices:
        prefix = f"[{device.area_name}] " if device.area_name else ""
        if mode == "names_only":
            line = f"{prefix}{device.name} ({device.entity_id})"
        else:  # compact
            line = f"{prefix}{device.name} ({device.entity_id}): {device.state}"

        if char_budget is not None and used + len(line) + 1 > char_budget:
            remaining = len(devices) - emitted
            lines.append(f"(+{remaining} more devices omitted to stay under the prompt cap)")
            break

        lines.append(line)
        used += len(line) + 1
        emitted += 1

    return "\n".join(lines)


def _format_state_attributes(state: State, allowed: list[str]) -> list[str]:
    """Return the subset of ``state.attributes`` the system prompt should show.

    ``allowed`` is the user-configured ``CONF_EXTRA_ATTRIBUTES_TO_EXPOSE``
    list. Only attributes listed there are emitted, and only for domains the
    formatter applies to.
    """
    out: list[str] = []
    for attr_key, domain_filter, formatter in _ATTRIBUTE_FORMATTERS:
        if attr_key not in allowed:
            continue
        if domain_filter is not None and state.domain != domain_filter:
            continue
        formatted = formatter(state.attributes.get(attr_key))
        if formatted is not None:
            out.append(formatted)
    return out


def get_exposed_devices(
    hass: HomeAssistant,
    extra_attributes: list[str],
    *,
    area_filter: list[str] | None = None,
) -> list[DeviceInfo]:
    """Enumerate entities exposed to the ``conversation`` context.

    ``extra_attributes`` is the user-configured attribute allow-list —
    typically ``CONF_EXTRA_ATTRIBUTES_TO_EXPOSE`` from the config entry.

    ``area_filter`` is an optional list of area ids. When non-empty, only
    entities whose entity-registry ``area_id`` is in that list are returned —
    a straightforward token-cost lever for installs with many rooms.
    """
    entity_registry = er.async_get(hass)
    area_registry = ar.async_get(hass)
    area_filter_set = set(area_filter) if area_filter else None

    devices: list[DeviceInfo] = []
    for state in hass.states.async_all():
        if not async_should_expose(hass, "conversation", state.entity_id):
            continue

        entity_entry = entity_registry.async_get(state.entity_id)
        area_id = entity_entry.area_id if entity_entry else None

        if area_filter_set is not None and area_id not in area_filter_set:
            continue

        area_name = None
        if area_id:
            area = area_registry.async_get_area(area_id)
            area_name = area.name if area else None

        devices.append(
            DeviceInfo(
                entity_id=state.entity_id,
                name=state.attributes.get("friendly_name", state.entity_id),
                state=state.state,
                area_id=area_id,
                area_name=area_name,
                attributes=_format_state_attributes(state, extra_attributes),
            )
        )

    return devices
