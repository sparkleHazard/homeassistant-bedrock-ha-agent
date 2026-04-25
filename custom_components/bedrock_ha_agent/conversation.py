"""AWS Bedrock conversation implementation."""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
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
    CONF_CONFIG_APPROVAL_TTL_SECONDS,
    CONF_CONFIG_UNDO_DEPTH,
    CONF_CONFIG_UNDO_TTL_SECONDS,
    CONF_ENABLE_CONFIG_EDITING,
    DEFAULT_CONFIG_APPROVAL_TTL_SECONDS,
    DEFAULT_CONFIG_UNDO_DEPTH,
    DEFAULT_CONFIG_UNDO_TTL_SECONDS,
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
from .config_tools.pending import ApprovalOutcome, PendingChangeManager
from .config_tools.undo import UndoEntry, get_or_create_stack
from .runtime_data import _get_runtime_data
from .vision import exposed_camera_entity_ids
from .conversation_helpers import error_result, speech_result

_LOGGER = logging.getLogger(__name__)

# Past-tense regex for AC17 warning
_PAST_TENSE_REGEX = re.compile(
    r"\b(added|created|renamed|deleted|saved|applied|done|configured|updated|removed)\b",
    re.IGNORECASE,
)


def _split_proposal_for_stream(tool_result: dict) -> tuple[str | None, dict]:
    """Return (spoken_text, structured_payload_for_chat_log).

    For pending_approval results, spoken_text is ONLY `proposed_summary`;
    `proposed_diff` stays in the structured payload (chat_log mirrors it as
    text-only structured content, not as a delta). For all other results,
    returns (None, tool_result) — no splitting needed.
    """
    if isinstance(tool_result, dict) and tool_result.get("status") == "pending_approval":
        return tool_result.get("proposed_summary", ""), tool_result
    return None, tool_result


def _lookup_pending(runtime_data, conversation_id: str):
    """Return the non-expired pending change visible to this conversation.

    Checks `conversation_id` first, then falls back to the ``"_global"`` key
    used by `ConfigEditingTool.async_call` when it can't derive a real
    conversation_id from `llm.LLMContext`. See `PendingChangeManager._resolve_key`
    for the background; keeping the same fallback rule here ensures the
    interceptor and the tool-side storage agree on which slot is authoritative.
    """
    pending = runtime_data.pending.get(conversation_id)
    if pending is not None:
        return pending
    return runtime_data.pending.get("_global")


