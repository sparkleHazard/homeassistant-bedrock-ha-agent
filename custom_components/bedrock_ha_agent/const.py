"Constants for the Bedrock Home Assistant Agent integration."
from typing import Final

DOMAIN: Final = "bedrock_ha_agent"
HOME_LLM_API_ID: Final = f"{DOMAIN}_services"

# AWS Configuration
CONF_AWS_ACCESS_KEY_ID: Final = "aws_access_key_id"
CONF_AWS_SECRET_ACCESS_KEY: Final = "aws_secret_access_key"
CONF_AWS_SESSION_TOKEN: Final = "aws_session_token"
CONF_AWS_REGION: Final = "aws_region"

# Agent configuration
CONF_MODEL_ID: Final = "model"
CONF_PROMPT: Final = "prompt"
CONF_TEMPERATURE: Final = "temperature"
CONF_MAX_TOKENS: Final = "max_tokens"
CONF_REFRESH_SYSTEM_PROMPT: Final = "refresh_prompt_per_turn"
CONF_REMEMBER_CONVERSATION: Final = "remember_conversation"
CONF_REMEMBER_NUM_INTERACTIONS: Final = "remember_num_interactions"
CONF_MAX_TOOL_CALL_ITERATIONS: Final = "max_tool_call_iterations"
CONF_EXTRA_ATTRIBUTES_TO_EXPOSE: Final = "extra_attributes_to_expose"
CONF_LLM_HASS_API: Final = "llm_hass_api"
CONF_SELECTED_LANGUAGE: Final = "selected_language"
CONF_AUTO_ATTACH_CAMERAS: Final = "auto_attach_cameras"
DEFAULT_AUTO_ATTACH_CAMERAS: Final = False

# --- Config editing (new; gated, default off) ---
CONF_ENABLE_CONFIG_EDITING: Final = "enable_config_editing"
DEFAULT_ENABLE_CONFIG_EDITING: Final = False

CONF_CONFIG_UNDO_DEPTH: Final = "config_undo_depth"
DEFAULT_CONFIG_UNDO_DEPTH: Final = 20
CONFIG_UNDO_DEPTH_MIN: Final = 1
CONFIG_UNDO_DEPTH_MAX: Final = 50

CONF_CONFIG_UNDO_TTL_SECONDS: Final = "config_undo_ttl_seconds"
DEFAULT_CONFIG_UNDO_TTL_SECONDS: Final = 3600
CONFIG_UNDO_TTL_MIN: Final = 60
CONFIG_UNDO_TTL_MAX: Final = 86400

CONF_CONFIG_APPROVAL_TTL_SECONDS: Final = "config_approval_ttl_seconds"
DEFAULT_CONFIG_APPROVAL_TTL_SECONDS: Final = 300
CONFIG_APPROVAL_TTL_MIN: Final = 30
CONFIG_APPROVAL_TTL_MAX: Final = 3600

# Approval / undo intent vocabulary (English first; localizable later).
# Lowercase, whitespace-stripped, trailing punctuation removed before matching.
APPROVAL_TOKENS: Final = frozenset({
    "yes", "yep", "yeah", "ok", "okay",
    "apply", "confirm", "sure", "proceed",
})
# "do it" is a two-word phrase matched separately; see BARE_APPROVAL_UTTERANCES.
BARE_APPROVAL_UTTERANCES: Final = frozenset({
    "do it",
})

UNDO_TOKENS: Final = frozenset({"undo", "revert", "cancel"})
BARE_UNDO_UTTERANCES: Final = frozenset({
    "undo",
    "undo that",
    "undo last",
    "undo the last change",
    "revert",
    "revert that",
    "cancel that",
    "cancel that change",
})

# Substrings used by the Haiku-model warning in the options update listener.
HAIKU_MODEL_SUBSTRINGS: Final = (
    "claude-haiku",
    "claude-3-haiku",
    "claude-haiku-4",
)

# Prompt-size trimming options.
CONF_EXPOSE_AREAS_ONLY: Final = "expose_areas_only"   # list[str] of area ids; empty = no filter
CONF_DEVICE_PROMPT_MODE: Final = "device_prompt_mode"  # full | compact | names_only
CONF_MAX_PROMPT_TOKENS: Final = "max_prompt_tokens"    # int; 0 = no cap

