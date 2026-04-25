"""AWS Bedrock client for conversation agents."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from dataclasses import dataclass

from botocore.exceptions import ClientError

from homeassistant.core import HomeAssistant
from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import (
    HomeAssistantError,
    TemplateError,
)
from homeassistant.helpers import (
    area_registry as ar,
    entity_registry as er,
    llm,
    template,
)

from .aws_session import session_from_entry_data
from .utils import closest_color
from .const import (
    CONF_AWS_REGION,
    CONF_EXTRA_ATTRIBUTES_TO_EXPOSE,
    CONF_MAX_TOKENS,
    CONF_MODEL_ID,
    CONF_SELECTED_LANGUAGE,
    CONF_TEMPERATURE,
    CURRENT_DATE_PROMPT,
    DEFAULT_AWS_REGION,
    DEFAULT_EXTRA_ATTRIBUTES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_ID,
    DEFAULT_SELECTED_LANGUAGE,
    DEFAULT_TEMPERATURE,
    DEVICES_PROMPT,
    PERSONA_PROMPTS,
    SERVICE_TOOL_NAME,
)

_LOGGER = logging.getLogger(__name__)

BedrockConfigEntry = ConfigEntry


@dataclass
class DeviceInfo:
    """Class to hold device information."""

    entity_id: str
    name: str
    state: str
    attributes: list[str]
    area_id: str | None = None
    area_name: str | None = None


class BedrockClient:
    """AWS Bedrock client."""

    def __init__(self, hass: HomeAssistant, entry: BedrockConfigEntry) -> None:
        """Initialize the client."""
        self.hass = hass
        self.entry = entry
        self._bedrock_runtime = None
        self._client_lock = None

    def _create_bedrock_client(self) -> Any:
        """Create the AWS Bedrock client (runs in executor)."""
        options = self.entry.options
        
        # Get AWS credentials from config entry
        # Region: options override, then entry.data, then default.
        aws_region = options.get(
            CONF_AWS_REGION,
            self.entry.data.get(CONF_AWS_REGION, DEFAULT_AWS_REGION),
        )
        session = session_from_entry_data(self.entry.data, region_override=aws_region)
        
        bedrock_runtime = session.client('bedrock-runtime')
        _LOGGER.info("Bedrock client initialized with region %s", aws_region)
        return bedrock_runtime

    async def _ensure_client(self) -> None:
        """Ensure the Bedrock client is initialized (lazy initialization)."""
        if self._bedrock_runtime is None:
            if self._client_lock is None:
                self._client_lock = asyncio.Lock()

            async with self._client_lock:
                # Double-check after acquiring lock
                if self._bedrock_runtime is None:
                    _LOGGER.info("Creating Bedrock client in executor")
                    self._bedrock_runtime = await self.hass.async_add_executor_job(
                        self._create_bedrock_client
                    )

    def _get_exposed_entities(self) -> list[DeviceInfo]:
        """Get all exposed entities with their information."""
        entity_registry = er.async_get(self.hass)
        area_registry = ar.async_get(self.hass)
        
        extra_attributes = self.entry.options.get(
            CONF_EXTRA_ATTRIBUTES_TO_EXPOSE,
            DEFAULT_EXTRA_ATTRIBUTES
        )
        
        devices = []
        
        for state in self.hass.states.async_all():
            if not async_should_expose(self.hass, "conversation", state.entity_id):
                continue
            
            entity_entry = entity_registry.async_get(state.entity_id)
            area_id = entity_entry.area_id if entity_entry else None
            area_name = None
            
            if area_id:
                area = area_registry.async_get_area(area_id)
                area_name = area.name if area else None
            
            # Extract relevant attributes
            attributes = []
            
            # Brightness
            if state.domain == "light" and "brightness" in extra_attributes:
                brightness = state.attributes.get("brightness")
                if brightness is not None:
                    attributes.append(f"{int(brightness * 100 / 255)}%")
            
            # Color
            if state.domain == "light" and "rgb_color" in extra_attributes:
                rgb_color = state.attributes.get("rgb_color")
                if rgb_color:
                    color_name = closest_color(tuple(rgb_color))
                    attributes.append(color_name)
            
            # Temperature
            if "temperature" in extra_attributes:
                temp = state.attributes.get("temperature")
                if temp is not None:
                    attributes.append(f"{temp}°")
            
            # Current temperature
            if "current_temperature" in extra_attributes:
                temp = state.attributes.get("current_temperature")
                if temp is not None:
                    attributes.append(f"current:{temp}°")
            
            # Target temperature
            if "target_temperature" in extra_attributes:
                temp = state.attributes.get("target_temperature")
                if temp is not None:
                    attributes.append(f"target:{temp}°")
            
            # Humidity
            if "humidity" in extra_attributes:
                humidity = state.attributes.get("humidity")
                if humidity is not None:
                    attributes.append(f"{humidity}%RH")
            
            # Fan mode
            if "fan_mode" in extra_attributes:
                fan_mode = state.attributes.get("fan_mode")
                if fan_mode:
                    attributes.append(f"fan:{fan_mode}")
            
            # HVAC mode
            if "hvac_mode" in extra_attributes:
                hvac_mode = state.attributes.get("hvac_mode")
                if hvac_mode:
                    attributes.append(f"hvac:{hvac_mode}")
            
            # HVAC action
            if "hvac_action" in extra_attributes:
                hvac_action = state.attributes.get("hvac_action")
                if hvac_action:
                    attributes.append(f"action:{hvac_action}")
            
            # Preset mode
            if "preset_mode" in extra_attributes:
                preset = state.attributes.get("preset_mode")
                if preset:
                    attributes.append(f"preset:{preset}")
            
            # Media title
            if "media_title" in extra_attributes:
                media_title = state.attributes.get("media_title")
                if media_title:
                    attributes.append(f"playing:{media_title}")
            
            # Media artist
            if "media_artist" in extra_attributes:
                media_artist = state.attributes.get("media_artist")
                if media_artist:
                    attributes.append(f"artist:{media_artist}")
            
            # Volume level
            if "volume_level" in extra_attributes:
                volume = state.attributes.get("volume_level")
                if volume is not None:
                    attributes.append(f"vol:{int(volume * 100)}%")
            
            devices.append(DeviceInfo(
                entity_id=state.entity_id,
                name=state.attributes.get("friendly_name", state.entity_id),
                state=state.state,
                area_id=area_id,
                area_name=area_name,
                attributes=attributes
            ))
        
        return devices

    async def _generate_system_prompt(
        self,
        prompt_template: str,
        llm_api: llm.APIInstance | None,
        options: dict[str, Any]
    ) -> str:
        """Generate the system prompt with device information."""
        from datetime import datetime
        
        language = options.get(CONF_SELECTED_LANGUAGE, DEFAULT_SELECTED_LANGUAGE)
        
        # Get persona and date prompts
        persona_prompt = PERSONA_PROMPTS.get(language, PERSONA_PROMPTS["en"])
        date_prompt_template = CURRENT_DATE_PROMPT.get(language, CURRENT_DATE_PROMPT["en"])
        devices_template = DEVICES_PROMPT.get(language, DEVICES_PROMPT["en"])
        
        # Get current date/time and format it
        current_datetime = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
        date_prompt = date_prompt_template.replace("<current_date>", current_datetime)
        
        # Get exposed devices
        devices = self._get_exposed_entities()
        
        _LOGGER.info("Found %d exposed devices for system prompt", len(devices))
        
        # First, render the devices section with Jinja
        try:
            devices_rendered = template.Template(devices_template, self.hass).async_render(
                {"devices": [d.__dict__ for d in devices]},
                parse_result=False
            )
        except TemplateError as err:
            _LOGGER.error("Error rendering devices template: %s", err)
            raise
        
        # Now replace placeholders in the main prompt template
        prompt = prompt_template
        prompt = prompt.replace("<persona>", persona_prompt)
        prompt = prompt.replace("<current_date>", date_prompt)
        prompt = prompt.replace("<devices>", devices_rendered)
        
        _LOGGER.info("Generated system prompt with %d characters", len(prompt))
        
        return prompt

    def _format_tools_for_bedrock(self, llm_api: llm.APIInstance | None) -> list[dict[str, Any]]:
        """Format Home Assistant tools for Bedrock tool use."""
        if not llm_api or not llm_api.tools:
            return []
        
        bedrock_tools = []
        
        for tool in llm_api.tools:
            # Use Anthropic Messages API format (not Converse API)
            tool_def = {
                "name": tool.name,
                "description": tool.description,
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
            
            # Convert voluptuous schema to JSON schema
            if hasattr(tool, 'parameters') and tool.parameters:
                # For HassCallService tool
                if tool.name == SERVICE_TOOL_NAME:
                    tool_def["input_schema"] = {
                        "type": "object",
                        "properties": {
                            "service": {
                                "type": "string",
                                "description": "The service to call (e.g., 'light.turn_on')"
                            },
                            "target_device": {
                                "type": "string",
                                "description": "The entity_id of the device to control"
                            },
                            "brightness": {
                                "type": "number",
                                "description": "Brightness level (0-255)"
                            },
                            "rgb_color": {
                                "type": "string",
                                "description": "RGB color as comma-separated values (e.g., '255,0,0')"
                            },
                            "temperature": {
                                "type": "number",
                                "description": "Temperature setting"
                            },
                            "humidity": {
                                "type": "number",
                                "description": "Humidity setting"
                            },
                            "fan_mode": {
                                "type": "string",
                                "description": "Fan mode setting"
                            },
                            "hvac_mode": {
                                "type": "string",
                                "description": "HVAC mode setting"
                            },
                            "preset_mode": {
                                "type": "string",
                                "description": "Preset mode"
                            },
                            "item": {
                                "type": "string",
                                "description": "Item to add to a list"
                            },
                            "duration": {
                                "type": "string",
                                "description": "Duration for the action"
                            }
                        },
                        "required": ["service", "target_device"]
                    }
            
            bedrock_tools.append(tool_def)
        
        _LOGGER.info("Formatted %d tool(s) for Bedrock", len(bedrock_tools))
        return bedrock_tools


    def _build_bedrock_messages(
        self,
        conversation_content: list[conversation.Content]
    ) -> list[dict[str, Any]]:
        """Convert Home Assistant conversation to Bedrock message format."""
        messages = []
        
        # First pass: pair each tool_call with the correct ToolResultContent's
        # tool_call_id. Tools can appear multiple times in one assistant turn
        # (e.g. two HassCallService calls), so we need to match in order and
        # consume results as we go — matching by tool_name alone would reuse
        # the same id and produce duplicate tool_use blocks, which Bedrock
        # rejects ("tool_use ids must be unique").
        tool_call_to_id: dict[int, str] = {}
        for idx, content in enumerate(conversation_content):
            if not (isinstance(content, conversation.AssistantContent) and content.tool_calls):
                continue

            # Collect the ToolResultContent entries that belong to this turn
            # (everything after it until the next AssistantContent).
            turn_results: list[conversation.ToolResultContent] = []
            for future_idx in range(idx + 1, len(conversation_content)):
                future_content = conversation_content[future_idx]
                if isinstance(future_content, conversation.ToolResultContent):
                    turn_results.append(future_content)
                elif isinstance(future_content, conversation.AssistantContent):
                    break

            # Match calls to results by tool_name, in order, consuming each result once.
            consumed: set[int] = set()
            for tool_call in content.tool_calls:
                for result_idx, result in enumerate(turn_results):
                    if result_idx in consumed:
                        continue
                    if result.tool_name == tool_call.tool_name:
                        tool_call_to_id[id(tool_call)] = result.tool_call_id
                        consumed.add(result_idx)
                        break

        fallback_counter = 0
        for content in conversation_content:
            if isinstance(content, conversation.SystemContent):
                # System prompt is handled separately in Bedrock
                continue
            
            elif isinstance(content, conversation.UserContent):
                messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": content.content}]
                })
            
            elif isinstance(content, conversation.AssistantContent):
                message_content = []
                
                if content.content:
                    message_content.append({"type": "text", "text": content.content})
                
                if content.tool_calls:
                    for tool_call in content.tool_calls:
                        tool_use_id = tool_call_to_id.get(id(tool_call))
                        if tool_use_id is None:
                            fallback_counter += 1
                            tool_use_id = f"tool_fallback_{fallback_counter}"
                        message_content.append({
                            "type": "tool_use",
                            "id": tool_use_id,
                            "name": tool_call.tool_name,
                            "input": tool_call.tool_args
                        })
                
                if message_content:
                    messages.append({
                        "role": "assistant",
                        "content": message_content
                    })
            
            elif isinstance(content, conversation.ToolResultContent):
                # Tool results go in user messages in Bedrock
                # Convert tool result to proper content format
                # If it's a dict/object, send as JSON text; otherwise send as text
                tool_result_data = content.tool_result
                if isinstance(tool_result_data, dict):
                    # For dict results, serialize to text to avoid confusion
                    import json as json_module
                    result_text = json_module.dumps(tool_result_data)
                    tool_result_content = [{"type": "text", "text": result_text}]
                else:
                    # For string results, send as text
                    tool_result_content = [{"type": "text", "text": str(tool_result_data)}]
                
                tool_result_block = {
                    "type": "tool_result",
                    "tool_use_id": content.tool_call_id,
                    "content": tool_result_content
                }
                
                if messages and messages[-1]["role"] == "user":
                    # Append to last user message
                    messages[-1]["content"].append(tool_result_block)
                else:
                    # Create new user message
                    messages.append({
                        "role": "user",
                        "content": [tool_result_block]
                    })
        
        return messages

    async def async_generate(
        self,
        conversation_content: list[conversation.Content],
        llm_api: llm.APIInstance | None,
        agent_id: str,
        options: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate a response from Bedrock."""
        # Ensure client is initialized before use
        await self._ensure_client()
        
        model_id = options.get(CONF_MODEL_ID, DEFAULT_MODEL_ID)
        # HA's NumberSelector always returns floats even when step=1; Bedrock's
        # Anthropic schema requires max_tokens to be an int.
        max_tokens = int(options.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS))
        temperature = float(options.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE))

        # Extract system prompt
        system_prompt = None
        for content in conversation_content:
            if isinstance(content, conversation.SystemContent):
                system_prompt = content.content
                break
        
        _LOGGER.info("System prompt: %d characters", len(system_prompt) if system_prompt else 0)
        
        # Build messages
        messages = self._build_bedrock_messages(conversation_content)
        _LOGGER.info("Built %d message(s) for Bedrock", len(messages))
        
        # Build request using Anthropic Messages API format (snake_case)
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages
        }
        
        # System prompt should be a string, not a list
        if system_prompt:
            request_body["system"] = system_prompt
        
        # Add tools if available
        tools = self._format_tools_for_bedrock(llm_api)
        if tools:
            request_body["tools"] = tools
            _LOGGER.info("Added %d tool(s) to request", len(tools))
        
        try:
            _LOGGER.info("Calling Bedrock model: %s", model_id)
            
            # Define a function that does both the invoke AND the read in the executor
            def invoke_and_read():
                response = self._bedrock_runtime.invoke_model(
                    modelId=model_id,
                    body=json.dumps(request_body)
                )
                # Read the response body in the executor thread to avoid blocking
                # The StreamingBody must be fully consumed in one go to avoid corruption
                body_stream = response['body']
                
                # Read all chunks to ensure we get the complete response
                chunks = []
                while True:
                    chunk = body_stream.read(8192)  # Read in 8KB chunks
                    if not chunk:
                        break
                    chunks.append(chunk)
                
                response_bytes = b''.join(chunks)
                _LOGGER.debug("Response bytes length: %d", len(response_bytes))
                
                # Decode to UTF-8 string
                response_text = response_bytes.decode('utf-8')
                _LOGGER.debug("Response text length: %d", len(response_text))
                
                # Parse JSON
                parsed_response = json.loads(response_text)
                
                # Log first content block if available for debugging
                if 'content' in parsed_response and len(parsed_response['content']) > 0:
                    first_block = parsed_response['content'][0]
                    if first_block.get('type') == 'text':
                        text_preview = first_block.get('text', '')[:200]
                        _LOGGER.debug("Raw Bedrock text preview: %r", text_preview)
                        # Also log the character codes to check for corruption
                        char_codes = [ord(c) for c in text_preview[:50]]
                        _LOGGER.debug("Character codes: %s", char_codes)
                
                return parsed_response
            
            # Add timeout protection for Bedrock API calls
            try:
                async with asyncio.timeout(30.0):
                    response_body = await self.hass.async_add_executor_job(invoke_and_read)
            except asyncio.TimeoutError:
                error_msg = "Bedrock API call timed out after 30 seconds"
                _LOGGER.error("%s", error_msg)
                raise HomeAssistantError(error_msg)
            
            # Log the full response for debugging
            # Note: Bedrock uses snake_case (stop_reason), not camelCase (stopReason)
            stop_reason = response_body.get('stop_reason')
            _LOGGER.info("Received response from Bedrock (stop_reason: %s)", stop_reason)
            
            # Log warning if stop_reason is missing
            if stop_reason is None:
                _LOGGER.warning("Bedrock response missing 'stop_reason' field. Full response keys: %s", list(response_body.keys()))
                _LOGGER.debug("Full response body: %s", response_body)
            
            return response_body
            
        except ClientError as err:
            _LOGGER.error("AWS Bedrock error: %s", err, exc_info=True)
            raise HomeAssistantError(f"Bedrock API error: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error calling Bedrock")
            raise HomeAssistantError(f"Unexpected error: {err}") from err
