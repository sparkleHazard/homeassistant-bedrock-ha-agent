"""Config flow for AWS Bedrock Conversation integration."""
from __future__ import annotations

import logging
from typing import Any

import boto3
import voluptuous as vol
from botocore.exceptions import (
    ClientError,
    NoCredentialsError,
    BotoCoreError,
)

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import llm, selector

from .const import (
    AVAILABLE_MODELS,
    CONF_AWS_ACCESS_KEY_ID,
    CONF_AWS_REGION,
    CONF_AWS_SECRET_ACCESS_KEY,
    CONF_AWS_SESSION_TOKEN,
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
    CONF_TOP_P,
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
    DEFAULT_TOP_P,
    DOMAIN,
    HOME_LLM_API_ID,
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
        session = boto3.Session(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token or None,
            region_name=aws_region,
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


async def validate_aws_credentials(hass: HomeAssistant, aws_access_key_id: str, aws_secret_access_key: str, aws_session_token: str | None = None, aws_region: str | None = None) -> dict[str, str] | None:
    """Validate AWS credentials by attempting to list foundation models."""
    if aws_region is None:
        aws_region = DEFAULT_AWS_REGION
    
    try:
        # Run boto3 client creation in executor to avoid blocking
        def _create_client():
            session = boto3.Session(
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                aws_session_token=aws_session_token,
                region_name=aws_region,
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
    """Handle a config flow for AWS Bedrock Conversation."""

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
            title = f"AWS Bedrock ({self._credentials[CONF_AWS_REGION]})"
            return self.async_create_entry(
                title=title,
                data=self._credentials,
                options={
                    CONF_MODEL_ID: user_input[CONF_MODEL_ID],
                    CONF_PROMPT: DEFAULT_PROMPT,
                    CONF_MAX_TOKENS: DEFAULT_MAX_TOKENS,
                    CONF_TEMPERATURE: DEFAULT_TEMPERATURE,
                    CONF_TOP_P: DEFAULT_TOP_P,
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
    """Handle options flow for AWS Bedrock Conversation."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
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
                default=self.config_entry.options.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=100, max=100000, step=100, mode=selector.NumberSelectorMode.BOX
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
                CONF_TOP_P,
                default=self.config_entry.options.get(CONF_TOP_P, DEFAULT_TOP_P)
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
                CONF_LLM_HASS_API,
                default=self.config_entry.options.get(CONF_LLM_HASS_API, HOME_LLM_API_ID)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=llm_api_ids,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })
        
        return self.async_show_form(
            step_id="init",
            data_schema=options_schema
        )
