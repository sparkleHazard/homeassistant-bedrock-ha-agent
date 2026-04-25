"""Helpers split out of ``conversation.py`` so ``async_process`` stays readable.

These are pure or near-pure functions: they parse a Bedrock response into a
typed result, execute a single tool call, and build ``IntentResponse`` /
``ConversationResult`` pairs for error/final paths. None of them touch the
entry/options state — the caller in ``conversation.py`` is responsible for
that.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components import conversation
from homeassistant.helpers import intent, llm

_LOGGER = logging.getLogger(__name__)

TOOL_CALL_TIMEOUT = 10.0


@dataclass
class BedrockResponse:
    """Parsed shape of one Bedrock assistant message."""

    stop_reason: str | None
    response_text: str
    tool_calls: list[llm.ToolInput]
    # tool_use_id per ToolInput, keyed by ``id(tool_input)``. The caller feeds
    # this back to ``execute_tool_call`` so ``ToolResultContent`` can echo the
    # real Bedrock id and avoid the "tool_use ids must be unique" error.
    tool_use_ids: dict[int, str]


def parse_bedrock_response(response: dict[str, Any]) -> BedrockResponse:
    """Translate a Bedrock ``invoke_model`` response into a ``BedrockResponse``.

    Assumes the Anthropic Messages response shape: ``stop_reason`` plus a
    ``content`` list of blocks with ``type`` in ``{"text", "tool_use"}``.
    Unknown block types are ignored.
    """
    stop_reason = response.get("stop_reason")
    content_blocks = response.get("content", [])

    response_text_parts: list[str] = []
    tool_calls: list[llm.ToolInput] = []
    tool_use_ids: dict[int, str] = {}

    for block in content_blocks:
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text", "")
            if text:
                response_text_parts.append(text)
        elif block_type == "tool_use":
            tool_name = block.get("name")
            tool_input_data = block.get("input", {})
            tool_use_id = block.get("id")
            if not tool_name:
                continue
            tool_input = llm.ToolInput(tool_name=tool_name, tool_args=tool_input_data)
            tool_calls.append(tool_input)
            if tool_use_id:
                tool_use_ids[id(tool_input)] = tool_use_id

    return BedrockResponse(
        stop_reason=stop_reason,
        response_text="".join(response_text_parts),
        tool_calls=tool_calls,
        tool_use_ids=tool_use_ids,
    )


async def execute_tool_call(
    llm_api: llm.APIInstance,
    tool_call: llm.ToolInput,
    tool_use_id: str,
    agent_id: str,
) -> conversation.ToolResultContent:
    """Invoke a single tool with a hard timeout and wrap the result.

    ``tool_use_id`` must be the Bedrock-issued id (from
    ``BedrockResponse.tool_use_ids``) so the ``ToolResultContent`` carries the
    id Bedrock is expecting on the next request.
    """
    try:
        async with asyncio.timeout(TOOL_CALL_TIMEOUT):
            tool_result: Any = await llm_api.async_call_tool(tool_call)
    except asyncio.TimeoutError:
        error_msg = f"Tool call timed out after {TOOL_CALL_TIMEOUT:g} seconds"
        _LOGGER.error("Tool %s: %s", tool_call.tool_name, error_msg)
        tool_result = {"error": error_msg}
    except Exception as err:  # noqa: BLE001 — report and continue
        _LOGGER.error(
            "Error executing tool %s: %s", tool_call.tool_name, err, exc_info=True
        )
        tool_result = {"error": str(err)}

    return conversation.ToolResultContent(
        agent_id=agent_id,
        tool_call_id=tool_use_id,
        tool_name=tool_call.tool_name,
        tool_result=tool_result,
    )


def error_result(
    conversation_id: str | None, language: str, message: str
) -> conversation.ConversationResult:
    """Build a conversation error response."""
    intent_response = intent.IntentResponse(language=language)
    intent_response.async_set_error(intent.IntentResponseErrorCode.UNKNOWN, message)
    return conversation.ConversationResult(
        response=intent_response, conversation_id=conversation_id
    )


def speech_result(
    conversation_id: str | None, language: str, text: str
) -> conversation.ConversationResult:
    """Build a conversation speech response."""
    intent_response = intent.IntentResponse(language=language)
    intent_response.async_set_speech(text)
    return conversation.ConversationResult(
        response=intent_response, conversation_id=conversation_id
    )