DEVICE_PROMPT_MODE_FULL: Final = "full"
DEVICE_PROMPT_MODE_COMPACT: Final = "compact"
DEVICE_PROMPT_MODE_NAMES_ONLY: Final = "names_only"
DEVICE_PROMPT_MODES: Final = (
    DEVICE_PROMPT_MODE_FULL,
    DEVICE_PROMPT_MODE_COMPACT,
    DEVICE_PROMPT_MODE_NAMES_ONLY,
)

DEFAULT_DEVICE_PROMPT_MODE: Final = DEVICE_PROMPT_MODE_FULL
DEFAULT_MAX_PROMPT_TOKENS: Final = 0
DEFAULT_EXPOSE_AREAS_ONLY: Final[list[str]] = []

# Vision-capable Anthropic model substrings. Add to this list when new
# Claude models on Bedrock get image support.
VISION_CAPABLE_MODELS: Final = (
    "claude-sonnet-4-5",
    "claude-3-5-sonnet",
    "claude-3-opus",
    "claude-3-sonnet",
    "claude-3-haiku",  # Claude 3 Haiku supports images; 4.x Haiku does not.
)


def model_supports_vision(model_id: str | None) -> bool:
    """Return True if the given Bedrock model id advertises image input."""
    if not model_id:
        return False
    return any(substr in model_id for substr in VISION_CAPABLE_MODELS)

# Text-to-speech (Amazon Polly)
CONF_TTS_VOICE_ID: Final = "tts_voice_id"
CONF_TTS_ENGINE: Final = "tts_engine"

DEFAULT_TTS_VOICE_ID: Final = "Joanna"
DEFAULT_TTS_ENGINE: Final = "neural"
TTS_ENGINES: Final = ["standard", "neural", "long-form", "generative"]
# Fallback voice list used when polly:DescribeVoices is unavailable.
FALLBACK_TTS_VOICES: Final = [
    "Joanna",
    "Matthew",
    "Ivy",
    "Kendra",
    "Kimberly",
    "Salli",
    "Joey",
    "Justin",
    "Kevin",
    "Ruth",
    "Stephen",
    "Amy",
    "Emma",
    "Brian",
    "Arthur",
]

DEFAULT_MODEL: Final = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
DEFAULT_MODEL_ID: Final = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
DEFAULT_PROMPT: Final = """You are a helpful Home Assistant smart home assistant. Your job is to help users control their smart home devices using natural language, and when they ask you to create or modify automations, scripts, scenes, helpers, Lovelace dashboards, areas, or labels, propose those changes through the config-editing tools.

RUNTIME CONTROL — for turning devices on/off, setting values, triggering scripts, etc.
1. When a user asks to control a device (e.g., "turn on the lamp", "dim the bedroom light"), identify the correct entity_id from the device list below.
2. NEVER ask the user for an entity_id — always find it yourself from the available devices.
3. Match the user's natural language to device names using fuzzy matching (e.g., "lamp" matches devices with "lamp" in the name; "bedroom light" matches lights in the bedroom area).
4. If multiple devices match, choose the most likely one or ask the user to clarify.
5. After identifying the device, call the HassCallService tool with the correct entity_id and service.
6. If no device matches, say what devices are available and ask the user to be more specific.

CONFIGURATION CHANGES — for creating or modifying persistent objects (automations, scripts, scenes, helpers, dashboards, areas, labels).
- NEVER describe the change as YAML in a chat message. Always propose it by calling the matching config tool: ConfigAutomationCreate/Edit/Delete, ConfigScriptCreate/Edit/Delete, ConfigSceneCreate/Edit/Delete, ConfigHelperCreate/Edit/Delete, ConfigLovelaceCardAdd/Remove, ConfigLovelaceDashboardCreate, ConfigAreaCreate/Rename/Delete, ConfigLabelCreate/Rename/Delete, ConfigEntityRename, ConfigEntityAssignArea.
- These tools return status: pending_approval. The change has NOT been applied at that point — describe what you proposed using the proposed_summary field, then ask the user to confirm in plain English ("yes", "apply", "do it"). Wait for their confirmation.
- Do not claim success, completion, or that anything changed until a subsequent tool_result carries status: applied. If the user declines or asks to cancel, acknowledge and stop.

{{current_date}}

{{devices}}"""
DEFAULT_MAX_TOKENS: Final = 4096
DEFAULT_TEMPERATURE: Final = 1.0
DEFAULT_AWS_REGION: Final = "us-west-2"
DEFAULT_REFRESH_SYSTEM_PROMPT: Final = True
DEFAULT_REMEMBER_CONVERSATION: Final = True
DEFAULT_REMEMBER_NUM_INTERACTIONS: Final = 10
DEFAULT_MAX_TOOL_CALL_ITERATIONS: Final = 5
DEFAULT_SELECTED_LANGUAGE: Final = "en"
DEFAULT_EXTRA_ATTRIBUTES: Final = [
    "brightness",
    "rgb_color",
    "temperature",
    "current_temperature",
    "target_temperature",
    "humidity",
    "fan_mode",
    "hvac_mode",
    "hvac_action",
    "preset_mode",
    "media_title",
    "media_artist",
    "volume_level",
]

