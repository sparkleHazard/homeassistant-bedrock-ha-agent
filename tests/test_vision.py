"""Tests for vision.py — metadata builder and image attach shape."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.bedrock_ha_agent.vision import (
    attach_image_to_last_user_message,
    build_camera_metadata,
)

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture
def hass_with_camera_state(hass):
    """hass with a camera state carrying friendly_name + detection attrs."""
    hass.states.async_set(
        "camera.front_door",
        "idle",
        {
            "friendly_name": "Front Door",
            "motion_detected": True,
            "person_detected": False,
            "recording": False,
            "stream_source": "rtsp://ignored",  # should be filtered out
        },
    )
    return hass


async def test_build_camera_metadata_includes_index_and_name(
    hass_with_camera_state,
):
    """Basic shape: `Image N of M. <friendly name>. captured ... . attributes: ...`."""
    text = build_camera_metadata(
        hass_with_camera_state, "camera.front_door", index=1, total=2
    )
    assert text.startswith("Image 1 of 2. ")
    assert "Front Door" in text
    assert "captured " in text
    assert "motion_detected=True" in text
    assert "person_detected=False" in text
    # Non-interesting attrs must be filtered out.
    assert "stream_source" not in text


async def test_build_camera_metadata_fallback_to_entity_id(hass):
    """No state → fall back to entity_id, no attribute section."""
    text = build_camera_metadata(hass, "camera.ghost", index=1, total=1)
    assert "camera.ghost" in text
    assert "attributes:" not in text


async def test_build_camera_metadata_includes_area(hass):
    """Entity registered under an area surfaces the area name."""
    from homeassistant.helpers import (
        area_registry as ar,
        entity_registry as er,
    )

    ar.async_get(hass).async_create("Entryway")
    area = ar.async_get(hass).async_get_area_by_name("Entryway")
    assert area is not None

    er.async_get(hass).async_get_or_create(
        "camera", "demo", "front_door_unique", suggested_object_id="front_door"
    )
    er.async_get(hass).async_update_entity(
        "camera.front_door", area_id=area.id
    )
    hass.states.async_set(
        "camera.front_door", "idle", {"friendly_name": "Front Door"}
    )

    text = build_camera_metadata(hass, "camera.front_door", index=1, total=1)
    assert "Front Door (Entryway)" in text


def test_attach_image_prepends_label_and_image_block():
    """Text label must appear before the image block in the content array."""
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"type": "text", "text": "What do you see?"}]}
    ]
    out = attach_image_to_last_user_message(
        messages, b"fakebytes", "image/jpeg", metadata_text="Image 1 of 1. Front Door."
    )
    content = out[-1]["content"]
    assert content[0] == {"type": "text", "text": "Image 1 of 1. Front Door."}
    assert content[1]["type"] == "image"
    assert content[1]["source"]["media_type"] == "image/jpeg"
    # Pre-existing user text must still follow the image.
    assert content[2] == {"type": "text", "text": "What do you see?"}


def test_attach_image_without_metadata_is_backward_compatible():
    """Calling without metadata_text keeps the old image-only prepend shape."""
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    ]
    out = attach_image_to_last_user_message(messages, b"bytes", "image/png")
    content = out[-1]["content"]
    assert content[0]["type"] == "image"
    assert content[1] == {"type": "text", "text": "hi"}


def test_attach_image_appends_user_message_when_no_trailing_user():
    """No trailing user message → new user message carries label + image."""
    messages: list[dict[str, Any]] = [
        {"role": "assistant", "content": [{"type": "text", "text": "prior"}]}
    ]
    out = attach_image_to_last_user_message(
        messages, b"b", "image/webp", metadata_text="Image 1 of 1."
    )
    assert out[-1]["role"] == "user"
    assert out[-1]["content"][0] == {"type": "text", "text": "Image 1 of 1."}
    assert out[-1]["content"][1]["type"] == "image"


def test_build_camera_metadata_survives_registry_failure(monkeypatch):
    """Registry explosions must not break the vision turn — metadata is best-effort."""
    from custom_components.bedrock_ha_agent import vision

    def boom(*_a, **_kw):
        raise RuntimeError("registry down")

    monkeypatch.setattr(vision.er, "async_get", boom)

    fake_hass = MagicMock()
    fake_state = MagicMock()
    fake_state.attributes = {"friendly_name": "Backyard"}
    fake_hass.states.get.return_value = fake_state

    text = build_camera_metadata(fake_hass, "camera.backyard", index=1, total=1)
    # Must still produce label + name even when area lookup raises.
    assert "Backyard" in text
    assert text.startswith("Image 1 of 1.")
