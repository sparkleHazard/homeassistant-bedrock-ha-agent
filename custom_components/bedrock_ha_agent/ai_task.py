"""AI Task entity for bedrock_ha_agent (v1.4.0)."""
from __future__ import annotations

import json as json_mod
import logging
from json import JSONDecodeError
from types import SimpleNamespace
from typing import TYPE_CHECKING

from homeassistant.components import ai_task, conversation
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.json import json_loads

from .const import CONF_IMAGE_MODEL_ID, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry, ConfigSubentry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: "ConfigEntry",
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AI Task entities from config subentries."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "ai_task_data":
            continue
        async_add_entities(
            [BedrockAITaskEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class BedrockAITaskEntity(ai_task.AITaskEntity, RestoreEntity):
    """AWS Bedrock Claude AI Task entity."""

    _attr_has_entity_name = True
    # Entity name defers to the device name so the entity_id matches the
    # subentry title (e.g. ai_task.bedrock_ha_agent). OpenAI and Google's
    # integrations do the same — they slugify the subentry title via the
    # per-subentry device.
    _attr_name = None
    _attr_supported_features = (
        ai_task.AITaskEntityFeature.GENERATE_DATA
        | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
        | ai_task.AITaskEntityFeature.GENERATE_IMAGE
    )

    def __init__(
        self, config_entry: "ConfigEntry", subentry: "ConfigSubentry"
    ) -> None:
        """Initialize the entity."""
        self._config_entry = config_entry
        self._subentry = subentry
        # unique_id scoped to parent entry + subentry for multi-task support
        self._attr_unique_id = f"{config_entry.entry_id}_{subentry.subentry_id}_ai_task"
        # Per-subentry device so each AI Task entity gets a distinguishable
        # name/identifier in HA. The device name is what HA slugifies into
        # the entity_id since _attr_name is None.
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="AWS",
            model="Bedrock",
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    async def _async_generate_data(
        self,
        task: ai_task.GenDataTask,
        chat_log: conversation.ChatLog,
    ) -> ai_task.GenDataTaskResult:
        """Run a Bedrock turn and return the model's response.

        HA has already appended task.instructions as UserContent to chat_log
        and attached llm_api if the parent entry has CONF_LLM_HASS_API set.
        We just drive the turn until stop_reason != "tool_use", read the
        final AssistantContent, and optionally JSON-parse for structure.
        """
        client = self._config_entry.runtime_data.bedrock_client
        if client is None:
            raise HomeAssistantError("Bedrock client not initialized")

        options = {**self._config_entry.data, **self._config_entry.options}
        agent_id = self._config_entry.entry_id
        llm_api = chat_log.llm_api

        # Build message_history from chat_log. System prompt is already in
        # chat_log.content if HA wired one up; we just mirror everything.
        message_history: list[conversation.Content] = list(chat_log.content)

        # Streaming tool-calling loop. Each iteration calls Bedrock with the
        # full history, streams deltas into chat_log, and — if the turn ended
        # with tool_use — loops. Terminal turns return the final text.
        tool_iterations = 0
        max_tool_call_iterations = 10  # AI Task uses a fixed limit

        _LOGGER.info("AI Task: starting tool-calling loop (max iterations: %d)", max_tool_call_iterations)

        while tool_iterations <= max_tool_call_iterations:
            try:
                _LOGGER.info("AI Task iteration %d: streaming Bedrock response...", tool_iterations)

                turn_state = await self._stream_one_bedrock_turn(
                    client=client,
                    chat_log=chat_log,
                    message_history=message_history,
                    llm_api=llm_api,
                    options=options,
                    agent_id=agent_id,
                )

                # chat_log's delta stream already:
                #   - wrote the AssistantContent (text + tool_calls) to the log
                #   - executed non-external tools and appended ToolResultContent
                # We mirror both into our own message_history so the next
                # Bedrock turn sees the full conversation.
                if turn_state.assistant_content is not None:
                    message_history.append(turn_state.assistant_content)
                message_history.extend(turn_state.tool_results)

                if turn_state.stop_reason is None:
                    _LOGGER.error(
                        "Bedrock stream ended with no stop_reason (tool_calls=%d)",
                        len(turn_state.tool_calls),
                    )
                    raise HomeAssistantError(
                        "Sorry, I received an unexpected response. Please try again."
                    )

                # Terminal turn — extract the final text.
                if turn_state.stop_reason != "tool_use" or not turn_state.tool_calls:
                    final_text = turn_state.full_text.strip()
                    _LOGGER.info(
                        "AI Task complete. Streamed %d chars",
                        len(final_text),
                    )
                    # Parse and return
                    if not task.structure:
                        return ai_task.GenDataTaskResult(
                            conversation_id=chat_log.conversation_id,
                            data=final_text,
                        )
                    try:
                        data = json_loads(final_text)
                    except JSONDecodeError as err:
                        _LOGGER.error(
                            "Failed to parse JSON response: %s. Response: %s", err, final_text
                        )
                        raise HomeAssistantError(
                            "Error with Bedrock structured response"
                        ) from err
                    return ai_task.GenDataTaskResult(
                        conversation_id=chat_log.conversation_id,
                        data=data,
                    )

                # tool_use turn — chat_log already executed the tools,
                # turn_state.tool_results has the resulting content. Loop
                # back for the next Bedrock response.
                _LOGGER.info(
                    "AI Task iteration %d: chat_log executed %d tool call(s), looping",
                    tool_iterations, len(turn_state.tool_calls),
                )
                tool_iterations += 1

            except HomeAssistantError:
                raise

        # Max iterations reached
        _LOGGER.warning(
            "AI Task: max iterations (%d) reached without completion",
            max_tool_call_iterations,
        )
        raise HomeAssistantError(
            "I couldn't complete that request after multiple attempts."
        )

    async def _stream_one_bedrock_turn(
        self,
        *,
        client,
        chat_log: conversation.ChatLog,
        message_history,
        llm_api,
        options,
        agent_id: str,
    ):
        """Stream one Bedrock turn into ``chat_log`` and return final state.

        Returns a SimpleNamespace with:
            stop_reason: str | None
            full_text: str
            tool_calls: list[llm.ToolInput]
            assistant_content: conversation.AssistantContent | None
            tool_results: list[conversation.ToolResultContent]
        """
        # Per-index buffers for incremental tool_use blocks from the stream.
        pending_tool_use: dict[int, dict] = {}
        pending_tool_use_json: dict[int, list[str]] = {}
        full_text: list[str] = []
        stop_reason: str | None = None

        bedrock_events = client.async_generate_stream(
            message_history, llm_api, options
        )

        async def delta_stream():
            """Translate Bedrock stream events into chat_log deltas."""
            nonlocal stop_reason
            # Yield the role starter so chat_log opens a new assistant entry.
            yield {"role": "assistant"}

            try:
                async for kind, payload in bedrock_events:
                    if kind == "text_delta":
                        full_text.append(payload)
                        yield {"content": payload}
                    elif kind == "tool_use_start":
                        idx = payload["index"]
                        pending_tool_use[idx] = {
                            "id": payload.get("id"),
                            "name": payload.get("name"),
                        }
                        pending_tool_use_json[idx] = []
                    elif kind == "tool_use_delta":
                        idx = payload["index"]
                        pending_tool_use_json.setdefault(idx, []).append(
                            payload.get("partial_json", "")
                        )
                    elif kind == "message_end":
                        stop_reason = payload.get("stop_reason")
                        # Assemble tool_calls now that input JSON is complete.
                        from homeassistant.helpers import llm
                        tool_inputs: list[llm.ToolInput] = []
                        # Iterate indexes in order so two calls to the same tool
                        # keep the order Bedrock sent them.
                        for idx in sorted(pending_tool_use):
                            meta = pending_tool_use[idx]
                            raw_json = "".join(pending_tool_use_json.get(idx, []))
                            try:
                                args = json_mod.loads(raw_json) if raw_json else {}
                            except json_mod.JSONDecodeError:
                                _LOGGER.warning(
                                    "Tool %s: could not parse streamed JSON args %r",
                                    meta.get("name"), raw_json,
                                )
                                args = {}
                            tool_input = llm.ToolInput(
                                tool_name=meta.get("name"),
                                tool_args=args,
                            )
                            tool_inputs.append(tool_input)
                        if tool_inputs:
                            yield {"tool_calls": tool_inputs}
                        break
            except HomeAssistantError:
                raise

        # chat_log.async_add_delta_content_stream consumes the delta async
        # iterable and yields the finalized AssistantContent + any
        # ToolResultContent records it produced by executing non-external
        # tools itself. We capture both.
        assistant_content: conversation.AssistantContent | None = None
        tool_results: list[conversation.ToolResultContent] = []
        async for finalized in chat_log.async_add_delta_content_stream(
            agent_id, delta_stream()
        ):
            if isinstance(finalized, conversation.AssistantContent):
                assistant_content = finalized
            elif isinstance(finalized, conversation.ToolResultContent):
                tool_results.append(finalized)

        tool_calls: list = []
        if assistant_content and assistant_content.tool_calls:
            tool_calls = list(assistant_content.tool_calls)

        return SimpleNamespace(
            stop_reason=stop_reason,
            full_text="".join(full_text),
            tool_calls=tool_calls,
            assistant_content=assistant_content,
            tool_results=tool_results,
        )

    async def _async_generate_image(
        self,
        task: ai_task.GenImageTask,
        chat_log: conversation.ChatLog,
    ) -> ai_task.GenImageTaskResult:
        """Generate a single image via the configured Bedrock image model."""
        client = self._config_entry.runtime_data.bedrock_client
        if client is None:
            raise HomeAssistantError("Bedrock client not initialized")

        options = {**self._config_entry.data, **self._config_entry.options}
        if not options.get(CONF_IMAGE_MODEL_ID):
            raise HomeAssistantError(
                "No image model selected. Pick one in the Bedrock integration options."
            )

        _LOGGER.info(
            "AI Task image: model=%s prompt_len=%d",
            options.get(CONF_IMAGE_MODEL_ID),
            len(task.instructions or ""),
        )

        generated = await client.async_generate_image(task.instructions, options)

        return ai_task.GenImageTaskResult(
            conversation_id=chat_log.conversation_id,
            image_data=generated.image_bytes,
            mime_type=generated.mime_type,
            width=generated.width,
            height=generated.height,
            model=generated.model,
            revised_prompt=None,
        )
