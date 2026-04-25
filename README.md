# AWS Bedrock Conversation for Home Assistant

A Home Assistant **custom integration** that uses AWS Bedrock (Anthropic Claude) as a conversation agent with native tool-calling for device control.

Distributed as a [HACS](https://hacs.xyz/) custom integration — **not** a Home Assistant add-on.

## Features

- Conversation agent backed by Claude on AWS Bedrock
- Native tool-calling: the model calls Home Assistant services (`light.turn_on`, `climate.set_temperature`, etc.) directly
- Text-to-speech via Amazon Polly (neural/long-form/generative engines), with the voice list fetched live from your account
- Speech-to-text via Amazon Transcribe streaming (PCM 16 kHz mono), covering English variants, major European languages, and CJK
- Auto-generated system prompt with your exposed devices, areas, and states
- Configurable conversation memory (turn history, per-turn prompt refresh)
- All configuration via the Home Assistant UI — no YAML
- Expose control: only entities you explicitly expose via `Settings → Voice assistants → Expose` are visible to the model

## Supported Models

Both the initial setup flow and the options flow populate their model dropdown by calling `bedrock:ListInferenceProfiles`, filtered to Anthropic entries in `ACTIVE` status. Whatever Claude inference profiles your AWS account/region has access to will appear automatically — the user picks one, there is no silent default.

If that API call fails (missing IAM permission, network error, etc.), the dropdown falls back to the built-in `AVAILABLE_MODELS` list in [`const.py`](custom_components/bedrock_conversation/const.py). Custom model IDs can also be typed manually — the dropdown accepts free-form values.

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
        "bedrock:ListInferenceProfiles",
        "polly:SynthesizeSpeech",
        "polly:DescribeVoices",
        "transcribe:StartStreamTranscription"
      ],
      "Resource": "*"
    }
  ]
}
```

`ListFoundationModels` is used by the config flow to validate credentials during setup. `ListInferenceProfiles` is called when opening the options flow to populate the model dropdown with the Claude inference profiles actually available in your account and region — if the call is denied, the integration falls back to a built-in list.

Polly permissions are optional: if you don't use the TTS entity, you can leave `polly:*` out of the policy. When present, `DescribeVoices` populates the Polly voice dropdown and `SynthesizeSpeech` performs the actual TTS.

Transcribe permission (`transcribe:StartStreamTranscription`) is optional too — it's only needed for the STT entity.

Create an access key for this user and keep the secret somewhere safe.

## Configure the Integration

1. **Settings → Devices & Services → Add Integration** → search "AWS Bedrock Conversation".
2. **Step 1 — credentials.** Enter AWS region (e.g. `us-west-2`), access key id, secret access key, and optionally a session token. Submitting runs a live `ListFoundationModels` call to verify credentials.
3. **Step 2 — model.** Pick the Claude inference profile you want to use. The dropdown is populated by `ListInferenceProfiles` for your account/region; if the call fails it falls back to a built-in list, and you can also type a custom id.

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
| Model ID | `CONF_MODEL_ID` | (chosen during setup) | Picked from the dynamic list fetched via `bedrock:ListInferenceProfiles`, the built-in fallback, or a free-form custom ID. Required — no silent default. |
| System prompt template | `CONF_PROMPT` | Built-in template | Supports `<persona>`, `<current_date>`, `<devices>` placeholders plus Jinja. |
| Max tokens | `CONF_MAX_TOKENS` | 4096 | Bedrock response cap. Slider bound to the selected model's limit (e.g. 8 192 for Haiku 4.5, 64 000 for Sonnet 4.5); clamped on save. |
| Temperature | `CONF_TEMPERATURE` | 1.0 | Sampling temperature. Claude treats temperature and top_p as mutually exclusive, and Bedrock's Claude path only accepts temperature — there is no top_p option. |
| Refresh system prompt each turn | `CONF_REFRESH_SYSTEM_PROMPT` | `True` | If true, device states are refreshed before every turn. |
| Remember conversation | `CONF_REMEMBER_CONVERSATION` | `True` | Keep chat history across turns. |
| Number of interactions to remember | `CONF_REMEMBER_NUM_INTERACTIONS` | 10 | History length (not including the system prompt). |
| Max tool call iterations | `CONF_MAX_TOOL_CALL_ITERATIONS` | 5 | Safety ceiling on tool-calling loop. |
| Extra attributes to expose | `CONF_EXTRA_ATTRIBUTES_TO_EXPOSE` | brightness, rgb_color, temperature, humidity, fan_mode, hvac_mode, etc. | Which entity attributes appear in the prompt. |
| Home Assistant LLM API | `CONF_LLM_HASS_API` | `bedrock_conversation_services` | Which LLM API exposes tools to the model. |
| Polly voice | `CONF_TTS_VOICE_ID` | `Joanna` | Amazon Polly `VoiceId`. Dropdown is populated from `polly:DescribeVoices`; custom IDs are accepted. |
| Polly engine | `CONF_TTS_ENGINE` | `neural` | One of `standard`, `neural`, `long-form`, `generative`. Neural has the best price/quality for general use. |
| Language | `CONF_SELECTED_LANGUAGE` | `en` | Currently only English persona/device-prompt strings ship. |

## Text-to-Speech (Amazon Polly)

A Polly TTS entity is created alongside the conversation agent. Wire it up in **Settings → Voice assistants → Add Assistant**, set the **Text-to-speech** provider to *AWS Polly*, and pick a voice language in the pipeline.

Voice and engine can also be overridden per-call via the `tts.speak` service `options` field, e.g.:

```yaml
service: tts.speak
target:
  entity_id: tts.aws_polly
data:
  message: "Welcome home."
  options:
    voice: Ruth
    engine: generative
```

## Speech-to-Text (Amazon Transcribe)

An STT entity (`stt.aws_transcribe`) is created alongside the conversation agent and TTS entity. Wire it into **Settings → Voice assistants → Add Assistant** by setting the **Speech-to-text** provider to *AWS Transcribe*.

Input format: 16 kHz, 16-bit PCM, mono. Home Assistant's voice pipeline already produces audio in this shape, so no extra conversion is needed.

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
