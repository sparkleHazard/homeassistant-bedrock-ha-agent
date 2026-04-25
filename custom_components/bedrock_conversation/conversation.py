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
    CONF_LLM_HASS_API,
    CONF_MAX_TOOL_CALL_ITERATIONS,
    CONF_PROMPT,
    CONF_REFRESH_SYSTEM_PROMPT,
    CONF_REMEMBER_CONVERSATION,
    CONF_REMEMBER_NUM_INTERACTIONS,
    DEFAULT_MAX_TOOL_CALL_ITERATIONS,
    DEFAULT_PROMPT,
    DEFAULT_REFRESH_SYSTEM_PROMPT,
    DEFAULT_REMEMBER_CONVERSATION,
    DEFAULT_REMEMBER_NUM_INTERACTIONS,
    DOMAIN,
)
from .conversation_helpers import (
    error_result,
    execute_tool_call,
    parse_bedrock_response,
    speech_result,
)

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
            
            # Tool calling loop
            tool_iterations = 0
            agent_id = self.entry.entry_id
            
            _LOGGER.info("Starting tool calling loop (max iterations: %d)", max_tool_call_iterations)
            
            while tool_iterations <= max_tool_call_iterations:
                try:
                    _LOGGER.info("Iteration %d: Calling Bedrock...", tool_iterations)
                    
                    response = await self.client.async_generate(
                        message_history, llm_api, agent_id, options
                    )

                    parsed = parse_bedrock_response(response)
                    _LOGGER.info(
                        "Bedrock response - stop_reason: %s, tool_calls: %d",
                        parsed.stop_reason, len(parsed.tool_calls),
                    )

                    # Missing stop_reason means the response shape is unexpected
                    # (e.g. an error payload with no content). Surface it.
                    if parsed.stop_reason is None:
                        _LOGGER.error(
                            "Bedrock response missing 'stop_reason'. Keys: %s",
                            list(response.keys()),
                        )
                        if "error" in response:
                            return error_result(
                                user_input.conversation_id,
                                user_input.language,
                                f"Bedrock API error: {response.get('error')}",
                            )
                        return error_result(
                            user_input.conversation_id,
                            user_input.language,
                            "Sorry, I received an unexpected response. Please try again.",
                        )

                    # Record the assistant's turn.
                    if parsed.response_text or parsed.tool_calls:
                        message_history.append(
                            conversation.AssistantContent(
                                agent_id=agent_id,
                                content=parsed.response_text.strip(),
                                tool_calls=parsed.tool_calls or None,
                            )
                        )

                    # Terminal turn — no tool loop continues.
                    if parsed.stop_reason != "tool_use" or not parsed.tool_calls:
                        final_text = parsed.response_text.strip()
                        _LOGGER.info(
                            "Conversation complete. Response length: %d chars",
                            len(final_text),
                        )
                        control_chars = [
                            c for c in final_text if ord(c) < 32 and c not in "\n\r\t"
                        ]
                        if control_chars:
                            _LOGGER.warning(
                                "Found control characters in response: %s",
                                [hex(ord(c)) for c in control_chars[:10]],
                            )
                        return speech_result(
                            user_input.conversation_id, user_input.language, final_text
                        )

                    # Run every tool in this turn and append the results to history.
                    _LOGGER.info("Executing %d tool call(s)...", len(parsed.tool_calls))
                    for idx, tool_call in enumerate(parsed.tool_calls):
                        tool_use_id = parsed.tool_use_ids.get(
                            id(tool_call), f"tool_fallback_{tool_iterations}_{idx}"
                        )
                        message_history.append(
                            await execute_tool_call(
                                llm_api, tool_call, tool_use_id, agent_id
                            )
                        )

                    _LOGGER.info(
                        "Iteration %d complete (%d tool result(s) appended)",
                        tool_iterations, len(parsed.tool_calls),
                    )
                    tool_iterations += 1

                except HomeAssistantError as err:
                    _LOGGER.error("Error calling Bedrock: %s", err, exc_info=True)
                    return error_result(
                        user_input.conversation_id,
                        user_input.language,
                        f"Sorry, there was an error: {err}",
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
