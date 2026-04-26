"""Camera snapshot helpers for vision input to Bedrock Claude.

Only the Anthropic-on-Bedrock Messages shape is produced here. The image goes
into the last user message's ``content`` array as an ``image`` block with
``source.type = "base64"``. Bedrock accepts ``image/jpeg``, ``image/png``,
``image/gif``, and ``image/webp``.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime
from typing import Any

from homeassistant.components import camera
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar, entity_registry as er
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Camera state attributes worth surfacing to the model. Everything else is
# noise (stream URLs, brand codes, polling intervals) — we only want signals
# the model can actually reason about.
_INTERESTING_CAMERA_ATTRS = (
    "motion_detected",
    "person_detected",
    "vehicle_detected",
    "animal_detected",
    "package_detected",
    "recording",
    "is_streaming",
)

_ALLOWED_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp"}
)


async def fetch_camera_snapshot(
    hass: HomeAssistant, entity_id: str
) -> tuple[bytes, str]:
    """Return ``(image_bytes, content_type)`` for ``entity_id``.

    Raises ``HomeAssistantError`` if the camera entity doesn't exist, isn't a
    camera, or returns an unsupported content type.
    """
    if not entity_id.startswith("camera."):
        raise HomeAssistantError(f"{entity_id} is not a camera entity_id")

    try:
        image = await camera.async_get_image(hass, entity_id)
    except HomeAssistantError:
        raise
    except Exception as err:  # noqa: BLE001
        raise HomeAssistantError(
            f"Could not fetch snapshot from {entity_id}: {err}"
        ) from err

    if image.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HomeAssistantError(
            f"Camera {entity_id} returned unsupported image type "
            f"{image.content_type}; Bedrock accepts JPEG/PNG/GIF/WEBP"
        )

    _LOGGER.debug(
        "Fetched %s snapshot: %d bytes, %s",
        entity_id, len(image.content), image.content_type,
    )
    return image.content, image.content_type


def exposed_camera_entity_ids(hass: HomeAssistant) -> list[str]:
    """Return the entity_ids of every ``camera.*`` entity exposed to conversation."""
    out: list[str] = []
    for state in hass.states.async_all():
        if not state.entity_id.startswith("camera."):
            continue
        if not async_should_expose(hass, "conversation", state.entity_id):
            continue
        out.append(state.entity_id)
    return out


def build_camera_metadata(
    hass: HomeAssistant,
    entity_id: str,
    index: int,
    total: int,
) -> str:
    """Build a one-line text label to send alongside a camera snapshot.

    Anthropic recommends labeling images in multi-image prompts so the model
    can refer to them unambiguously. We surface: ordering (image N of M),
    friendly name + area, capture time, and any detection attributes the
    camera exposes.
    """
    parts: list[str] = [f"Image {index} of {total}"]

    state = hass.states.get(entity_id)
    friendly_name = (
        state.attributes.get("friendly_name") if state else None
    ) or entity_id

    # Area lookup: entity -> entity_registry.area_id (falling back to device.area_id)
    # -> area_registry.async_get_area -> name.
    area_name: str | None = None
    try:
        ent_reg = er.async_get(hass)
        area_reg = ar.async_get(hass)
        entry = ent_reg.async_get(entity_id)
        area_id = entry.area_id if entry else None
        if not area_id and entry and entry.device_id:
            from homeassistant.helpers import device_registry as dr

            dev_reg = dr.async_get(hass)
            device = dev_reg.async_get(entry.device_id)
            area_id = device.area_id if device else None
        if area_id:
            area = area_reg.async_get_area(area_id)
            area_name = area.name if area else None
    except Exception:  # noqa: BLE001
        # Registry lookups should never fail the vision turn — metadata
        # is best-effort, the image still gets sent.
        _LOGGER.debug("Area lookup failed for %s", entity_id, exc_info=True)

    if area_name:
        parts.append(f"{friendly_name} ({area_name})")
    else:
        parts.append(str(friendly_name))

    # Capture timestamp in the HA-configured local timezone.
    now_local = dt_util.now()
    if isinstance(now_local, datetime):
        parts.append(f"captured {now_local.strftime('%Y-%m-%d %H:%M %Z').strip()}")

    # Detection attributes: only include ones the entity actually reports.
    if state:
        attr_bits: list[str] = []
        for key in _INTERESTING_CAMERA_ATTRS:
            if key in state.attributes:
                attr_bits.append(f"{key}={state.attributes[key]}")
        if attr_bits:
            parts.append("attributes: " + ", ".join(attr_bits))

    return ". ".join(parts) + "."


def attach_image_to_last_user_message(
    messages: list[dict[str, Any]],
    image_bytes: bytes,
    content_type: str,
    metadata_text: str | None = None,
) -> list[dict[str, Any]]:
    """Return a copy of ``messages`` with an image (and optional label) prepended to the last user message.

    Bedrock's Anthropic Messages shape expects images to come *before* the
    accompanying text in the same ``content`` array, so the image appears
    first and the pre-existing text follows. When ``metadata_text`` is
    provided, a text block carrying that label is emitted immediately
    before the image block — this is Anthropic's recommended shape for
    multi-image prompts where each image needs identification.

    If ``messages`` has no trailing user entry, a new one is appended
    carrying just the label + image.
    """
    image_block = {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": content_type,
            "data": base64.b64encode(image_bytes).decode("ascii"),
        },
    }

    prepend: list[dict[str, Any]] = []
    if metadata_text:
        prepend.append({"type": "text", "text": metadata_text})
    prepend.append(image_block)

    if messages and messages[-1].get("role") == "user":
        last = dict(messages[-1])
        existing = list(last.get("content") or [])
        last["content"] = [*prepend, *existing]
        return [*messages[:-1], last]

    return [*messages, {"role": "user", "content": prepend}]
