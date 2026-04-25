"""AWS Bedrock client for conversation agents."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from botocore.exceptions import ClientError

from homeassistant.core import HomeAssistant
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import (
    HomeAssistantError,
    TemplateError,
)
from homeassistant.helpers import llm, template

from .aws_session import session_from_entry_data
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
)
from .device_info import DeviceInfo, get_exposed_devices
from .messages import build_bedrock_messages, format_tools_for_bedrock

_LOGGER = logging.getLogger(__name__)

BedrockConfigEntry = ConfigEntry

# Re-exported for backward compatibility with earlier imports / tests.
__all__ = ["BedrockClient", "DeviceInfo"]


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
        extra_attributes = self.entry.options.get(
            CONF_EXTRA_ATTRIBUTES_TO_EXPOSE, DEFAULT_EXTRA_ATTRIBUTES
        )
        return get_exposed_devices(self.hass, extra_attributes)

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

    def _format_tools_for_bedrock(
        self, llm_api: llm.APIInstance | None
    ) -> list[dict[str, Any]]:
        """Format Home Assistant tools for Bedrock tool use."""
        return format_tools_for_bedrock(llm_api)

    def _build_bedrock_messages(
        self, conversation_content: list[conversation.Content]
    ) -> list[dict[str, Any]]:
        """Convert Home Assistant conversation to Bedrock message format."""
        return build_bedrock_messages(conversation_content)

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
