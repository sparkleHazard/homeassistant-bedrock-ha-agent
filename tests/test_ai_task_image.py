"""Tests for AI Task image generation (v1.5.0)."""
from __future__ import annotations

import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.bedrock_ha_agent.bedrock_client import (
    BedrockClient,
    GeneratedImage,
)
from custom_components.bedrock_ha_agent.const import (
    CONF_IMAGE_MODEL_ID,
    image_model_family,
)


# A tiny, valid PNG payload (1x1 transparent pixel) reused across tests.
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
    b"\xc0\x00\x00\x00\x03\x00\x01!\xf5\x9aC\x00\x00\x00\x00IEND\xaeB`\x82"
)
_PNG_B64 = base64.b64encode(_PNG_BYTES).decode("ascii")


# ---------------------------------------------------------------------------
# Pure-helper tests: image_model_family routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("amazon.nova-canvas-v1:0", "nova"),
        ("amazon.titan-image-generator-v2:0", "titan"),
        ("amazon.titan-image-generator-v1", "titan"),
        ("stability.sd3-5-large-v1:0", "stability"),
        ("stability.stable-image-core-v1:1", "stability"),
        ("stability.stable-image-ultra-v1:1", "stability"),
        ("anthropic.claude-sonnet-4-5", None),
        ("", None),
        (None, None),
    ],
)
def test_image_model_family_routing(model_id, expected):
    """image_model_family picks the right family per model id substring."""
    assert image_model_family(model_id) == expected


# ---------------------------------------------------------------------------
# async_generate_image — body shape + response decoding per family
# ---------------------------------------------------------------------------


def _make_client_with_response(response_body: dict) -> BedrockClient:
    """Build a BedrockClient stub with a pre-wired invoke_model response.

    The client's `_ensure_client` is a no-op because we set `_bedrock_runtime`
    directly; no real boto3 session is built.
    """

    hass = MagicMock()

    async def _noop_executor(fn, *args):
        # Mirrors hass.async_add_executor_job: just call fn in the event loop.
        return fn(*args)

    hass.async_add_executor_job = _noop_executor

    entry = MagicMock()
    entry.data = {}
    entry.options = {}
    entry.runtime_data = None  # _runtime_usage_tracker returns None -> no-op

    client = BedrockClient(hass, entry)

    mock_runtime = MagicMock()
    response_bytes = json.dumps(response_body).encode("utf-8")
    mock_runtime.invoke_model.return_value = {
        "body": io.BytesIO(response_bytes),
    }
    client._bedrock_runtime = mock_runtime
    return client


async def test_generate_image_nova_body_and_decode():
    """Nova Canvas body uses taskType + textToImageParams; response decodes to bytes."""
    client = _make_client_with_response({"images": [_PNG_B64], "error": None})

    result = await client.async_generate_image(
        "a red apple on a white table",
        {CONF_IMAGE_MODEL_ID: "amazon.nova-canvas-v1:0"},
    )

    assert isinstance(result, GeneratedImage)
    assert result.image_bytes == _PNG_BYTES
    assert result.mime_type == "image/png"
    assert result.model == "amazon.nova-canvas-v1:0"
    assert result.width == 1024
    assert result.height == 1024

    # Inspect the request body that was sent.
    (_args, kwargs) = client._bedrock_runtime.invoke_model.call_args
    assert kwargs["modelId"] == "amazon.nova-canvas-v1:0"
    sent = json.loads(kwargs["body"])
    assert sent["taskType"] == "TEXT_IMAGE"
    assert sent["textToImageParams"]["text"] == "a red apple on a white table"
    assert sent["imageGenerationConfig"]["numberOfImages"] == 1


async def test_generate_image_titan_shares_nova_body():
    """Titan uses the same taskType schema as Nova Canvas."""
    client = _make_client_with_response({"images": [_PNG_B64]})

    result = await client.async_generate_image(
        "a sunset", {CONF_IMAGE_MODEL_ID: "amazon.titan-image-generator-v2:0"}
    )
    assert result.image_bytes == _PNG_BYTES

    (_args, kwargs) = client._bedrock_runtime.invoke_model.call_args
    sent = json.loads(kwargs["body"])
    assert sent["taskType"] == "TEXT_IMAGE"
    assert sent["textToImageParams"]["text"] == "a sunset"


async def test_generate_image_stability_body_and_decode():
    """Stability body uses mode=text-to-image, prompt=<prompt>."""
    client = _make_client_with_response(
        {"images": [_PNG_B64], "finish_reasons": ["SUCCESS"], "seeds": [42]}
    )

    result = await client.async_generate_image(
        "neon cyberpunk cat",
        {CONF_IMAGE_MODEL_ID: "stability.sd3-5-large-v1:0"},
    )
    assert result.image_bytes == _PNG_BYTES
    assert result.mime_type == "image/png"

    (_args, kwargs) = client._bedrock_runtime.invoke_model.call_args
    sent = json.loads(kwargs["body"])
    assert sent["mode"] == "text-to-image"
    assert sent["prompt"] == "neon cyberpunk cat"
    assert sent["output_format"] == "png"


