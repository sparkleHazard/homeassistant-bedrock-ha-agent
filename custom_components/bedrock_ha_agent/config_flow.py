"""Config flow for Bedrock Home Assistant Agent integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from botocore.exceptions import (
    ClientError,
    NoCredentialsError,
    BotoCoreError,
)

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import llm, selector

from .aws_session import build_session
from .const import (
    AVAILABLE_MODELS,
    CONF_AWS_ACCESS_KEY_ID,
    CONF_AWS_REGION,
    CONF_AWS_SECRET_ACCESS_KEY,
    CONF_AWS_SESSION_TOKEN,
    CONF_CONFIG_APPROVAL_TTL_SECONDS,
    CONF_CONFIG_UNDO_DEPTH,
    CONF_CONFIG_UNDO_TTL_SECONDS,
    CONF_ENABLE_CONFIG_EDITING,
    CONFIG_APPROVAL_TTL_MAX,
    CONFIG_APPROVAL_TTL_MIN,
    CONFIG_UNDO_DEPTH_MAX,
    CONFIG_UNDO_DEPTH_MIN,
    CONFIG_UNDO_TTL_MAX,
    CONFIG_UNDO_TTL_MIN,
    DEFAULT_CONFIG_APPROVAL_TTL_SECONDS,
    DEFAULT_CONFIG_UNDO_DEPTH,
    DEFAULT_CONFIG_UNDO_TTL_SECONDS,
    DEFAULT_ENABLE_CONFIG_EDITING,
    CONF_EXTRA_ATTRIBUTES_TO_EXPOSE,
    CONF_LLM_HASS_API,
    CONF_MAX_TOKENS,
    CONF_MAX_TOOL_CALL_ITERATIONS,
    CONF_MODEL_ID,
    CONF_PROMPT,
    CONF_REFRESH_SYSTEM_PROMPT,
    CONF_REMEMBER_CONVERSATION,
    CONF_REMEMBER_NUM_INTERACTIONS,
    CONF_TEMPERATURE,
    CONF_TTS_ENGINE,
    CONF_TTS_VOICE_ID,
    DEFAULT_AWS_REGION,
    DEFAULT_EXTRA_ATTRIBUTES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_TOOL_CALL_ITERATIONS,
    DEFAULT_MODEL_ID,
    DEFAULT_PROMPT,
    DEFAULT_REFRESH_SYSTEM_PROMPT,
    DEFAULT_REMEMBER_CONVERSATION,
    DEFAULT_REMEMBER_NUM_INTERACTIONS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TTS_ENGINE,
    DEFAULT_TTS_VOICE_ID,
    DOMAIN,
    FALLBACK_TTS_VOICES,
    TTS_ENGINES,
    HOME_LLM_API_ID,
    CONF_AUTO_ATTACH_CAMERAS,
    DEFAULT_AUTO_ATTACH_CAMERAS,
    CONF_EXPOSE_AREAS_ONLY,
    DEFAULT_EXPOSE_AREAS_ONLY,
    CONF_DEVICE_PROMPT_MODE,
    DEFAULT_DEVICE_PROMPT_MODE,
    DEVICE_PROMPT_MODES,
    CONF_MAX_PROMPT_TOKENS,
    DEFAULT_MAX_PROMPT_TOKENS,
    get_model_max_tokens,
)

_LOGGER = logging.getLogger(__name__)


async def fetch_claude_inference_profiles(
    hass: HomeAssistant,
    aws_region: str,
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: str | None = None,
) -> list[str]:
    """Return sorted, active Anthropic inference profile IDs available in this account/region.

    Inference profile IDs (e.g. ``us.anthropic.claude-haiku-4-5-...``) are what actually
    work with on-demand ``InvokeModel`` in most regions — raw foundation model IDs
    typically return "use inference profile ID" validation errors.

    Returns an empty list if the API call succeeds but no Anthropic profiles are present.
    Raises on API errors so the caller can fall back to a hardcoded list.
    """

    def _list() -> list[str]:
        session = build_session(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
            aws_region=aws_region,
        )
        client = session.client("bedrock")

        profile_ids: list[str] = []
        paginator = client.get_paginator("list_inference_profiles")
        for page in paginator.paginate():
            for summary in page.get("inferenceProfileSummaries", []):
                profile_id = summary.get("inferenceProfileId")
                status = summary.get("status")
                if not profile_id or status != "ACTIVE":
                    continue
                if "anthropic" not in profile_id.lower():
                    continue
                profile_ids.append(profile_id)

        return sorted(set(profile_ids))

    return await hass.async_add_executor_job(_list)


async def fetch_polly_voices(
    hass: HomeAssistant,
    aws_region: str,
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: str | None = None,
    engine: str | None = None,
) -> list[str]:
    """Return sorted unique Polly voice IDs available in the account/region.

    If ``engine`` is provided, only voices whose ``SupportedEngines`` include
    that engine are returned. Raises on API errors so callers can fall back to
    ``FALLBACK_TTS_VOICES``.
    """

    def _list() -> list[str]:
        session = build_session(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
            aws_region=aws_region,
        )
        polly = session.client("polly")
        voice_ids: list[str] = []
        paginator = polly.get_paginator("describe_voices")
        for page in paginator.paginate():
            for voice in page.get("Voices", []):
                voice_id = voice.get("Id")
                if not voice_id:
                    continue
                if engine and engine not in (voice.get("SupportedEngines") or []):
                    continue
                voice_ids.append(voice_id)
        return sorted(set(voice_ids))

    return await hass.async_add_executor_job(_list)


async def validate_aws_credentials(hass: HomeAssistant, aws_access_key_id: str, aws_secret_access_key: str, aws_session_token: str | None = None, aws_region: str | None = None) -> dict[str, str] | None:
    """Validate AWS credentials by attempting to list foundation models."""
    if aws_region is None:
        aws_region = DEFAULT_AWS_REGION
    
    try:
        # Run boto3 client creation in executor to avoid blocking
        def _create_client():
            session = build_session(
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                aws_session_token=aws_session_token,
                aws_region=aws_region,
            )
            return session.client("bedrock")

        bedrock_client = await hass.async_add_executor_job(_create_client)
        
        # Try to list foundation models to verify credentials work
        await hass.async_add_executor_job(bedrock_client.list_foundation_models)
        return None
        
    except NoCredentialsError as e:
        _LOGGER.debug("Caught NoCredentialsError: %s", e)
        return {"base": "invalid_credentials"}
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        _LOGGER.debug("Caught ClientError with code %s: %s", error_code, e)
        if error_code == "UnrecognizedClientException":
            return {"base": "invalid_credentials"}
        elif error_code == "AccessDeniedException":
            return {"base": "access_denied"}
        else:
            _LOGGER.error("Unexpected error validating AWS credentials: %s", e)
            return {"base": "unknown"}
    except BotoCoreError as e:
        _LOGGER.debug("Caught BotoCoreError: %s", e)
        _LOGGER.error("BotoCore error validating AWS credentials: %s", e)
        return {"base": "unknown"}
    except Exception as e:
        _LOGGER.debug("Caught unexpected Exception: %s", e)
        _LOGGER.error("Unknown error validating AWS credentials: %s", e)
        return {"base": "unknown"}


class BedrockConversationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bedrock Home Assistant Agent."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow state."""
        self._credentials: dict[str, Any] = {}
        self._model_options: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 1: collect and validate AWS credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            validation_error = await validate_aws_credentials(
                self.hass,
                user_input[CONF_AWS_ACCESS_KEY_ID],
                user_input[CONF_AWS_SECRET_ACCESS_KEY],
                user_input.get(CONF_AWS_SESSION_TOKEN),
                user_input.get(CONF_AWS_REGION),
            )

            if validation_error:
                errors.update(validation_error)
            else:
                self._credentials = {
                    CONF_AWS_REGION: user_input.get(CONF_AWS_REGION, DEFAULT_AWS_REGION),
                    CONF_AWS_ACCESS_KEY_ID: user_input[CONF_AWS_ACCESS_KEY_ID],
                    CONF_AWS_SECRET_ACCESS_KEY: user_input[CONF_AWS_SECRET_ACCESS_KEY],
                    CONF_AWS_SESSION_TOKEN: user_input.get(CONF_AWS_SESSION_TOKEN, ""),
                }

                try:
                    self._model_options = await fetch_claude_inference_profiles(
                        self.hass,
                        self._credentials[CONF_AWS_REGION],
                        self._credentials[CONF_AWS_ACCESS_KEY_ID],
                        self._credentials[CONF_AWS_SECRET_ACCESS_KEY],
                        self._credentials.get(CONF_AWS_SESSION_TOKEN) or None,
                    )
                except Exception as err:  # noqa: BLE001 — fall back to built-in list
                    _LOGGER.warning(
                        "Could not list Bedrock inference profiles during setup, "
                        "falling back to built-in model list: %s",
                        err,
                    )
                    self._model_options = []

                if not self._model_options:
                    self._model_options = list(AVAILABLE_MODELS)

                return await self.async_step_model()

        data_schema = vol.Schema({
            vol.Required(CONF_AWS_REGION, default=DEFAULT_AWS_REGION): str,
            vol.Required(CONF_AWS_ACCESS_KEY_ID): str,
            vol.Required(CONF_AWS_SECRET_ACCESS_KEY): str,
            vol.Optional(CONF_AWS_SESSION_TOKEN): str,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 2: pick a Bedrock model."""
        if user_input is not None:
            title = f"Bedrock Home Assistant Agent ({self._credentials[CONF_AWS_REGION]})"
            return self.async_create_entry(
                title=title,
                data=self._credentials,
                options={
                    CONF_MODEL_ID: user_input[CONF_MODEL_ID],
                    CONF_PROMPT: DEFAULT_PROMPT,
                    CONF_MAX_TOKENS: DEFAULT_MAX_TOKENS,
                    CONF_TEMPERATURE: DEFAULT_TEMPERATURE,
                    CONF_REFRESH_SYSTEM_PROMPT: DEFAULT_REFRESH_SYSTEM_PROMPT,
                    CONF_REMEMBER_CONVERSATION: DEFAULT_REMEMBER_CONVERSATION,
                    CONF_REMEMBER_NUM_INTERACTIONS: DEFAULT_REMEMBER_NUM_INTERACTIONS,
                    CONF_MAX_TOOL_CALL_ITERATIONS: DEFAULT_MAX_TOOL_CALL_ITERATIONS,
                    CONF_EXTRA_ATTRIBUTES_TO_EXPOSE: DEFAULT_EXTRA_ATTRIBUTES,
                    CONF_LLM_HASS_API: HOME_LLM_API_ID,
                },
            )

        model_schema = vol.Schema({
            vol.Required(CONF_MODEL_ID): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=self._model_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                )
            ),
        })

        return self.async_show_form(
            step_id="model",
            data_schema=model_schema,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return BedrockConversationOptionsFlow()


class BedrockConversationOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Bedrock Home Assistant Agent."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Clamp max_tokens to the chosen model's known limit.
            picked_model = user_input.get(CONF_MODEL_ID)
            model_limit = get_model_max_tokens(picked_model)
            if CONF_MAX_TOKENS in user_input:
                requested = int(user_input[CONF_MAX_TOKENS])
                if requested > model_limit:
                    user_input[CONF_MAX_TOKENS] = model_limit
            # NumberSelector returns floats — coerce the int-semantic one.
            if CONF_MAX_PROMPT_TOKENS in user_input:
                user_input[CONF_MAX_PROMPT_TOKENS] = int(user_input[CONF_MAX_PROMPT_TOKENS])
            return self.async_create_entry(title="", data=user_input)

        # Get available LLM APIs
        llm_api_ids = [
            api.id for api in llm.async_get_apis(self.hass) 
            if api.id != "nlsql"  # Exclude nlsql as it requires special setup
        ]
        
        # Ensure we always have at least the default API in the list
        if HOME_LLM_API_ID not in llm_api_ids:
            llm_api_ids.append(HOME_LLM_API_ID)
        
        # If list is still empty, add a fallback
        if not llm_api_ids:
            llm_api_ids = [HOME_LLM_API_ID]
        
        current_model = self.config_entry.options.get(CONF_MODEL_ID, DEFAULT_MODEL_ID)

        # Prefer a live list of Anthropic inference profiles. Fall back to the
        # hardcoded AVAILABLE_MODELS on any error so the options flow always opens.
        model_options: list[str] = []
        try:
            data = self.config_entry.data
            fetched = await fetch_claude_inference_profiles(
                self.hass,
                data.get(CONF_AWS_REGION, DEFAULT_AWS_REGION),
                data[CONF_AWS_ACCESS_KEY_ID],
                data[CONF_AWS_SECRET_ACCESS_KEY],
                data.get(CONF_AWS_SESSION_TOKEN),
            )
            model_options = fetched
        except Exception as err:  # noqa: BLE001 — non-fatal; fall back below
            _LOGGER.warning(
                "Could not fetch Bedrock inference profiles dynamically, "
                "falling back to built-in list: %s",
                err,
            )

        if not model_options:
            model_options = list(AVAILABLE_MODELS)

        if current_model not in model_options:
            model_options.append(current_model)

        # Polly voice list — fetch live, fall back to the built-in shortlist.
        current_voice = self.config_entry.options.get(
            CONF_TTS_VOICE_ID, DEFAULT_TTS_VOICE_ID
        )
        current_engine = self.config_entry.options.get(
            CONF_TTS_ENGINE, DEFAULT_TTS_ENGINE
        )
        voice_options: list[str] = []
        try:
            voice_options = await fetch_polly_voices(
                self.hass,
                self.config_entry.data.get(CONF_AWS_REGION, DEFAULT_AWS_REGION),
                self.config_entry.data[CONF_AWS_ACCESS_KEY_ID],
                self.config_entry.data[CONF_AWS_SECRET_ACCESS_KEY],
                self.config_entry.data.get(CONF_AWS_SESSION_TOKEN),
                engine=current_engine,
            )
        except Exception as err:  # noqa: BLE001 — non-fatal
            _LOGGER.warning(
                "Could not fetch Polly voices dynamically, "
                "falling back to built-in list: %s",
                err,
            )

        if not voice_options:
            voice_options = list(FALLBACK_TTS_VOICES)
        if current_voice not in voice_options:
            voice_options.append(current_voice)

        options_schema = vol.Schema({
            vol.Optional(
                CONF_MODEL_ID,
                default=current_model
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=model_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                )
            ),
            vol.Optional(
                CONF_PROMPT,
                default=self.config_entry.options.get(CONF_PROMPT, DEFAULT_PROMPT)
            ): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.TEXT,
                    multiline=True,
                )
            ),
            vol.Optional(
                CONF_MAX_TOKENS,
                default=min(
                    self.config_entry.options.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS),
                    get_model_max_tokens(current_model),
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=100,
                    max=get_model_max_tokens(current_model),
                    # Coarse step so the slider stays usable across wildly different
                    # maxes (8 192 for Haiku vs 64 000 for Sonnet).
                    step=max(1, get_model_max_tokens(current_model) // 64),
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_TEMPERATURE,
                default=self.config_entry.options.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=1, step=0.05, mode=selector.NumberSelectorMode.SLIDER
                )
            ),
            vol.Optional(
                CONF_REFRESH_SYSTEM_PROMPT,
                default=self.config_entry.options.get(CONF_REFRESH_SYSTEM_PROMPT, DEFAULT_REFRESH_SYSTEM_PROMPT)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_REMEMBER_CONVERSATION,
                default=self.config_entry.options.get(CONF_REMEMBER_CONVERSATION, DEFAULT_REMEMBER_CONVERSATION)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_REMEMBER_NUM_INTERACTIONS,
                default=self.config_entry.options.get(CONF_REMEMBER_NUM_INTERACTIONS, DEFAULT_REMEMBER_NUM_INTERACTIONS)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=20, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_MAX_TOOL_CALL_ITERATIONS,
                default=self.config_entry.options.get(CONF_MAX_TOOL_CALL_ITERATIONS, DEFAULT_MAX_TOOL_CALL_ITERATIONS)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=10, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_TTS_VOICE_ID,
                default=current_voice
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=voice_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                )
            ),
            vol.Optional(
                CONF_TTS_ENGINE,
                default=current_engine
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=TTS_ENGINES,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_AUTO_ATTACH_CAMERAS,
                default=self.config_entry.options.get(
                    CONF_AUTO_ATTACH_CAMERAS, DEFAULT_AUTO_ATTACH_CAMERAS
                ),
            ): selector.BooleanSelector(),
            # Prompt-size trimming: optionally restrict the device list to
            # specific areas, switch to a lighter-weight rendering, and/or
            # cap the total rendered size. All default to "no change".
            vol.Optional(
                CONF_EXPOSE_AREAS_ONLY,
                default=self.config_entry.options.get(
                    CONF_EXPOSE_AREAS_ONLY, DEFAULT_EXPOSE_AREAS_ONLY
                ),
            ): selector.AreaSelector(
                selector.AreaSelectorConfig(multiple=True)
            ),
            vol.Optional(
                CONF_DEVICE_PROMPT_MODE,
                default=self.config_entry.options.get(
                    CONF_DEVICE_PROMPT_MODE, DEFAULT_DEVICE_PROMPT_MODE
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(DEVICE_PROMPT_MODES),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="device_prompt_mode",
                )
            ),
            vol.Optional(
                CONF_MAX_PROMPT_TOKENS,
                default=self.config_entry.options.get(
                    CONF_MAX_PROMPT_TOKENS, DEFAULT_MAX_PROMPT_TOKENS
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=50000, step=500, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_LLM_HASS_API,
                default=self.config_entry.options.get(CONF_LLM_HASS_API, HOME_LLM_API_ID)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=llm_api_ids,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            # Config editing options (Phase 3)
            vol.Optional(
                CONF_ENABLE_CONFIG_EDITING,
                default=self.config_entry.options.get(
                    CONF_ENABLE_CONFIG_EDITING, DEFAULT_ENABLE_CONFIG_EDITING
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_CONFIG_UNDO_DEPTH,
                default=self.config_entry.options.get(
                    CONF_CONFIG_UNDO_DEPTH, DEFAULT_CONFIG_UNDO_DEPTH
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=CONFIG_UNDO_DEPTH_MIN,
                    max=CONFIG_UNDO_DEPTH_MAX,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_CONFIG_UNDO_TTL_SECONDS,
                default=self.config_entry.options.get(
                    CONF_CONFIG_UNDO_TTL_SECONDS, DEFAULT_CONFIG_UNDO_TTL_SECONDS
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=CONFIG_UNDO_TTL_MIN,
                    max=CONFIG_UNDO_TTL_MAX,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_CONFIG_APPROVAL_TTL_SECONDS,
                default=self.config_entry.options.get(
                    CONF_CONFIG_APPROVAL_TTL_SECONDS, DEFAULT_CONFIG_APPROVAL_TTL_SECONDS
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=CONFIG_APPROVAL_TTL_MIN,
                    max=CONFIG_APPROVAL_TTL_MAX,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema
        )
