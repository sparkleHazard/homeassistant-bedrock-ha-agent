"""AWS Bedrock conversation implementation."""
from __future__ import annotations

import logging
from typing import Literal

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    HomeAssistantError,
    TemplateError,
)
from homeassistant.helpers import chat_session, llm
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .bedrock_client import BedrockClient
from .const import (
    CONF_AUTO_ATTACH_CAMERAS,
    CONF_LLM_HASS_API,
    CONF_MAX_TOOL_CALL_ITERATIONS,
    CONF_PROMPT,
    CONF_REFRESH_SYSTEM_PROMPT,
    CONF_REMEMBER_CONVERSATION,
    CONF_REMEMBER_NUM_INTERACTIONS,
    DEFAULT_AUTO_ATTACH_CAMERAS,
    DEFAULT_MAX_TOOL_CALL_ITERATIONS,
    DEFAULT_PROMPT,
    DEFAULT_REFRESH_SYSTEM_PROMPT,
    DEFAULT_REMEMBER_CONVERSATION,
    DEFAULT_REMEMBER_NUM_INTERACTIONS,
    DOMAIN,
)
from .vision import exposed_camera_entity_ids
from .conversation_helpers import error_result, speech_result

_LOGGER = logging.getLogger(__name__)


class BedrockConversationEntity(
    conversation.ConversationEntity,
    conversation.AbstractConversationAgent,
):
    """Bedrock conversation agent entity."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the agent."""
        self.hass = hass
        self.entry = entry
        self.history = {}
        self.client: BedrockClient = entry.runtime_data["client"]
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = None
        
        # Check if we should enable device control
        if entry.options.get(CONF_LLM_HASS_API):
            self._attr_supported_features = (
                conversation.ConversationEntityFeature.CONTROL
            )

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return MATCH_ALL

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        conversation.async_set_agent(self.hass, self.entry, self)
        _LOGGER.info("Bedrock conversation agent registered")

    async def async_will_remove_from_hass(self) -> None:
        """When entity is being removed from hass."""
        conversation.async_unset_agent(self.hass, self.entry)
        await super().async_will_remove_from_hass()
        _LOGGER.info("Bedrock conversation agent unregistered")

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """Process a sentence."""
        _LOGGER.info("Processing user input: '%s'", user_input.text)
        
        options = {**self.entry.data, **self.entry.options}
        
        with (
            chat_session.async_get_chat_session(
                self.hass, user_input.conversation_id
            ) as session,
            conversation.async_get_chat_log(self.hass, session, user_input) as chat_log,
        ):
            raw_prompt = options.get(CONF_PROMPT, DEFAULT_PROMPT)
            refresh_system_prompt = options.get(
                CONF_REFRESH_SYSTEM_PROMPT, DEFAULT_REFRESH_SYSTEM_PROMPT
            )
            remember_conversation = options.get(
                CONF_REMEMBER_CONVERSATION, DEFAULT_REMEMBER_CONVERSATION
            )
            # NumberSelector stores values as floats; coerce the integer-semantic
            # options before using them for list slicing / loop bounds.
            remember_num_interactions = int(options.get(
                CONF_REMEMBER_NUM_INTERACTIONS, DEFAULT_REMEMBER_NUM_INTERACTIONS
            ))
            max_tool_call_iterations = int(options.get(
                CONF_MAX_TOOL_CALL_ITERATIONS, DEFAULT_MAX_TOOL_CALL_ITERATIONS
            ))
            
            # Get LLM API if configured
            llm_api: llm.APIInstance | None = None
            if options.get(CONF_LLM_HASS_API):
                try:
                    _LOGGER.info("Getting LLM API: %s", options[CONF_LLM_HASS_API])
                    llm_api = await llm.async_get_api(
                        self.hass,
                        options[CONF_LLM_HASS_API],
                        llm_context=user_input.as_llm_context(DOMAIN)
                    )
                    _LOGGER.info("LLM API loaded with %d tools", len(llm_api.tools) if llm_api.tools else 0)
                except HomeAssistantError as err:
                    _LOGGER.error("Error getting LLM API: %s", err)
                    return error_result(
                        user_input.conversation_id,
                        user_input.language,
                        f"Error preparing LLM API: {err}",
                    )
            
            # Ensure chat log has the LLM API instance
            chat_log.llm_api = llm_api
            
            # Get message history
            if remember_conversation:
                message_history = chat_log.content[:]
            else:
                message_history = []
            
            _LOGGER.info("Message history length: %d messages", len(message_history))
            
            # Trim history if needed
            if remember_num_interactions and len(message_history) > (remember_num_interactions * 2) + 1:
                new_message_history = [message_history[0]]  # Keep system prompt
                new_message_history.extend(message_history[1:][-(remember_num_interactions * 2):])
                message_history = new_message_history
                _LOGGER.info("Trimmed history to %d messages", len(message_history))
            
            # Generate or refresh system prompt
            if len(message_history) == 0 or refresh_system_prompt:
                try:
                    _LOGGER.info("Generating system prompt...")
                    system_prompt_text = await self.client._generate_system_prompt(
                        raw_prompt, llm_api, options
                    )
                    system_prompt = conversation.SystemContent(content=system_prompt_text)
                    _LOGGER.info("System prompt generated (%d chars)", len(system_prompt_text))
                except TemplateError as err:
                    _LOGGER.error("Error rendering prompt: %s", err)
                    return error_result(
                        user_input.conversation_id,
                        user_input.language,
                        f"Sorry, I had a problem with my template: {err}",
                    )
                
                if len(message_history) == 0:
                    message_history.append(system_prompt)
                else:
                    message_history[0] = system_prompt
            
            # Add user message
            message_history.append(conversation.UserContent(content=user_input.text))
            
            # Streaming tool-calling loop. Each iteration calls Bedrock with
            # the full history, streams deltas into chat_log (HA streams those
            # to TTS automatically), and — if the turn ended with tool_use —
            # executes the tools and loops. Terminal turns return whatever
            # text was streamed.
            tool_iterations = 0
            agent_id = self.entry.entry_id
            _LOGGER.info("Starting tool-calling loop (max iterations: %d)", max_tool_call_iterations)

            # Resolve cameras to auto-attach (first iteration only).
            auto_attach_cameras: list[str] = []
            if options.get(CONF_AUTO_ATTACH_CAMERAS, DEFAULT_AUTO_ATTACH_CAMERAS):
                auto_attach_cameras = exposed_camera_entity_ids(self.hass)
                if auto_attach_cameras:
                    _LOGGER.info(
                        "Auto-attaching %d camera snapshot(s): %s",
                        len(auto_attach_cameras), auto_attach_cameras,
                    )

            while tool_iterations <= max_tool_call_iterations:
                try:
                    _LOGGER.info("Iteration %d: streaming Bedrock response...", tool_iterations)

                    turn_state = await self._stream_one_bedrock_turn(
                        chat_log=chat_log,
                        message_history=message_history,
                        llm_api=llm_api,
                        options=options,
                        agent_id=agent_id,
                        attach_images_from_cameras=(
                            auto_attach_cameras if tool_iterations == 0 else None
                        ),
                    )

                    # chat_log's delta stream already:
                    #   - wrote the AssistantContent (text + tool_calls) to the log
                    #   - executed non-external tools and appended ToolResultContent
                    # We mirror both into our own message_history so the next
                    # Bedrock turn sees the full Bedrock-shaped conversation.
                    if turn_state.assistant_content is not None:
                        message_history.append(turn_state.assistant_content)
                    message_history.extend(turn_state.tool_results)

                    if turn_state.stop_reason is None:
                        _LOGGER.error(
                            "Bedrock stream ended with no stop_reason (tool_calls=%d)",
                            len(turn_state.tool_calls),
                        )
                        return error_result(
                            user_input.conversation_id,
                            user_input.language,
                            "Sorry, I received an unexpected response. Please try again.",
                        )

                    # Terminal turn — streaming already pushed text to TTS.
                    if turn_state.stop_reason != "tool_use" or not turn_state.tool_calls:
                        final_text = turn_state.full_text.strip()
                        _LOGGER.info(
                            "Conversation complete. Streamed %d chars",
                            len(final_text),
                        )
                        return speech_result(
                            user_input.conversation_id,
                            user_input.language,
                            final_text,
                        )

                    # tool_use turn — chat_log already executed the tools,
                    # turn_state.tool_results has the resulting content. Loop
                    # back for the next Bedrock response.
                    _LOGGER.info(
                        "Iteration %d: chat_log executed %d tool call(s), looping",
                        tool_iterations, len(turn_state.tool_calls),
                    )
                    tool_iterations += 1

                except HomeAssistantError as err:
                    _LOGGER.error("Error during Bedrock stream: %s", err, exc_info=True)
                    # The client already translated ClientError → a
                    # voice-friendly message before raising, so surface it
                    # directly instead of wrapping with "Sorry, there was an
                    # error:".
                    return error_result(
                        user_input.conversation_id,
                        user_input.language,
                        str(err),
                    )

            # Max iterations reached
            _LOGGER.warning(
                "Max iterations (%d) reached without completion",
                max_tool_call_iterations,
            )
            return speech_result(
                user_input.conversation_id,
                user_input.language,
                "I'm sorry, I couldn't complete that request after multiple attempts.",
            )

    async def _stream_one_bedrock_turn(
        self,
        *,
        chat_log: conversation.ChatLog,
        message_history,
        llm_api,
        options,
        agent_id: str,
        attach_images_from_cameras: list[str] | None = None,
    ):
        """Stream one Bedrock turn into ``chat_log`` and return final state.

        Returns a small object with:
            stop_reason: str | None
            full_text: str
            tool_calls: list[llm.ToolInput]
            tool_use_ids: dict[int(tool_call), str]  — Bedrock tool_use_id by id()
            assistant_content: conversation.AssistantContent | None
        """
        import json as json_mod
        from types import SimpleNamespace

        # Per-index buffers for incremental tool_use blocks from the stream.
        pending_tool_use: dict[int, dict] = {}
        pending_tool_use_json: dict[int, list[str]] = {}
        full_text: list[str] = []
        stop_reason: str | None = None

        bedrock_events = self.client.async_generate_stream(
            message_history, llm_api, options,
            attach_images_from_cameras=attach_images_from_cameras,
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

        tool_calls: list[llm.ToolInput] = []
        if assistant_content and assistant_content.tool_calls:
            tool_calls = list(assistant_content.tool_calls)

        return SimpleNamespace(
            stop_reason=stop_reason,
            full_text="".join(full_text),
            tool_calls=tool_calls,
            assistant_content=assistant_content,
            tool_results=tool_results,
        )

    async def async_reload(self, language: str | None = None) -> None:
        """Clear cached intents for a language."""
        pass

    async def async_prepare(self, language: str | None = None) -> None:
        """Load intents for a language."""
        pass


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up conversation agent."""
    agent = BedrockConversationEntity(hass, config_entry)
    async_add_entities([agent])
