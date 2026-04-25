"Constants for the AWS Bedrock Conversation integration."
from typing import Final

DOMAIN: Final = "bedrock_conversation"
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
CONF_TOP_P: Final = "top_p"
CONF_MAX_TOKENS: Final = "max_tokens"
CONF_REFRESH_SYSTEM_PROMPT: Final = "refresh_prompt_per_turn"
CONF_REMEMBER_CONVERSATION: Final = "remember_conversation"
CONF_REMEMBER_NUM_INTERACTIONS: Final = "remember_num_interactions"
CONF_MAX_TOOL_CALL_ITERATIONS: Final = "max_tool_call_iterations"
CONF_EXTRA_ATTRIBUTES_TO_EXPOSE: Final = "extra_attributes_to_expose"
CONF_LLM_HASS_API: Final = "llm_hass_api"
CONF_SELECTED_LANGUAGE: Final = "selected_language"

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
DEFAULT_PROMPT: Final = """<persona>

<current_date>

<devices>"""
DEFAULT_MAX_TOKENS: Final = 4096
DEFAULT_TEMPERATURE: Final = 1.0
DEFAULT_TOP_P: Final = 0.999
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
    "en": "The current date is <current_date>.",
}

# Template for devices prompt
DEVICES_PROMPT = {
    "en": """{% if devices %}The user has the following devices:\n\n{% for device in devices %}{% if device.area_name %}[{{ device.area_name }}] {% endif %}{{ device.name }} ({{ device.entity_id }}): {{ device.state }}{% if device.attributes %} ({% for attr in device.attributes %}{{ attr }}{% if not loop.last %}, {% endif %}{% endfor %}){% endif %}\n{% endfor %}{% else %}The user has no exposed devices.{% endif %}""",
}

# Attribute constants
ATTR_ENTITY_ID: Final = "entity_id"
