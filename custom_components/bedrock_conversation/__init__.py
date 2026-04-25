"""AWS Bedrock Conversation integration."""

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform, ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import llm
import voluptuous as vol
import logging
import asyncio

from .const import (
    ALLOWED_SERVICE_CALL_ARGUMENTS,
    CONF_CONFIG_APPROVAL_TTL_SECONDS,
    CONF_CONFIG_UNDO_DEPTH,
    CONF_CONFIG_UNDO_TTL_SECONDS,
    CONF_ENABLE_CONFIG_EDITING,
    CONF_MODEL_ID,
    DEFAULT_CONFIG_APPROVAL_TTL_SECONDS,
    DEFAULT_CONFIG_UNDO_DEPTH,
    DEFAULT_CONFIG_UNDO_TTL_SECONDS,
    DOMAIN,
    HAIKU_MODEL_SUBSTRINGS,
    HOME_LLM_API_ID,
    SERVICE_TOOL_NAME,
    SERVICE_TOOL_ALLOWED_DOMAINS,
    SERVICE_TOOL_ALLOWED_SERVICES,
)
from .bedrock_client import BedrockClient
from .usage_tracker import UsageTracker
from .runtime_data import BedrockRuntimeData, _get_runtime_data
from ._ha_api_smoke import check_required_ha_apis

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CONVERSATION, Platform.SENSOR, Platform.STT, Platform.TTS]


class HassServiceTool(llm.Tool):
    """Tool for calling Home Assistant services."""

    name = SERVICE_TOOL_NAME
    description = (
        "Calls a Home Assistant service to control a specific device. "
        "You MUST provide the exact entity_id from the device list in the system prompt. "
        "Use this tool after identifying the correct device from the user's natural language request. "
        "For example: if user says 'turn on the lamp', find the entity_id containing 'lamp' from the device list, "
        "then call this tool with service='light.turn_on' and target_device='light.lamp_entity_id'."
    )

    parameters = vol.Schema(
        {
            vol.Required("service"): str,
            vol.Required("target_device"): str,
        }
    )

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the tool."""
        self.hass = hass

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> dict:
        """Call the Home Assistant service."""
        service = tool_input.tool_args.get("service")
        target_device = tool_input.tool_args.get("target_device")

        _LOGGER.info("Tool call: service=%s, device=%s", service, target_device)

        if not service or not target_device:
            error_msg = "Missing required parameters: service and target_device"
            _LOGGER.error("Service call failed: %s", error_msg)
            return {
                "result": "error",
                "error": error_msg,
            }

        try:
            domain, service_name = service.split(".", 1)
        except ValueError:
            error_msg = f"Invalid service format: {service}. Expected 'domain.service'"
            _LOGGER.error("Service call failed: %s", error_msg)
            return {
                "result": "error",
                "error": error_msg,
            }

        if domain not in SERVICE_TOOL_ALLOWED_DOMAINS:
            error_msg = f"Service domain '{domain}' is not allowed"
            _LOGGER.error("Service call failed: %s", error_msg)
            return {
                "result": "error",
                "error": error_msg,
            }

        if service not in SERVICE_TOOL_ALLOWED_SERVICES:
            error_msg = f"Service '{service}' is not allowed"
            _LOGGER.error("Service call failed: %s", error_msg)
            return {
                "result": "error",
                "error": error_msg,
            }

        service_data = {ATTR_ENTITY_ID: target_device}

        for key, value in tool_input.tool_args.items():
            if key in ALLOWED_SERVICE_CALL_ARGUMENTS:
                service_data[key] = value

        _LOGGER.info("Calling service: %s.%s with data: %s", domain, service_name, service_data)

        try:
            async with asyncio.timeout(5.0):
                # Non-blocking to avoid hanging when services run long-running automations.
                await hass.services.async_call(
                    domain,
                    service_name,
                    service_data,
                    blocking=False,
                )

            success_msg = f"Successfully called {service} on {target_device}"
            _LOGGER.info(success_msg)

            return {
                "result": "success",
                "service": service,
                "target": target_device,
                "message": success_msg,
            }
        except asyncio.TimeoutError:
            error_msg = f"Timeout calling service {service} (took more than 5 seconds)"
            _LOGGER.error(error_msg)
            return {
                "result": "error",
                "error": error_msg,
            }
        except Exception as err:
            error_msg = f"Error calling service {service}: {err}"
            _LOGGER.error(error_msg, exc_info=True)
            return {
                "result": "error",
                "error": error_msg,
            }


class BedrockServicesAPI(llm.API):
    """Bedrock Services LLM API."""

    def __init__(self, hass: HomeAssistant, id: str, name: str) -> None:
        """Initialize the API."""
        self.hass = hass
        self.id = id
        self.name = name

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        """Get API instance."""
        from .config_tools import ConfigEditingTool, register_config_tools

        tools = [HassServiceTool(self.hass)]
        api_prompt = (
            "You have access to the HassCallService tool to control Home Assistant devices. "
            "CRITICAL: The device list in the system prompt contains all available devices with their entity_ids. "
            "When the user asks to control a device, YOU MUST: "
            "1. Search the device list for a matching entity based on the user's natural language (e.g., 'lamp', 'bedroom light') "
            "2. Identify the correct entity_id from that list "
            "3. Call HassCallService with the exact entity_id you found "
            "NEVER ask the user for an entity_id - always find it yourself from the provided device list."
        )

        # Resolve the owning config entry at call time
        entry = ConfigEditingTool._resolve_entry(self.hass, llm_context)
        if entry is not None and entry.options.get(CONF_ENABLE_CONFIG_EDITING, False):
            # Append config-editing tools
            config_tools = register_config_tools(self.hass, entry)
            tools.extend(config_tools)

            # Append system-prompt addendum
            api_prompt += (
                "\n\nWhen a config-editing tool returns status: pending_approval, the change has NOT been applied. "
                "Do not claim success, completion, or that anything changed until a subsequent tool_result carries "
                "status: applied. Describe your proposal using the proposed_summary, ask the user to confirm in plain "
                "English (\"yes\", \"apply\", \"do it\", or similar), and wait. If the user declines or asks to revert, "
                "acknowledge and stop."
            )

        return llm.APIInstance(
            api=self,
            api_prompt=api_prompt,
            llm_context=llm_context,
            tools=tools,
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AWS Bedrock Conversation from a config entry."""
    _LOGGER.info("Bedrock setup: starting integration setup")

    # Smoke check: verify all required HA APIs are present
    api_failures = check_required_ha_apis()
    if api_failures:
        error_msg = (
            "Missing required Home Assistant APIs (HA floor: 2025.6.0):\n  - "
            + "\n  - ".join(api_failures)
        )
        _LOGGER.error(error_msg)
        raise ConfigEntryNotReady(error_msg)

    existing_apis = [api.id for api in llm.async_get_apis(hass)]
    if HOME_LLM_API_ID not in existing_apis:
        llm.async_register_api(hass, BedrockServicesAPI(hass, HOME_LLM_API_ID, "AWS Bedrock Services"))
        _LOGGER.info("Bedrock setup: registered Bedrock Services LLM API")

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry

    # Initialize runtime_data with BedrockRuntimeData dataclass
    client = BedrockClient(hass, entry)
    runtime_data = BedrockRuntimeData(bedrock_client=client)
    entry.runtime_data = runtime_data

    # Legacy dict fields for backward compatibility
    entry.runtime_data.client = client  # type: ignore[attr-defined]
    entry.runtime_data.usage = UsageTracker()  # type: ignore[attr-defined]

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Register services once per HA (not per entry)
    if not hass.services.has_service(DOMAIN, "ask_with_image"):
        await _async_register_vision_service(hass)
    if not hass.services.has_service(DOMAIN, "undo_last_config_change"):
        await _async_register_undo_service(hass)

    _LOGGER.info("Bedrock setup: integration setup complete")
    return True


