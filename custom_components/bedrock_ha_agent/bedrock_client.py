"""AWS Bedrock client for conversation agents."""
from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import logging
from dataclasses import dataclass
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
    CONF_DEVICE_PROMPT_MODE,
    CONF_EXPOSE_AREAS_ONLY,
    CONF_EXTRA_ATTRIBUTES_TO_EXPOSE,
    CONF_IMAGE_MODEL_ID,
    CONF_MAX_PROMPT_TOKENS,
    CONF_MAX_TOKENS,
    CONF_MODEL_ID,
    CONF_SELECTED_LANGUAGE,
    CONF_TEMPERATURE,
    CURRENT_DATE_PROMPT,
    DEFAULT_AWS_REGION,
    DEFAULT_DEVICE_PROMPT_MODE,
    DEFAULT_EXPOSE_AREAS_ONLY,
    DEFAULT_EXTRA_ATTRIBUTES,
    DEFAULT_MAX_PROMPT_TOKENS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_ID,
    DEFAULT_SELECTED_LANGUAGE,
    DEFAULT_TEMPERATURE,
    DEVICE_PROMPT_MODE_FULL,
    DEVICES_PROMPT,
    PERSONA_PROMPTS,
    image_model_family,
    model_supports_vision,
)
from .device_info import DeviceInfo, get_exposed_devices, render_devices_section
from .messages import build_bedrock_messages, format_tools_for_bedrock
from .vision import (
    attach_image_to_last_user_message,
    build_camera_metadata,
    fetch_camera_snapshot,
)

_LOGGER = logging.getLogger(__name__)

BedrockConfigEntry = ConfigEntry

# AWS error codes that are worth a second try (transient infrastructure /
# rate-limit conditions, not config/permission errors). These match the
# common retryable set boto3 itself uses internally, plus Bedrock-specific
# stream errors.
_RETRYABLE_ERROR_CODES = frozenset(
    {
        "ThrottlingException",
        "TooManyRequestsException",
        "ServiceUnavailableException",
        "InternalServerException",
        "ModelStreamErrorException",
        "ModelTimeoutException",
    }
)
_RETRY_DELAYS_S = (0.5, 1.0, 2.0)  # 3 attempts max (initial + 2 retries after first)

# Defensive cap on image-response body size. Bedrock typically returns
# ~1-3 MiB per PNG at 1024x1024; 32 MiB leaves plenty of headroom while
# preventing a pathological or spoofed response from OOM'ing HA.
_IMAGE_RESPONSE_MAX_BYTES = 32 * 1024 * 1024


def _friendly_error_message(err: ClientError) -> str:
    """Translate a boto3 ClientError into a voice-friendly sentence."""
    code = err.response.get("Error", {}).get("Code", "") if err.response else ""
    mapping = {
        "ThrottlingException": "I'm being rate-limited right now. Try again in a minute.",
        "TooManyRequestsException": "I'm being rate-limited right now. Try again in a minute.",
        "ServiceUnavailableException": "The AI service is temporarily unavailable. Try again shortly.",
        "InternalServerException": "The AI service hit an internal error. Try again shortly.",
        "ModelStreamErrorException": "The connection to the AI service dropped. Try again.",
        "ModelTimeoutException": "The AI took too long to respond. Try again.",
        "ValidationException": "That request didn't pass the AI service's validation. Check the logs for details.",
        "AccessDeniedException": "My AWS credentials don't have permission for that model.",
        "ResourceNotFoundException": "The selected model isn't available in this AWS region.",
    }
    return mapping.get(code, f"AWS Bedrock error: {err}")


# Re-exported for backward compatibility with earlier imports / tests.
__all__ = ["BedrockClient", "DeviceInfo", "GeneratedImage"]


@dataclass(slots=True)
class GeneratedImage:
    """Result of a Bedrock image-generation call."""

    image_bytes: bytes
    mime_type: str
    width: int
    height: int
    model: str


def _runtime_usage_tracker(entry: ConfigEntry) -> Any:
    """Resolve `entry.runtime_data.usage` defensively.

    `runtime_data` is a `BedrockRuntimeData` dataclass in the shipping
    integration, but some tests set it to None or to a non-dataclass stub.
    Return the `UsageTracker` when present, else None — never raise.
    """
    rd = getattr(entry, "runtime_data", None)
    if rd is None:
        return None
    return getattr(rd, "usage", None)