async def test_generate_image_stability_content_filtered_raises():
    """CONTENT_FILTERED finish reason surfaces as a HomeAssistantError."""
    from homeassistant.exceptions import HomeAssistantError

    client = _make_client_with_response(
        {"images": [""], "finish_reasons": ["CONTENT_FILTERED"]}
    )

    with pytest.raises(HomeAssistantError, match="safety policy"):
        await client.async_generate_image(
            "whatever", {CONF_IMAGE_MODEL_ID: "stability.sd3-5-large-v1:0"}
        )


async def test_generate_image_nova_error_field_raises():
    """Nova Canvas refusal (non-empty `error`) surfaces as HomeAssistantError."""
    from homeassistant.exceptions import HomeAssistantError

    client = _make_client_with_response(
        {"images": [], "error": "Prompt violates policy"}
    )

    with pytest.raises(HomeAssistantError, match="Prompt violates policy"):
        await client.async_generate_image(
            "nope", {CONF_IMAGE_MODEL_ID: "amazon.nova-canvas-v1:0"}
        )


async def test_generate_image_missing_model_id_raises():
    """Missing CONF_IMAGE_MODEL_ID -> actionable HomeAssistantError."""
    from homeassistant.exceptions import HomeAssistantError

    client = _make_client_with_response({"images": [_PNG_B64]})

    with pytest.raises(HomeAssistantError, match="No image model selected"):
        await client.async_generate_image("x", {})


async def test_generate_image_unknown_family_raises():
    """An unrecognized model id is rejected before any Bedrock call."""
    from homeassistant.exceptions import HomeAssistantError

    client = _make_client_with_response({"images": [_PNG_B64]})

    with pytest.raises(HomeAssistantError, match="Unknown image model family"):
        await client.async_generate_image(
            "x", {CONF_IMAGE_MODEL_ID: "anthropic.claude-sonnet-4-5"}
        )
    # And we never hit Bedrock for unknown families.
    client._bedrock_runtime.invoke_model.assert_not_called()


async def test_generate_image_malformed_base64_raises():
    """Malformed base64 in response is reported as HomeAssistantError."""
    from homeassistant.exceptions import HomeAssistantError

    client = _make_client_with_response({"images": ["not-base64!!!"]})

    with pytest.raises(HomeAssistantError, match="malformed image data"):
        await client.async_generate_image(
            "x", {CONF_IMAGE_MODEL_ID: "amazon.nova-canvas-v1:0"}
        )


# ---------------------------------------------------------------------------
# Entity-level: _async_generate_image wires through to the client
# ---------------------------------------------------------------------------


async def test_entity_generate_image_delegates_to_client():
    """The entity reads CONF_IMAGE_MODEL_ID, calls client, shapes the result."""
    from custom_components.bedrock_ha_agent.ai_task import BedrockAITaskEntity

    entry = MagicMock()
    entry.entry_id = "e1"
    entry.data = {}
    entry.options = {CONF_IMAGE_MODEL_ID: "amazon.nova-canvas-v1:0"}

    client_stub = MagicMock()

    async def _fake_generate_image(prompt, options, **_kw):
        assert prompt == "a robot"
        assert options[CONF_IMAGE_MODEL_ID] == "amazon.nova-canvas-v1:0"
        return GeneratedImage(
            image_bytes=_PNG_BYTES,
            mime_type="image/png",
            width=1024,
            height=1024,
            model="amazon.nova-canvas-v1:0",
        )

    client_stub.async_generate_image = _fake_generate_image
    entry.runtime_data = SimpleNamespace(bedrock_client=client_stub)

    subentry = SimpleNamespace(subentry_id="s1", title="Bedrock AI Task")
    entity = BedrockAITaskEntity(entry, subentry)

    task = SimpleNamespace(instructions="a robot", attachments=None)
    chat_log = SimpleNamespace(conversation_id="conv-123")

    result = await entity._async_generate_image(task, chat_log)

    assert result.image_data == _PNG_BYTES
    assert result.mime_type == "image/png"
    assert result.model == "amazon.nova-canvas-v1:0"
    assert result.width == 1024
    assert result.height == 1024
    assert result.conversation_id == "conv-123"
    assert result.revised_prompt is None


async def test_entity_generate_image_missing_model_raises():
    """Entity surfaces 'no image model selected' when option is unset."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.bedrock_ha_agent.ai_task import BedrockAITaskEntity

    entry = MagicMock()
    entry.entry_id = "e1"
    entry.data = {}
    entry.options = {}  # no CONF_IMAGE_MODEL_ID

    entry.runtime_data = SimpleNamespace(bedrock_client=MagicMock())

    subentry = SimpleNamespace(subentry_id="s1", title="Bedrock AI Task")
    entity = BedrockAITaskEntity(entry, subentry)

    task = SimpleNamespace(instructions="x", attachments=None)
    chat_log = SimpleNamespace(conversation_id="c")

    with pytest.raises(HomeAssistantError, match="No image model selected"):
        await entity._async_generate_image(task, chat_log)