# Service tool configuration
SERVICE_TOOL_NAME: Final = "HassCallService"
SERVICE_TOOL_ALLOWED_DOMAINS: Final = [
    "light",
    "switch",
    "fan",
    "climate",
    "cover",
    "media_player",
    "lock",
    "script",
    "scene",
    "input_boolean",
    "input_number",
    "input_text",
    "input_select",
    "input_datetime",
    "timer",
]
SERVICE_TOOL_ALLOWED_SERVICES: Final = [
    "light.turn_on",
    "light.turn_off",
    "light.toggle",
    "switch.turn_on",
    "switch.turn_off",
    "switch.toggle",
    "fan.turn_on",
    "fan.turn_off",
    "fan.set_percentage",
    "fan.oscillate",
    "fan.set_direction",
    "fan.set_preset_mode",
    "climate.set_temperature",
    "climate.set_humidity",
    "climate.set_fan_mode",
    "climate.set_hvac_mode",
    "climate.set_preset_mode",
    "cover.open_cover",
    "cover.close_cover",
    "cover.stop_cover",
    "cover.set_cover_position",
    "media_player.turn_on",
    "media_player.turn_off",
    "media_player.toggle",
    "media_player.volume_up",
    "media_player.volume_down",
    "media_player.volume_set",
    "media_player.volume_mute",
    "media_player.media_play",
    "media_player.media_pause",
    "media_player.media_stop",
    "media_player.media_next_track",
    "media_player.media_previous_track",
    "media_player.play_media",
    "lock.lock",
    "lock.unlock",
    "script.turn_on",
    "scene.turn_on",
    "input_boolean.turn_on",
    "input_boolean.turn_off",
    "input_boolean.toggle",
    "input_number.set_value",
    "input_text.set_value",
    "input_select.select_option",
    "input_datetime.set_datetime",
    "timer.start",
    "timer.pause",
    "timer.cancel",
    "timer.finish",
]

ALLOWED_SERVICE_CALL_ARGUMENTS: Final = [
    "brightness",
    "brightness_pct",
    "rgb_color",
    "temperature",
    "humidity",
    "fan_mode",
    "hvac_mode",
    "preset_mode",
    "item",
    "duration",
    "percentage",
    "oscillating",
    "direction",
    "target_temp_high",
    "target_temp_low",
    "position",
    "tilt_position",
    "volume_level",
    "is_volume_muted",
    "media_content_id",
    "media_content_type",
    "value",
    "option",
    "datetime",
]

# ============================================================
# Diagnostics & Control Tool Suite (v1.2)
# ============================================================

CONF_ENABLE_DIAGNOSTICS = "enable_diagnostics"
DEFAULT_ENABLE_DIAGNOSTICS = False

CONF_DIAGNOSTICS_LOG_MAX_LINES = "diagnostics_log_max_lines"
DEFAULT_DIAGNOSTICS_LOG_MAX_LINES = 50  # 10..500

CONF_DIAGNOSTICS_HISTORY_MAX_HOURS = "diagnostics_history_max_hours"
DEFAULT_DIAGNOSTICS_HISTORY_MAX_HOURS = 24  # 1..168

CONF_DIAGNOSTICS_CALL_BUDGET_PER_TURN = "diagnostics_call_budget_per_turn"
DEFAULT_DIAGNOSTICS_CALL_BUDGET_PER_TURN = 3  # 1..10

