"""Camera snapshot helpers for vision input to Bedrock Claude.

Only the Anthropic-on-Bedrock Messages shape is produced here. The image goes
into the last user message's ``content`` array as an ``image`` block with
``source.type = "base64"``. Bedrock accepts ``image/jpeg``, ``image/png``,
``image/gif``, and ``image/webp``.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

from homeassistant.components import camera
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

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


def attach_image_to_last_user_message(
    messages: list[dict[str, Any]],
    image_bytes: bytes,
    content_type: str,
) -> list[dict[str, Any]]:
    """Return a copy of ``messages`` with an image block prepended to the last user message.

    Bedrock's Anthropic Messages shape expects images to come *before* the
    accompanying text in the same ``content`` array, so the image appears as
    the first block and the pre-existing text follows. If ``messages`` has no
    trailing user entry, a new one is appended carrying only the image.
    """
    image_block = {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": content_type,
            "data": base64.b64encode(image_bytes).decode("ascii"),
        },
    }

    if messages and messages[-1].get("role") == "user":
        last = dict(messages[-1])
        existing = list(last.get("content") or [])
        last["content"] = [image_block, *existing]
        return [*messages[:-1], last]

    return [*messages, {"role": "user", "content": [image_block]}]