class BedrockClient:
    """AWS Bedrock client."""

    def __init__(self, hass: HomeAssistant, entry: BedrockConfigEntry) -> None:
        """Initialize the client."""
        self.hass = hass
        self.entry = entry
        self._bedrock_runtime: Any | None = None
        self._client_lock: asyncio.Lock | None = None

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

            # mypy can't track the lock assignment above; assert it's non-None here
            assert self._client_lock is not None
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
        area_filter = self.entry.options.get(
            CONF_EXPOSE_AREAS_ONLY, DEFAULT_EXPOSE_AREAS_ONLY
        ) or None
        return get_exposed_devices(
            self.hass, extra_attributes, area_filter=area_filter
        )

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
        
        # Get current date/time and format it. Accept both the new
        # ``{{current_date}}`` delimiter (added in v1.1.3 to avoid HA's
        # options-flow translation renderer parsing ``<current_date>`` as
        # an unclosed HTML tag) and the legacy ``<current_date>`` form so
        # users who customized the system prompt before v1.1.3 and saved
        # the old syntax keep working.
        current_datetime = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
        date_prompt = (
            date_prompt_template
            .replace("{{current_date}}", current_datetime)
            .replace("<current_date>", current_datetime)
        )
        
        # Get exposed devices
        devices = self._get_exposed_entities()

        _LOGGER.info("Found %d exposed devices for system prompt", len(devices))

        # Choose rendering mode. "full" keeps the existing Jinja template so
        # users who rely on its exact format aren't disturbed; other modes
        # generate a plain-text list via render_devices_section.
        mode = options.get(CONF_DEVICE_PROMPT_MODE, DEFAULT_DEVICE_PROMPT_MODE)
        max_prompt_tokens = int(
            options.get(CONF_MAX_PROMPT_TOKENS, DEFAULT_MAX_PROMPT_TOKENS) or 0
        )

        if mode == DEVICE_PROMPT_MODE_FULL:
            try:
                devices_rendered = template.Template(devices_template, self.hass).async_render(
                    {"devices": [d.__dict__ for d in devices]},
                    parse_result=False,
                )
            except TemplateError as err:
                _LOGGER.error("Error rendering devices template: %s", err)
                raise
            # Apply the soft token cap by char-truncating the already-rendered
            # output; a loose 4-chars/token heuristic is enough for a cap.
            if max_prompt_tokens > 0 and len(devices_rendered) > max_prompt_tokens * 4:
                devices_rendered = (
                    devices_rendered[: max_prompt_tokens * 4]
                    + "\n(devices omitted to stay under the prompt cap)"
                )
        else:
            devices_rendered = render_devices_section(
                devices, mode=mode, max_tokens=max_prompt_tokens
            )
        
        # Now replace placeholders in the main prompt template
        prompt = prompt_template
        # Substitute both the new ``{{token}}`` and legacy ``<token>``
        # delimiters. See v1.1.3 note above: the new syntax dodges HA's
        # options-flow translation renderer's UNCLOSED_TAG error, but
        # existing customized prompts may still carry the old form.
        for old, new in (
            ("{{persona}}", persona_prompt),
            ("<persona>", persona_prompt),
            ("{{current_date}}", date_prompt),
            ("<current_date>", date_prompt),
            ("{{devices}}", devices_rendered),
            ("<devices>", devices_rendered),
        ):
            prompt = prompt.replace(old, new)
        
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

    async def _build_request(
        self,
        conversation_content: list[conversation.Content],
        llm_api: llm.APIInstance | None,
        options: dict[str, Any],
        *,
        attach_images_from_cameras: list[str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Assemble the Bedrock request body shared by streaming + non-streaming paths.

        ``attach_images_from_cameras`` is an optional list of camera entity_ids
        whose current snapshot should be attached to the last user message
        (used by the auto-attach feature). Requires a vision-capable model.
        """
        model_id = options.get(CONF_MODEL_ID, DEFAULT_MODEL_ID)
        # HA's NumberSelector always returns floats even when step=1; Bedrock's
        # Anthropic schema requires max_tokens to be an int.
        max_tokens = int(options.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS))
        temperature = float(options.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE))

        system_prompt = None
        for content in conversation_content:
            if isinstance(content, conversation.SystemContent):
                system_prompt = content.content
                break

        messages = self._build_bedrock_messages(conversation_content)

        # Auto-attach camera snapshots to the last user message.
        if attach_images_from_cameras:
            if not model_supports_vision(model_id):
                _LOGGER.warning(
                    "auto_attach_cameras is on but model %s is not vision-capable; "
                    "dropping snapshots for this turn",
                    model_id,
                )
            else:
                total = len(attach_images_from_cameras)
                for idx, entity_id in enumerate(attach_images_from_cameras, start=1):
                    try:
                        image_bytes, content_type = await fetch_camera_snapshot(
                            self.hass, entity_id
                        )
                    except HomeAssistantError as err:
                        _LOGGER.warning(
                            "Skipping snapshot from %s: %s", entity_id, err
                        )
                        continue
                    metadata_text = build_camera_metadata(
                        self.hass, entity_id, idx, total
                    )
                    messages = attach_image_to_last_user_message(
                        messages, image_bytes, content_type, metadata_text
                    )

        _LOGGER.info(
            "Bedrock request: system=%d chars, messages=%d",
            len(system_prompt) if system_prompt else 0,
            len(messages),
        )

        request_body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }

        # Prompt caching: tag the system prompt and last tool with cache_control.
        if system_prompt:
            request_body["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        tools = self._format_tools_for_bedrock(llm_api)
        if tools:
            tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
            request_body["tools"] = tools
            _LOGGER.info("Added %d tool(s) to request (last one cache-tagged)", len(tools))

        return model_id, request_body

    async def async_generate(
        self,
        conversation_content: list[conversation.Content],
        llm_api: llm.APIInstance | None,
        agent_id: str,
        options: dict[str, Any],
        *,
        attach_images_from_cameras: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate a response from Bedrock."""
        # Ensure client is initialized before use
        await self._ensure_client()

        model_id, request_body = await self._build_request(
            conversation_content, llm_api, options,
            attach_images_from_cameras=attach_images_from_cameras,
        )
        
        try:
            _LOGGER.info("Calling Bedrock model: %s", model_id)
            
            # Define a function that does both the invoke AND the read in the executor
            def invoke_and_read() -> dict[str, Any]:
                assert self._bedrock_runtime is not None  # ensured by _ensure_client
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

                return parsed_response  # type: ignore[no-any-return]  # boto3 response shape is polymorphic
            
            # Add timeout protection for Bedrock API calls + retry on transient errors.
            try:
                async with asyncio.timeout(30.0):
                    response_body = await self._retry_blocking(invoke_and_read)
            except asyncio.TimeoutError:
                error_msg = "Bedrock API call timed out after 30 seconds"
                _LOGGER.error("%s", error_msg)
                tracker = _runtime_usage_tracker(self.entry)
                if tracker is not None:
                    tracker.record_error(error_msg)
                raise HomeAssistantError(error_msg)
            
            # Log the full response for debugging
            # Note: Bedrock uses snake_case (stop_reason), not camelCase (stopReason)
            stop_reason = response_body.get('stop_reason')
            usage = response_body.get("usage", {}) or {}
            _LOGGER.info(
                "Received response from Bedrock "
                "(stop_reason: %s, input=%s, output=%s, cache_read=%s, cache_write=%s)",
                stop_reason,
                usage.get("input_tokens"),
                usage.get("output_tokens"),
                usage.get("cache_read_input_tokens"),
                usage.get("cache_creation_input_tokens"),
            )

            # Fold token usage into the per-entry tracker for the sensor
            # platform. runtime_data may be absent in tests — silently skip.
            tracker = _runtime_usage_tracker(self.entry)
            if tracker is not None:
                tracker.record(model_id, usage)

            # Log warning if stop_reason is missing
            if stop_reason is None:
                _LOGGER.warning("Bedrock response missing 'stop_reason' field. Full response keys: %s", list(response_body.keys()))
                _LOGGER.debug("Full response body: %s", response_body)

            return response_body  # type: ignore[no-any-return]  # boto3 response shape verified at runtime
            
        except ClientError as err:
            _LOGGER.error("AWS Bedrock error: %s", err, exc_info=True)
            friendly = _friendly_error_message(err)
            tracker = _runtime_usage_tracker(self.entry)
            if tracker is not None:
                tracker.record_error(friendly)
            raise HomeAssistantError(friendly) from err
        except Exception as err:
            _LOGGER.exception("Unexpected error calling Bedrock")
            tracker = _runtime_usage_tracker(self.entry)
            if tracker is not None:
                tracker.record_error(str(err))
            raise HomeAssistantError(f"Unexpected error: {err}") from err

    async def async_generate_vision(
        self,
        message: str,
        camera_entity_ids: list[str],
        options: dict[str, Any],
    ) -> str:
        """One-shot Bedrock vision call: fetch snapshot(s), ask a question, return text.

        Refuses if the configured model doesn't support images. No
        conversation history, no tools — just the raw text + image(s).
        """
        await self._ensure_client()
        model_id = options.get(CONF_MODEL_ID, DEFAULT_MODEL_ID)
        if not model_supports_vision(model_id):
            raise HomeAssistantError(
                f"Model {model_id} does not support images. Pick a "
                f"vision-capable Claude Sonnet model."
            )

        if not camera_entity_ids:
            raise HomeAssistantError("ask_with_image requires at least one camera entity")

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": [{"type": "text", "text": message}]}
        ]
        total = len(camera_entity_ids)
        for idx, entity_id in enumerate(camera_entity_ids, start=1):
            image_bytes, content_type = await fetch_camera_snapshot(self.hass, entity_id)
            metadata_text = build_camera_metadata(self.hass, entity_id, idx, total)
            messages = attach_image_to_last_user_message(
                messages, image_bytes, content_type, metadata_text
            )

        request_body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": int(options.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)),
            "temperature": float(options.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)),
            "messages": messages,
        }

        def invoke_and_read() -> dict[str, Any]:
            assert self._bedrock_runtime is not None  # ensured by _ensure_client
            response = self._bedrock_runtime.invoke_model(
                modelId=model_id, body=json.dumps(request_body)
            )
            body_stream = response["body"]
            chunks: list[bytes] = []
            while True:
                chunk = body_stream.read(8192)
                if not chunk:
                    break
                chunks.append(chunk)
            parsed: dict[str, Any] = json.loads(b"".join(chunks).decode("utf-8"))
            return parsed

        try:
            async with asyncio.timeout(30.0):
                response_body = await self._retry_blocking(invoke_and_read)
        except asyncio.TimeoutError:
            raise HomeAssistantError("Bedrock vision request timed out after 30 seconds")
        except ClientError as err:
            friendly = _friendly_error_message(err)
            tracker = _runtime_usage_tracker(self.entry)
            if tracker is not None:
                tracker.record_error(friendly)
            raise HomeAssistantError(friendly) from err

        # Record usage so vision calls show up in the cost sensors too.
        usage = response_body.get("usage", {}) or {}
        tracker = _runtime_usage_tracker(self.entry)
        if tracker is not None:
            tracker.record(model_id, usage)

        # Extract the text reply from content blocks.
        text_parts: list[str] = []
        for block in response_body.get("content", []) or []:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        return "".join(text_parts).strip()

    async def async_generate_image(
        self,
        prompt: str,
        options: dict[str, Any],
        *,
        width: int = 1024,
        height: int = 1024,
    ) -> GeneratedImage:
        """One-shot Bedrock image generation.

        Dispatches on model family (Nova Canvas, Stability, Titan) and returns
        raw PNG bytes plus metadata suitable for ``ai_task.GenImageTaskResult``.
        """
        await self._ensure_client()
        model_id = options.get(CONF_IMAGE_MODEL_ID) or ""
        if not model_id:
            raise HomeAssistantError(
                "No image model selected. Pick one in the Bedrock integration options."
            )
        family = image_model_family(model_id)
        if family is None:
            raise HomeAssistantError(
                f"Unknown image model family for {model_id!r}. Supported prefixes: "
                "amazon.nova-canvas, amazon.titan-image, stability.sd3, stability.stable."
            )

        if family in ("nova", "titan"):
            request_body: dict[str, Any] = {
                "taskType": "TEXT_IMAGE",
                "textToImageParams": {"text": prompt},
                "imageGenerationConfig": {
                    "numberOfImages": 1,
                    "width": int(width),
                    "height": int(height),
                    "cfgScale": 6.5,
                    "seed": 0,
                },
            }
        else:  # stability
            request_body = {
                "prompt": prompt,
                "mode": "text-to-image",
                "aspect_ratio": "1:1",
                "output_format": "png",
            }

        def invoke_and_read() -> dict[str, Any]:
            assert self._bedrock_runtime is not None  # ensured by _ensure_client
            response = self._bedrock_runtime.invoke_model(
                modelId=model_id, body=json.dumps(request_body)
            )
            body_stream = response["body"]
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = body_stream.read(8192)
                if not chunk:
                    break
                total += len(chunk)
                if total > _IMAGE_RESPONSE_MAX_BYTES:
                    raise HomeAssistantError(
                        "Bedrock image response exceeded the 32 MiB size cap."
                    )
                chunks.append(chunk)
            parsed: dict[str, Any] = json.loads(b"".join(chunks).decode("utf-8"))
            return parsed

        try:
            async with asyncio.timeout(60.0):
                response_body = await self._retry_blocking(invoke_and_read)
        except asyncio.TimeoutError as err:
            tracker = _runtime_usage_tracker(self.entry)
            if tracker is not None:
                tracker.record_error("Bedrock image request timed out after 60 seconds")
            raise HomeAssistantError(
                "Bedrock image request timed out after 60 seconds"
            ) from err
        except ClientError as err:
            friendly = _friendly_error_message(err)
            tracker = _runtime_usage_tracker(self.entry)
            if tracker is not None:
                tracker.record_error(friendly)
            raise HomeAssistantError(friendly) from err
        except HomeAssistantError:
            raise
        except Exception as err:
            _LOGGER.exception("Unexpected error generating image")
            tracker = _runtime_usage_tracker(self.entry)
            if tracker is not None:
                tracker.record_error(str(err))
            raise HomeAssistantError(f"Unexpected error: {err}") from err

        # Stability-specific safety filter — check every slot in case the
        # API ever returns multiple images and only some are filtered.
        finish_reasons = response_body.get("finish_reasons") or []
        if "CONTENT_FILTERED" in finish_reasons:
            raise HomeAssistantError(
                "Image was filtered by the model's safety policy."
            )
        # Nova Canvas returns {"error": "<message>"} on refusal.
        nova_error = response_body.get("error")
        if nova_error:
            raise HomeAssistantError(f"Image generation failed: {nova_error}")

        images = response_body.get("images") or []
        if not images or not isinstance(images[0], str):
            raise HomeAssistantError(
                "Bedrock image response had no image data."
            )
        try:
            image_bytes = base64.b64decode(images[0], validate=True)
        except (binascii.Error, ValueError) as err:
            raise HomeAssistantError(
                f"Bedrock returned malformed image data: {err}"
            ) from err

        return GeneratedImage(
            image_bytes=image_bytes,
            mime_type="image/png",
            width=int(width),
            height=int(height),
            model=model_id,
        )

    async def _retry_blocking(self, fn: Any, *args: Any) -> Any:
        """Call a blocking ``fn`` via the executor with retry on transient errors.

        Retryable ``ClientError`` codes are listed in ``_RETRYABLE_ERROR_CODES``;
        backoff follows ``_RETRY_DELAYS_S``. Non-retryable errors (auth,
        validation, etc.) bubble immediately so the caller can surface them.
        """
        last_err: Exception | None = None
        for attempt, delay in enumerate([0.0, *_RETRY_DELAYS_S]):
            if delay:
                _LOGGER.info("Bedrock retry attempt %d after %.1fs backoff", attempt, delay)
                await asyncio.sleep(delay)
            try:
                return await self.hass.async_add_executor_job(fn, *args)
            except ClientError as err:
                code = err.response.get("Error", {}).get("Code", "") if err.response else ""
                if code not in _RETRYABLE_ERROR_CODES:
                    raise
                last_err = err
                _LOGGER.warning(
                    "Bedrock transient error %s (attempt %d/%d)",
                    code, attempt + 1, len(_RETRY_DELAYS_S) + 1,
                )
        # Exhausted retries — re-raise the last transient error.
        assert last_err is not None
        raise last_err

    async def async_generate_stream(
        self,
        conversation_content: list[conversation.Content],
        llm_api: llm.APIInstance | None,
        options: dict[str, Any],
        *,
        attach_images_from_cameras: list[str] | None = None,
    ) -> Any:
        """Yield normalized events from ``invoke_model_with_response_stream``.

        Events (as ``(kind, payload)`` tuples):

        - ``("text_delta", str)``            — incremental text to stream to the user
        - ``("tool_use_start", {"index", "id", "name"})``
        - ``("tool_use_delta", {"index", "partial_json"})``  — input_json_delta chunks
        - ``("message_end", {"stop_reason", "usage": {...}})``

        On error raises ``HomeAssistantError``; iteration stops after
        ``message_end``. Callers can assemble the tool_use blocks by
        concatenating the partial_json strings for each index, then
        ``json.loads``-ing at ``message_end``.
        """
        await self._ensure_client()
        model_id, request_body = await self._build_request(
            conversation_content, llm_api, options,
            attach_images_from_cameras=attach_images_from_cameras,
        )

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any] | object] = asyncio.Queue()
        SENTINEL = object()

        # Open the stream with retry; once we have an EventStream the pump
        # just iterates events on the executor.
        def _open_stream() -> Any:
            assert self._bedrock_runtime is not None  # ensured by _ensure_client
            return self._bedrock_runtime.invoke_model_with_response_stream(
                modelId=model_id, body=json.dumps(request_body)
            )

        try:
            stream_response = await self._retry_blocking(_open_stream)
        except ClientError as err:
            friendly = _friendly_error_message(err)
            tracker = _runtime_usage_tracker(self.entry)
            if tracker is not None:
                tracker.record_error(friendly)
            raise HomeAssistantError(friendly) from err

        def _pump() -> None:
            """Drain Bedrock's EventStream (blocking) into the async queue."""
            try:
                for event in stream_response.get("body"):
                    chunk = event.get("chunk")
                    if not chunk or "bytes" not in chunk:
                        continue
                    try:
                        payload = json.loads(chunk["bytes"].decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as err:
                        loop.call_soon_threadsafe(queue.put_nowait, ("error", err))
                        return
                    loop.call_soon_threadsafe(queue.put_nowait, ("raw", payload))
            except Exception as err:  # noqa: BLE001 — propagate via the queue
                loop.call_soon_threadsafe(queue.put_nowait, ("error", err))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

        pump_task = loop.run_in_executor(None, _pump)

        try:
            # Each content_block in the stream has an index. We track per-index
            # state so the caller can reassemble tool_use blocks from the
            # partial_json deltas. Text blocks emit ("text_delta", str).
            while True:
                item = await queue.get()
                if item is SENTINEL:
                    break
                # mypy can't narrow the union after the SENTINEL check; cast explicitly
                assert isinstance(item, tuple), "non-SENTINEL items are tuples"
                kind: str
                payload: Any
                kind, payload = item
                if kind == "error":
                    if isinstance(payload, ClientError):
                        msg = _friendly_error_message(payload)
                    else:
                        msg = f"Bedrock stream error: {payload}"
                    tracker = _runtime_usage_tracker(self.entry)
                    if tracker is not None:
                        tracker.record_error(msg)
                    raise HomeAssistantError(msg)

                event_type = payload.get("type")
                if event_type == "content_block_start":
                    block = payload.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        yield (
                            "tool_use_start",
                            {
                                "index": payload.get("index", 0),
                                "id": block.get("id"),
                                "name": block.get("name"),
                            },
                        )
                elif event_type == "content_block_delta":
                    delta = payload.get("delta") or {}
                    dt = delta.get("type")
                    if dt == "text_delta":
                        text = delta.get("text") or ""
                        if text:
                            yield ("text_delta", text)
                    elif dt == "input_json_delta":
                        yield (
                            "tool_use_delta",
                            {
                                "index": payload.get("index", 0),
                                "partial_json": delta.get("partial_json", ""),
                            },
                        )
                elif event_type == "message_delta":
                    delta = payload.get("delta") or {}
                    usage = payload.get("usage") or {}
                    if "stop_reason" in delta:
                        # message_delta carries stop_reason + usage on
                        # termination; the subsequent message_stop is empty.
                        # Record usage into the tracker here so the sensors
                        # update even when streaming.
                        tracker = _runtime_usage_tracker(self.entry)
                        if tracker is not None:
                            tracker.record(model_id, usage)
                        yield (
                            "message_end",
                            {"stop_reason": delta.get("stop_reason"), "usage": usage},
                        )
        finally:
            # Drain the pump so the executor thread always exits cleanly, even
            # if we broke out of the loop via `raise` above or an iteration
            # exception propagated. Swallow any pump exception here — if the
            # pump failed mid-stream, the queue's ("error", ...) message has
            # already been yielded and raised by the loop, so re-raising its
            # residual CancelledError / broken-pipe at this point would mask
            # the real error. Letting pump_task finish silently is safe.
            with contextlib.suppress(Exception):
                await pump_task