# Hard caps (not user-configurable in v1)
DIAGNOSTICS_RESPONSE_BYTE_CAP = 64 * 1024  # 64 KiB per tool response

# Redaction list for both called_with payloads and service_response outputs (widened per S2)
DIAGNOSTICS_REDACT_KEYS = frozenset({
    "access_token",
    "password",
    "api_key",
    "auth_token",
    # widened S2
    "bearer_token",
    "bearer",
    "authorization",
    "client_secret",
    "refresh_token",
    "aws_secret_access_key",
    "aws_access_key_id",
    "secret_key",
    "secret",
    "credentials",
    "private_key",
    "authentication_token",
    "cookie",
    "session_id",
    "csrf_token",
    "pin",
    "ssid",
})

# Past-tense lifecycle tokens (used by AC17 confabulation guard, widened per M7/D49)
DIAGNOSTICS_LIFECYCLE_PAST_TENSE_TOKENS = frozenset({
    "reloaded", "restarted", "disabled", "enabled",
})

# Tool-name set used for (a) system-prompt shape detection, (b) flag-off pending sweep.
# Must stay in lockstep with the classes registered by diagnostics/__init__.py.
DIAGNOSTICS_TOOL_NAMES: frozenset[str] = frozenset({
    "DiagnosticsSystemLogList",
    "DiagnosticsLogbookRead",
    "DiagnosticsRepairsList",
    "DiagnosticsHealthCheck",
    "DiagnosticsStateRead",
    "DiagnosticsStateHistory",
    "DiagnosticsStatistics",
    "DiagnosticsIntegrationList",
    "ExtendedServiceCall",
    "DiagnosticsReloadIntegration",
    "DiagnosticsReloadConfigEntry",
    "DiagnosticsEntityEnable",
    "DiagnosticsEntityDisable",
    "DiagnosticsLoggerSetLevel",
    "DiagnosticsCheckConfig",
})

# ExtendedServiceCall classification.
# class: "read_safe" -> immediate execute (no PendingChange).
# class: "mutating"  -> routed through the existing PendingChange -> approve -> apply -> UndoStack.
# Services NOT listed here are denied by default (allowlist, not denylist).
# Keep this list disjoint from SERVICE_TOOL_ALLOWED_SERVICES and from the dedicated
# DiagnosticsLoggerSetLevel tool (no logger.* entries here).
DIAGNOSTICS_ALLOWED_SERVICES: dict[str, dict[str, str]] = {
    # --- read_safe / ambient ---
    "system_log.clear":                {"class": "read_safe", "reason": "In-memory log ring only; no persistent state"},
    "persistent_notification.create":  {"class": "read_safe", "reason": "UI-only; user visible; no entity mutation"},
    "persistent_notification.dismiss": {"class": "read_safe", "reason": "UI-only"},
    "persistent_notification.dismiss_all": {"class": "read_safe", "reason": "UI-only"},
    "zone.reload":                     {"class": "read_safe", "reason": "Reloads zone YAML from storage; no external side-effect"},
    "homeassistant.update_entity":     {"class": "read_safe", "reason": "Forces poll of a single entity; no state write initiated by us"},

    # --- mutating / approval-gated ---
    "automation.trigger":              {"class": "mutating", "reason": "Runs automation actions; real-world side-effects"},
    "automation.turn_on":              {"class": "mutating", "reason": "Enables automation"},
    "automation.turn_off":             {"class": "mutating", "reason": "Disables automation"},
    "automation.toggle":               {"class": "mutating", "reason": "Toggles automation"},
    "script.turn_on":                  {"class": "mutating", "reason": "Runs script sequence"},
    "script.turn_off":                 {"class": "mutating", "reason": "Stops running script"},
    "scene.apply":                     {"class": "mutating", "reason": "Applies scene to entities"},
    "scene.turn_on":                   {"class": "mutating", "reason": "Activates scene"},
    "input_boolean.toggle":            {"class": "mutating", "reason": "Flips helper state"},
    "input_boolean.turn_on":           {"class": "mutating", "reason": "Writes helper state"},
    "input_boolean.turn_off":          {"class": "mutating", "reason": "Writes helper state"},
    "input_button.press":              {"class": "mutating", "reason": "Fires helper event"},
    "timer.start":                     {"class": "mutating", "reason": "Starts timer"},
    "timer.pause":                     {"class": "mutating", "reason": "Pauses timer"},
    "timer.cancel":                    {"class": "mutating", "reason": "Cancels timer"},
    "timer.finish":                    {"class": "mutating", "reason": "Completes timer"},
    "counter.increment":               {"class": "mutating", "reason": "Mutates counter"},
    "counter.decrement":               {"class": "mutating", "reason": "Mutates counter"},
    "counter.reset":                   {"class": "mutating", "reason": "Mutates counter"},
}

