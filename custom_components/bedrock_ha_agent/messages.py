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
        # validator.container is a Container (set, list, etc.) — convert to list for JSON
        container = validator.container
        vals: list[Any] = list(container) if hasattr(container, '__iter__') else []  # type: ignore[call-overload]  # voluptuous Container is iterable
        return {"enum": vals}

    # vol.Any(None, dict) or vol.Any(str, list) — pick the first concrete
    # non-None branch so Bedrock gets a usable `type` (it rejects empty schemas).
    if isinstance(validator, vol.Any):
        for branch in validator.validators:
            if branch is None or branch is type(None):
                continue
            branch_schema = _vol_type_to_json(branch)
            if branch_schema and "type" in branch_schema:
                return branch_schema
        return {"type": "string"}

    # Nested vol.Schema
    if isinstance(validator, vol.Schema):
        return _vol_schema_to_json_schema(validator)

    # Unknown — permissive
    return {}


def _vol_schema_to_json_schema(schema: vol.Schema) -> dict[str, Any]:
    """Convert a vol.Schema to a top-level JSON Schema object.

    Output conforms to Bedrock's JSON Schema subset:
    - No `default` fields (Bedrock rejects them).
    - Every property has a concrete `type` (Bedrock requires it).
    - Non-string non-Required/Optional keys (e.g. free-form ``cv.string``
      dict keys used with ``extra=vol.ALLOW_EXTRA``) are dropped from
      ``properties`` — they belong under ``additionalProperties`` instead.
    """
    if not isinstance(schema, vol.Schema) or not isinstance(schema.schema, dict):
        return {"type": "object", "properties": {}, "required": []}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for key, validator in schema.schema.items():
        # Only string-named keys become JSON Schema properties.
        if isinstance(key, vol.Required):
            if not isinstance(key.schema, str):
                continue
            key_name = key.schema
            required.append(key_name)
        elif isinstance(key, vol.Optional):
            if not isinstance(key.schema, str):
                continue
            key_name = key.schema
        elif isinstance(key, str):
            key_name = key
        else:
            # Function keys (e.g. cv.string used as a free-form key with
            # extra=ALLOW_EXTRA) cannot be JSON Schema properties. Skip them;
            # they'll be covered by additionalProperties below.
            continue

        prop_schema = _vol_type_to_json(validator)

        # Bedrock requires every property to declare a concrete type.
        # Permissive converters return {} — promote those to string.
        if not prop_schema or "type" not in prop_schema:
            # vol.Any(None, dict) and similar — fall back to a permissive
            # string type so Bedrock accepts the schema. Specific callers
            # that need object payloads should use vol.Schema({...}) nested.
            prop_schema = {**prop_schema, "type": "string"}

        # Bedrock does NOT accept `default` in tool input_schema. Skip it.
        properties[key_name] = prop_schema

    extra_flag: dict[str, Any] = (
        {"additionalProperties": True} if schema.extra == vol.ALLOW_EXTRA else {}
    )

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