def _check_past_tense_vs_pending(
    hass: HomeAssistant,
    entry_id: str,
    conversation_id: str,
    final_text: str,
) -> str | None:
    """Check if assistant claims success while a proposal is pending (AC17).

    M3: Returns a correction string if past-tense detected with pending, None otherwise.
    """
    runtime_data = _get_runtime_data(hass, entry_id)
    pending = _lookup_pending(runtime_data, conversation_id)
    if pending is None:
        return None

    match = _PAST_TENSE_REGEX.search(final_text)
    if match:
        _LOGGER.warning(
            "config_editing: pending proposal %s still awaiting approval; "
            "assistant text claims success (matched %r)",
            pending.proposal_id,
            match.group(0),
        )
        return (
            "(Heads up — the change is still waiting for your approval; "
            "I haven't applied anything yet.)"
        )
    return None


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
        self.client: BedrockClient = entry.runtime_data.bedrock_client
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
        # L1: downgrade PII-sensitive user text to DEBUG
        _LOGGER.debug("Processing user input: '%s'", user_input.text)
        _LOGGER.info("Processing user input (%d chars)", len(user_input.text))
        
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

            # Approval-turn interceptor (Phase 3 Step 3.2)
            if options.get(CONF_ENABLE_CONFIG_EDITING, False):
                manager = PendingChangeManager.for_entry_conv(
                    self.hass, self.entry.entry_id, user_input.conversation_id
                )
                outcome = manager.handle_approval_intent(user_input.text)

                if outcome.intercepted:
                    # Append synthetic assistant response to chat_log
                    assistant_content = conversation.AssistantContent(
                        agent_id=user_input.agent_id or DOMAIN,
                        content=outcome.user_message,
                    )

                    if outcome.outcome == ApprovalOutcome.APPLIED:
                        # Apply the pending change. Uses `_lookup_pending` so the
                        # fallback to the "_global" bucket matches what the
                        # ConfigEditingTool may have written if
                        # llm_context didn't carry a conversation_id.
                        runtime_data = _get_runtime_data(self.hass, self.entry.entry_id)
                        pending = _lookup_pending(runtime_data, user_input.conversation_id)

                        if pending is not None:
                            _LOGGER.info(
                                "config_editing: applying proposal %s tool=%s",
                                pending.proposal_id, pending.tool_name,
                            )
                            try:
                                # Execute apply_fn
                                apply_result = await pending.apply_fn(  # type: ignore[attr-defined]
                                    self.hass, pending.proposed_payload, pending.pre_state
                                )
                                _LOGGER.info(
                                    "config_editing: applied proposal %s tool=%s result=%s",
                                    pending.proposal_id, pending.tool_name, apply_result,
                                )

                                # Push undo entry
                                undo_stack = get_or_create_stack(
                                    self.hass,
                                    self.entry.entry_id,
                                    user_input.conversation_id,
                                    max_depth=int(
                                        options.get(
                                            CONF_CONFIG_UNDO_DEPTH, DEFAULT_CONFIG_UNDO_DEPTH
                                        )
                                    ),
                                    ttl_seconds=int(
                                        options.get(
                                            CONF_CONFIG_UNDO_TTL_SECONDS,
                                            DEFAULT_CONFIG_UNDO_TTL_SECONDS,
                                        )
                                    ),
                                )

                                undo_entry = UndoEntry(
                                    entry_id=self.entry.entry_id,
                                    conversation_id=user_input.conversation_id,
                                    proposal_id=pending.proposal_id,
                                    tool_name=pending.tool_name,
                                    before_state=pending.pre_state,
                                    after_state=pending.proposed_payload,
                                    restore_fn=pending.restore_fn,  # type: ignore[attr-defined]
                                    timestamp=datetime.now(UTC),
                                    ttl=undo_stack.ttl,
                                    warnings=getattr(pending, "warnings", []),
                                )
                                undo_stack.push(undo_entry)

                                # Clear pending
                                manager.clear_current()

                                # Success message
                                success_msg = f"Applied: {pending.tool_name}."
                                if undo_entry.warnings:
                                    success_msg += " Note: " + "; ".join(undo_entry.warnings)

                                assistant_content = conversation.AssistantContent(
                                    agent_id=user_input.agent_id or DOMAIN,
                                    content=success_msg,
                                )

                            except Exception as err:
                                _LOGGER.exception(
                                    "config_editing: apply_fn failed for proposal %s",
                                    pending.proposal_id,
                                )

                                # Auto-pop undo stack and restore on failure
                                popped = undo_stack.pop_latest()
                                if popped is not None:
                                    try:
                                        await popped.restore_fn()
                                    except Exception as restore_err:
                                        _LOGGER.exception(
                                            "config_editing: restore_fn also failed after apply error"
                                        )

                                assistant_content = conversation.AssistantContent(
                                    agent_id=user_input.agent_id or DOMAIN,
                                    content=f"Failed to apply change: {err}",
                                )

                    elif outcome.outcome == ApprovalOutcome.UNDONE:
                        # Pop from undo stack
                        undo_stack = get_or_create_stack(
                            self.hass,
                            self.entry.entry_id,
                            user_input.conversation_id,
                            max_depth=int(
                                options.get(CONF_CONFIG_UNDO_DEPTH, DEFAULT_CONFIG_UNDO_DEPTH)
                            ),
                            ttl_seconds=int(
                                options.get(
                                    CONF_CONFIG_UNDO_TTL_SECONDS,
                                    DEFAULT_CONFIG_UNDO_TTL_SECONDS,
                                )
                            ),
                        )
                        undo_entry = undo_stack.pop_latest()

                        if undo_entry is None:
                            assistant_content = conversation.AssistantContent(
                                agent_id=user_input.agent_id or DOMAIN,
                                content="Nothing to undo in this conversation.",
                            )
                        else:
                            try:
                                await undo_entry.restore_fn()

                                undo_msg = f"Reverted: {undo_entry.tool_name}."
                                if undo_entry.warnings:
                                    undo_msg += " Note: " + "; ".join(undo_entry.warnings)

                                assistant_content = conversation.AssistantContent(
                                    agent_id=user_input.agent_id or DOMAIN,
                                    content=undo_msg,
                                )
                            except Exception as err:
                                _LOGGER.exception(
                                    "config_editing: undo restore_fn failed for %s",
                                    undo_entry.proposal_id,
                                )
                                assistant_content = conversation.AssistantContent(
                                    agent_id=user_input.agent_id or DOMAIN,
                                    content=f"Failed to undo: {err}",
                                )

                    # Append to chat_log and return
                    chat_log.async_add_assistant_content_without_tools(assistant_content)
                    return speech_result(
                        user_input.conversation_id,
                        user_input.language,
                        assistant_content.content,
                    )

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

                        # Check for past-tense claims vs pending (AC17 + M3)
                        if options.get(CONF_ENABLE_CONFIG_EDITING, False):
                            correction = _check_past_tense_vs_pending(
                                self.hass,
                                self.entry.entry_id,
                                user_input.conversation_id,
                                final_text,
                            )
                            if correction:
                                # M3: prepend correction to speech response
                                final_text = f"{correction}\n\n{final_text}"

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