# Explicit deny list — backstop even if the allowlist dict is ever expanded by mistake.
DIAGNOSTICS_DENIED_SERVICES: frozenset[str] = frozenset({
    "homeassistant.restart",
    "homeassistant.stop",
    "recorder.purge",
    "recorder.purge_entities",
    "hassio.host_shutdown",
    "hassio.host_reboot",
    "hassio.supervisor_restart",
    "hassio.supervisor_update",
})

AVAILABLE_MODELS: Final = [
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
]

RECOMMENDED_MODELS: Final = AVAILABLE_MODELS

# Per-model output-token limits. Bedrock doesn't expose these via API, so we
# maintain a lookup table. Patterns are matched against the model id as
# substrings, first-match wins — order most specific to most general.
MODEL_TOKEN_LIMITS: Final[tuple[tuple[str, int], ...]] = (
    ("claude-sonnet-4-5", 64000),
    ("claude-haiku-4-5", 8192),
    ("claude-3-5-sonnet", 8192),
    ("claude-3-5-haiku", 8192),
    ("claude-3-opus", 4096),
    ("claude-3-sonnet", 4096),
    ("claude-3-haiku", 4096),
    ("anthropic.claude", 8192),
)
# Generous default for unknown / custom model ids so we don't artificially clamp.
DEFAULT_MODEL_MAX_TOKENS: Final = 64000


def get_model_max_tokens(model_id: str | None) -> int:
    """Return the max output-token limit for ``model_id``.

    Falls back to ``DEFAULT_MODEL_MAX_TOKENS`` for unknown ids.
    """
    if not model_id:
        return DEFAULT_MODEL_MAX_TOKENS
    for pattern, limit in MODEL_TOKEN_LIMITS:
        if pattern in model_id:
            return limit
    return DEFAULT_MODEL_MAX_TOKENS

# Default prompts
PERSONA_PROMPTS = {
    "en": """You are a helpful Home Assistant smart home assistant. Your job is to help users control their smart home devices using natural language.

IMPORTANT INSTRUCTIONS FOR DEVICE CONTROL:
1. When a user asks to control a device (e.g., "turn on the lamp", "dim the bedroom light"), you MUST identify the correct entity_id from the device list below
2. NEVER ask the user for an entity_id - always find it yourself from the available devices
3. Match user's natural language to device names using fuzzy matching:
   - "lamp" matches devices with "lamp" in the name or entity_id
   - "bedroom light" matches lights in the bedroom area or with "bedroom" in the name
   - "living room fan" matches fans in the living room area
4. If multiple devices match, choose the most likely one or ask the user to clarify which specific device they mean
5. After identifying the device, use the HassCallService tool with the correct entity_id and service
6. If you cannot find a matching device, explain what devices are available and ask the user to be more specific

Examples:
- User: "turn on the lamp" → Find entity_id containing "lamp" → Call light.turn_on with that entity_id
- User: "set bedroom temperature to 72" → Find climate entity in bedroom → Call climate.set_temperature
- User: "dim the kitchen lights to 50%" → Find light entity in kitchen → Call light.turn_on with brightness parameter""",
}

# Current date prompt
CURRENT_DATE_PROMPT = {
    "en": "The current date is {{current_date}}.",
}

# Template for devices prompt
DEVICES_PROMPT = {
    "en": """{% if devices %}The user has the following devices:\n\n{% for device in devices %}{% if device.area_name %}[{{ device.area_name }}] {% endif %}{{ device.name }} ({{ device.entity_id }}): {{ device.state }}{% if device.attributes %} ({% for attr in device.attributes %}{{ attr }}{% if not loop.last %}, {% endif %}{% endfor %}){% endif %}\n{% endfor %}{% else %}The user has no exposed devices.{% endif %}""",
}

# Attribute constants
ATTR_ENTITY_ID: Final = "entity_id"
