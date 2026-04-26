"""Bedrock message + tool-schema construction.

Pure translation of Home Assistant's chat-log ``Content`` objects into the
Bedrock Anthropic-Messages request shape, and of ``llm.Tool`` instances into
the Bedrock ``toolSpec`` (Messages API) shape.

Extracted from ``bedrock_client.py`` so the client only deals with I/O.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import conversation
from homeassistant.helpers import llm

from .const import SERVICE_TOOL_NAME

_LOGGER = logging.getLogger(__name__)


def _vol_type_to_json(validator: Any) -> dict[str, Any]:
    """Convert a voluptuous leaf validator to a JSON Schema type fragment."""
    # Direct types
    if validator is str:
        return {"type": "string"}
    if validator is int:
        return {"type": "integer"}
    if validator is float:
        return {"type": "number"}
    if validator is bool:
        return {"type": "boolean"}
    if validator is dict:
        return {"type": "object"}
    if validator is list:
        return {"type": "array"}

    # cv.string, cv.entity_id, cv.slug, etc. — all string validators
    if callable(validator):
        name = getattr(validator, "__name__", "")
        if name in ("string", "slug", "entity_id", "entity_ids", "domain", "service", "isbool"):
            # known HA validators that accept strings
            if name == "isbool":
                return {"type": "boolean"}
            return {"type": "string"}

    # vol.All(int, vol.Range(min=..., max=...))
    if isinstance(validator, vol.All):
        result: dict[str, Any] = {}
        for v in validator.validators:
            result.update(_vol_type_to_json(v))
        return result

    # vol.Range
    if isinstance(validator, vol.Range):
        r = {}
        if validator.min is not None:
            r["minimum"] = validator.min
        if validator.max is not None:
            r["maximum"] = validator.max
        return r

    # vol.Length
    if isinstance(validator, vol.Length):
        r = {}
        if validator.min is not None:
            r["minLength"] = validator.min
        if validator.max is not None:
            r["maxLength"] = validator.max
        return r

    # vol.In([...])
    if isinstance(validator, vol.In):
        vals = list(validator.container)
        return {"enum": vals}

    # vol.Any(None, dict) or vol.Any(str, list)
    if isinstance(validator, vol.Any):
        # Permissive: return empty schema (accept anything)
        return {}

    # Nested vol.Schema
    if isinstance(validator, vol.Schema):
        return _vol_schema_to_json_schema(validator)

    # Unknown — permissive
    return {}


def _vol_schema_to_json_schema(schema: vol.Schema) -> dict[str, Any]:
    """Convert a vol.Schema to a top-level JSON Schema object."""
    if not isinstance(schema, vol.Schema) or not isinstance(schema.schema, dict):
        return {"type": "object", "properties": {}, "required": []}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for key, validator in schema.schema.items():
        if isinstance(key, vol.Required):
            key_name = str(key.schema)
            required.append(key_name)
        elif isinstance(key, vol.Optional):
            key_name = str(key.schema)
        else:
            key_name = str(key)

        prop_schema = _vol_type_to_json(validator)

        # Attach default for Optional keys when serializable
        if isinstance(key, vol.Optional) and key.default is not vol.UNDEFINED:
            try:
                default_val = key.default() if callable(key.default) else key.default
                if isinstance(default_val, (str, int, float, bool, type(None))):
                    prop_schema.setdefault("type", "string")  # best-effort
                    prop_schema["default"] = default_val
            except Exception:  # noqa: BLE001
                pass

        properties[key_name] = prop_schema or {"type": "string"}

    # extra=ALLOW_EXTRA → additionalProperties: true
    extra_flag = {"additionalProperties": True} if schema.extra == vol.ALLOW_EXTRA else {}

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        **extra_flag,
    }


def format_tools_for_bedrock(llm_api: llm.APIInstance | None) -> list[dict[str, Any]]:
    """Convert HA ``llm.Tool`` instances to Bedrock Anthropic Messages tool specs.

    The built-in ``HassCallService`` tool uses a hand-written schema because its
    voluptuous schema doesn't introspect cleanly. All other tools use automatic
    voluptuous → JSON Schema conversion.
    """
    if not llm_api or not llm_api.tools:
        return []

    bedrock_tools: list[dict[str, Any]] = []
    for tool in llm_api.tools:
        tool_def: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }

        params = getattr(tool, "parameters", None)
        if params and tool.name == SERVICE_TOOL_NAME:
            # Keep the existing hand-written HassCallService schema
            tool_def["input_schema"] = {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "The service to call (e.g., 'light.turn_on')",
                    },
                    "target_device": {
                        "type": "string",
                        "description": "The entity_id of the device to control",
                    },
                    "brightness": {
                        "type": "number",
                        "description": "Brightness level (0-255)",
                    },
                    "rgb_color": {
                        "type": "string",
                        "description": "RGB color as comma-separated values (e.g., '255,0,0')",
                    },
                    "temperature": {"type": "number", "description": "Temperature setting"},
                    "humidity": {"type": "number", "description": "Humidity setting"},
                    "fan_mode": {"type": "string", "description": "Fan mode setting"},
                    "hvac_mode": {"type": "string", "description": "HVAC mode setting"},
                    "preset_mode": {"type": "string", "description": "Preset mode"},
                    "item": {"type": "string", "description": "Item to add to a list"},
                    "duration": {"type": "string", "description": "Duration for the action"},
                },
                "required": ["service", "target_device"],
            }
        elif params:
            try:
                tool_def["input_schema"] = _vol_schema_to_json_schema(params)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to convert schema for tool %s: %s; using empty schema",
                    tool.name,
                    err,
                )

        bedrock_tools.append(tool_def)

    _LOGGER.info("Formatted %d tool(s) for Bedrock", len(bedrock_tools))
    return bedrock_tools


def _pair_tool_calls_to_ids(
    conversation_content: list[conversation.Content],
) -> dict[int, str]:
    """Map each ``tool_call``'s Python id to its real Bedrock ``tool_use_id``.

    A single assistant turn can call the same tool multiple times (e.g. two
    ``HassCallService`` calls in one message). Matching by ``tool_name`` alone
    would hand every call the same id and produce duplicate ``tool_use`` blocks,
    which Bedrock rejects with ``tool_use ids must be unique``. Instead, pair
    calls to their matching results **in order**, consuming each result once.
    """
    out: dict[int, str] = {}
    for idx, content in enumerate(conversation_content):
        if not (
            isinstance(content, conversation.AssistantContent) and content.tool_calls
        ):
            continue

        # Collect ToolResultContent entries in this turn (until the next assistant).
        turn_results: list[conversation.ToolResultContent] = []
        for future_idx in range(idx + 1, len(conversation_content)):
            future = conversation_content[future_idx]
            if isinstance(future, conversation.ToolResultContent):
                turn_results.append(future)
            elif isinstance(future, conversation.AssistantContent):
                break

        consumed: set[int] = set()
        for tool_call in content.tool_calls:
            for result_idx, result in enumerate(turn_results):
                if result_idx in consumed:
                    continue
                if result.tool_name == tool_call.tool_name:
                    out[id(tool_call)] = result.tool_call_id
                    consumed.add(result_idx)
                    break
    return out


def _tool_result_block(content: conversation.ToolResultContent) -> dict[str, Any]:
    """Render one ``ToolResultContent`` as a Bedrock ``tool_result`` block."""
    raw = content.tool_result
    text = json.dumps(raw) if isinstance(raw, dict) else str(raw)
    return {
        "type": "tool_result",
        "tool_use_id": content.tool_call_id,
        "content": [{"type": "text", "text": text}],
    }


def build_bedrock_messages(
    conversation_content: list[conversation.Content],
) -> list[dict[str, Any]]:
    """Translate HA chat-log content into Bedrock ``messages`` list.

    System content is stripped — callers attach it to the top-level ``system``
    field of the Bedrock request body, not to ``messages``.
    """
    tool_call_to_id = _pair_tool_calls_to_ids(conversation_content)
    messages: list[dict[str, Any]] = []
    fallback_counter = 0

    for content in conversation_content:
        if isinstance(content, conversation.SystemContent):
            continue

        if isinstance(content, conversation.UserContent):
            messages.append(
                {"role": "user", "content": [{"type": "text", "text": content.content}]}
            )
            continue

        if isinstance(content, conversation.AssistantContent):
            blocks: list[dict[str, Any]] = []
            if content.content:
                blocks.append({"type": "text", "text": content.content})
            if content.tool_calls:
                for tool_call in content.tool_calls:
                    tool_use_id = tool_call_to_id.get(id(tool_call))
                    if tool_use_id is None:
                        fallback_counter += 1
                        tool_use_id = f"tool_fallback_{fallback_counter}"
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tool_use_id,
                            "name": tool_call.tool_name,
                            "input": tool_call.tool_args,
                        }
                    )
            if blocks:
                messages.append({"role": "assistant", "content": blocks})
            continue

        if isinstance(content, conversation.ToolResultContent):
            block = _tool_result_block(content)
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"].append(block)
            else:
                messages.append({"role": "user", "content": [block]})

    return messages
