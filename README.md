# AWS Bedrock Conversation for Home Assistant

A Home Assistant **custom integration** that uses AWS Bedrock (Anthropic Claude) as a conversation agent with native tool-calling for device control.

Distributed as a [HACS](https://hacs.xyz/) custom integration — **not** a Home Assistant add-on.

## Features

- Conversation agent backed by Claude on AWS Bedrock
- Native tool-calling: the model calls Home Assistant services (`light.turn_on`, `climate.set_temperature`, etc.) directly
- Auto-generated system prompt with your exposed devices, areas, and states
- Configurable conversation memory (turn history, per-turn prompt refresh)
- All configuration via the Home Assistant UI — no YAML
- Expose control: only entities you explicitly expose via `Settings → Voice assistants → Expose` are visible to the model

## Supported Models

The options flow populates its model dropdown by calling `bedrock:ListInferenceProfiles` at the time you open it, filtered to Anthropic entries in `ACTIVE` status. Whatever Claude inference profiles your AWS account/region has access to will appear automatically.

If that API call fails (missing IAM permission, network error, etc.), the dropdown falls back to the built-in `AVAILABLE_MODELS` list in [`const.py`](custom_components/bedrock_conversation/const.py):

- `us.anthropic.claude-sonnet-4-5-20250929-v1:0` — larger, more capable
- `us.anthropic.claude-haiku-4-5-20251001-v1:0` — default, faster and cheaper

Custom model IDs can also be typed in manually — the dropdown accepts free-form values.

## Requirements

- Home Assistant 2024.x or later with HACS installed
- An AWS account with Bedrock access
- An IAM user with `bedrock:InvokeModel` and `bedrock:ListFoundationModels`
- Model access granted for your chosen Claude model in the AWS Bedrock console

## Installation

### HACS (recommended)

1. Open **HACS → Integrations**.
2. Menu (⋮) → **Custom repositories** → add `https://github.com/cronus42/homeassistant-aws-bedrock-conversation-agent` as category **Integration**.
3. Search for **AWS Bedrock Conversation** and install it.
4. Restart Home Assistant.

### Manual

1. Copy `custom_components/bedrock_conversation/` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

## AWS Setup

### 1. Enable model access

AWS Console → Bedrock → **Model access** → request access to the Claude model(s) you plan to use. Approval is usually immediate.

### 2. Create an IAM user

Attach a policy equivalent to:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:ListFoundationModels",
        "bedrock:ListInferenceProfiles"
      ],
      "Resource": "*"
    }
  ]
}
```

`ListFoundationModels` is used by the config flow to validate credentials during setup. `ListInferenceProfiles` is called when opening the options flow to populate the model dropdown with the Claude inference profiles actually available in your account and region — if the call is denied, the integration falls back to a built-in list.

Create an access key for this user and keep the secret somewhere safe.

## Configure the Integration

1. **Settings → Devices & Services → Add Integration** → search "AWS Bedrock Conversation".
2. Enter AWS region (e.g. `us-west-2`), access key id, secret access key, and optionally a session token.
3. Submit. The config flow makes a live `ListFoundationModels` call to verify credentials.

### 3. Expose devices

For the model to control a device, it must be exposed:

**Settings → Voice assistants → Expose** → tick the entities you want the assistant to see.

Only exposed entities appear in the system prompt.

### 4. Create a voice assistant

**Settings → Voice assistants → Add Assistant**, set the **Conversation agent** to *AWS Bedrock Conversation*, and configure STT/TTS as desired.

## Configuration Options

After setup, use **Devices & Services → AWS Bedrock Conversation → Configure** to adjust:

| Option | Constant | Default | Notes |
|--------|----------|---------|-------|
| Model ID | `CONF_MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Must be in `AVAILABLE_MODELS`. |
| System prompt template | `CONF_PROMPT` | Built-in template | Supports `<persona>`, `<current_date>`, `<devices>` placeholders plus Jinja. |
| Max tokens | `CONF_MAX_TOKENS` | 4096 | Bedrock response cap. |
| Temperature | `CONF_TEMPERATURE` | 1.0 | Claude treats temperature and top_p as mutually exclusive; only temperature is sent for Claude. |
| Top P | `CONF_TOP_P` | 0.999 | Only applied for non-Claude models. |
| Refresh system prompt each turn | `CONF_REFRESH_SYSTEM_PROMPT` | `True` | If true, device states are refreshed before every turn. |
| Remember conversation | `CONF_REMEMBER_CONVERSATION` | `True` | Keep chat history across turns. |
| Number of interactions to remember | `CONF_REMEMBER_NUM_INTERACTIONS` | 10 | History length (not including the system prompt). |
| Max tool call iterations | `CONF_MAX_TOOL_CALL_ITERATIONS` | 5 | Safety ceiling on tool-calling loop. |
| Extra attributes to expose | `CONF_EXTRA_ATTRIBUTES_TO_EXPOSE` | brightness, rgb_color, temperature, humidity, fan_mode, hvac_mode, etc. | Which entity attributes appear in the prompt. |
| Home Assistant LLM API | `CONF_LLM_HASS_API` | `bedrock_conversation_services` | Which LLM API exposes tools to the model. |
| Language | `CONF_SELECTED_LANGUAGE` | `en` | Currently only English persona/device-prompt strings ship. |

## How Tool Calling Works

1. User: "Turn on the kitchen light."
2. Claude emits a `tool_use` block naming the `HassCallService` tool with `service="light.turn_on"` and `target_device="light.kitchen"`.
3. The integration validates the service against `SERVICE_TOOL_ALLOWED_DOMAINS` / `SERVICE_TOOL_ALLOWED_SERVICES` and calls `hass.services.async_call(..., blocking=False)`.
4. The result is fed back to Claude.
5. Claude returns a natural-language confirmation, which becomes the intent response.

The allowlists live in [`const.py`](custom_components/bedrock_conversation/const.py) and cover lights, switches, fans, climates, covers, media players, locks, scripts, scenes, inputs, and timers.

## Troubleshooting

### Invalid credentials

- Recheck the access key ID and secret.
- Confirm the IAM user has `bedrock:InvokeModel` and `bedrock:ListFoundationModels`.

### Access denied

- Request model access in the Bedrock console for your chosen model.
- Verify the region you picked hosts the chosen model.

### No response / "Unknown error occurred"

Turn on debug logging:

```yaml
logger:
  default: info
  logs:
    custom_components.bedrock_conversation: debug
```

Restart Home Assistant, reproduce the issue, then inspect `home-assistant.log`. Look for:

- `Calling Bedrock model: ...` — request was dispatched
- `Received response from Bedrock (stop_reason: ...)` — request completed
- `Found tool use '...'` / `Tool ... completed` — tool-calling loop activity

If you see `Bedrock API call timed out`, the network path to Bedrock is slow or the model is overloaded; retry or switch to a faster model.

### Device not being controlled

- Confirm the entity is exposed (**Settings → Voice assistants → Expose**).
- Confirm `CONF_MAX_TOOL_CALL_ITERATIONS` is > 0.
- Check logs for `Service domain '...' is not allowed` — that domain is not in the allowlist.

## Documentation for Contributors

- [`DEVELOPMENT.md`](DEVELOPMENT.md) — local development, Makefile targets, release workflow
- [`AGENTS.md`](AGENTS.md) and the per-directory `AGENTS.md` files — architecture reference for AI agents and humans
- [`CHANGELOG.md`](CHANGELOG.md) — release history

## License

MIT. See [`LICENSE`](LICENSE).

## Credits

Inspired by [home-llm](https://github.com/acon96/home-llm) by @acon96.