async def _async_register_vision_service(hass: HomeAssistant) -> None:
    """Register the ``bedrock_conversation.ask_with_image`` service."""
    schema = vol.Schema(
        {
            vol.Required("message"): str,
            vol.Required("camera_entity_id"): vol.Any(
                str, vol.All([str], vol.Length(min=1))
            ),
            vol.Optional("config_entry_id"): str,
        }
    )

    async def _handle(call) -> dict:
        message: str = call.data["message"]
        raw = call.data["camera_entity_id"]
        entity_ids: list[str] = [raw] if isinstance(raw, str) else list(raw)

        # Pick a config entry: explicit > single entry > fail if ambiguous.
        entries = list(hass.data.get(DOMAIN, {}).values())
        if not entries:
            raise HomeAssistantError("No Bedrock Conversation config entry set up")
        explicit_id = call.data.get("config_entry_id")
        if explicit_id:
            matched = [e for e in entries if e.entry_id == explicit_id]
            if not matched:
                raise HomeAssistantError(
                    f"No Bedrock Conversation entry with id {explicit_id}"
                )
            entry = matched[0]
        elif len(entries) == 1:
            entry = entries[0]
        else:
            raise HomeAssistantError(
                "Multiple Bedrock Conversation entries configured; pass "
                "config_entry_id to pick one"
            )

        client = entry.runtime_data["client"]
        options = {**entry.data, **entry.options}
        text = await client.async_generate_vision(message, entity_ids, options)
        return {"response": text}

    hass.services.async_register(
        DOMAIN,
        "ask_with_image",
        _handle,
        schema=schema,
        supports_response=SupportsResponse.ONLY,
    )
    _LOGGER.info("Bedrock setup: registered ask_with_image service")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Bedrock unload: unloading integration")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _async_register_undo_service(hass: HomeAssistant) -> None:
    """Register the ``bedrock_conversation.undo_last_config_change`` service."""
    from .config_tools.undo import collect_non_empty_stacks, get_or_create_stack

    schema = vol.Schema(
        {
            vol.Optional("config_entry_id"): str,
            vol.Optional("conversation_id"): str,
        }
    )

    async def _handle(call) -> dict:
        # Resolve entry_id
        explicit_id = call.data.get("config_entry_id")
        entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.state == ConfigEntryState.LOADED
        ]

        if not entries:
            raise HomeAssistantError("No Bedrock Conversation config entry set up")

        if explicit_id:
            matched = [e for e in entries if e.entry_id == explicit_id]
            if not matched:
                raise HomeAssistantError(
                    f"No Bedrock Conversation entry with id {explicit_id}"
                )
            entry = matched[0]
        elif len(entries) == 1:
            entry = entries[0]
        else:
            raise HomeAssistantError(
                "Multiple Bedrock Conversation entries configured; pass "
                "config_entry_id to pick one"
            )

        entry_id = entry.entry_id
        conversation_id = call.data.get("conversation_id")

        # If conversation_id provided, pop from that stack
        if conversation_id:
            stack = get_or_create_stack(
                hass,
                entry_id,
                conversation_id,
                max_depth=int(
                    entry.options.get(CONF_CONFIG_UNDO_DEPTH, DEFAULT_CONFIG_UNDO_DEPTH)
                ),
                ttl_seconds=int(
                    entry.options.get(
                        CONF_CONFIG_UNDO_TTL_SECONDS, DEFAULT_CONFIG_UNDO_TTL_SECONDS
                    )
                ),
            )
            undo_entry = stack.pop_latest()
            if undo_entry is None:
                return {
                    "undone": False,
                    "summary": "Nothing to undo for this conversation.",
                }

            # Execute restore_fn
            try:
                await undo_entry.restore_fn()
            except Exception as err:
                _LOGGER.exception("Undo restore_fn failed: %s", err)
                raise HomeAssistantError(f"Undo failed: {err}") from err

            warnings_str = ""
            if undo_entry.warnings:
                warnings_str = " Note: " + "; ".join(undo_entry.warnings)

            return {
                "undone": True,
                "summary": f"Reverted: {undo_entry.tool_name}.{warnings_str}",
            }

        # No conversation_id provided — check for ambiguity
        non_empty = collect_non_empty_stacks(hass, entry_id)
        if len(non_empty) == 0:
            return {
                "undone": False,
                "summary": "Nothing to undo.",
            }
        if len(non_empty) == 1:
            # Unambiguous — pop from the single stack
            conv_id, stack = next(iter(non_empty.items()))
            undo_entry = stack.pop_latest()
            if undo_entry is None:
                return {
                    "undone": False,
                    "summary": "Nothing to undo.",
                }

            try:
                await undo_entry.restore_fn()
            except Exception as err:
                _LOGGER.exception("Undo restore_fn failed: %s", err)
                raise HomeAssistantError(f"Undo failed: {err}") from err

            warnings_str = ""
            if undo_entry.warnings:
                warnings_str = " Note: " + "; ".join(undo_entry.warnings)

            return {
                "undone": True,
                "summary": f"Reverted: {undo_entry.tool_name}.{warnings_str}",
            }

        # Ambiguous — ≥2 non-empty stacks
        return {
            "undone": False,
            "error": "ambiguous_conversation",
            "conversation_ids": list(non_empty.keys()),
            "summary": (
                f"Multiple conversations have undo history ({len(non_empty)}). "
                "Pass conversation_id to pick one."
            ),
        }

    hass.services.async_register(
        DOMAIN,
        "undo_last_config_change",
        _handle,
        schema=schema,
        supports_response=SupportsResponse.ONLY,
    )
    _LOGGER.info("Bedrock setup: registered undo_last_config_change service")


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    # Check for Haiku model warning
    runtime_data = _get_runtime_data(hass, entry.entry_id)
    flag_on = entry.options.get(CONF_ENABLE_CONFIG_EDITING, False)
    current_model = entry.options.get(CONF_MODEL_ID, "")
    is_haiku = any(substr in current_model for substr in HAIKU_MODEL_SUBSTRINGS)

    # Trigger warning on flag-on + Haiku transition
    should_warn = (
        flag_on
        and is_haiku
        and (
            not runtime_data.last_config_editing_flag
            or runtime_data.last_model_warned_for != current_model
        )
    )

    if should_warn:
        import homeassistant.components.persistent_notification as pn

        await pn.async_create(
            hass,
            message=(
                "Config editing works best on Claude Sonnet 4.5 or Opus; "
                "Haiku may truncate large dashboards."
            ),
            title="Bedrock Conversation: Model advisory",
            notification_id=f"bedrock_haiku_warning_{entry.entry_id}",
        )
        _LOGGER.info(
            "Config editing enabled with Haiku model %s; advisory notification sent",
            current_model,
        )

    # Update tracking state
    runtime_data.last_config_editing_flag = flag_on
    runtime_data.last_model_warned_for = current_model if (flag_on and is_haiku) else None

    _LOGGER.info("Bedrock reload: reloading due to configuration change")
    await hass.config_entries.async_reload(entry.entry_id)
