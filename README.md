# Bedrock Home Assistant Agent for Home Assistant

A Home Assistant **custom integration** that uses AWS Bedrock (Anthropic Claude) as a conversation agent with native tool-calling for device control.

Distributed as a [HACS](https://hacs.xyz/) custom integration — **not** a Home Assistant add-on.

## Features

### Core
- Conversation agent backed by Claude on AWS Bedrock
- Native tool-calling: the model calls Home Assistant services (`light.turn_on`, `climate.set_temperature`, etc.) directly
- Text-to-speech via Amazon Polly (neural/long-form/generative engines), with the voice list fetched live from your account
- Speech-to-text via Amazon Transcribe streaming (PCM 16 kHz mono), covering English variants, major European languages, and CJK
- Prompt caching (automatic): the static system prompt + tool schema use Anthropic's ephemeral prompt cache for ~90% cost savings on cache hits
- Usage / cost sensors — per-config-entry token counts and estimated daily/cumulative spend in USD, ready for the HA dashboard
- Auto-generated system prompt with your exposed devices, areas, and states
- Configurable conversation memory (turn history, per-turn prompt refresh)
- All configuration via the Home Assistant UI — no YAML
- Expose control: only entities you explicitly expose via `Settings → Voice assistants → Expose` are visible to the model
- Vision input: one-shot camera-snapshot service (`bedrock_ha_agent.ask_with_image`) or auto-attach exposed cameras to every turn

### Opt-in tool suites (v1.1.0+ and v1.2.0+)

Two additional tool suites ship but are **off by default**. Enable them independently in the options flow when you want the model to go beyond basic device control:

- **Config editing** (`CONF_ENABLE_CONFIG_EDITING`, v1.1.0+) — approval-gated natural-language editing of automations, scripts, scenes, helpers (`input_*`, `timer`, `counter`), Lovelace dashboards and cards, and the area/label/entity registries. Every proposed change is previewed as a diff and summary; the user must say "yes" / "apply" before anything writes. In-memory undo stack per conversation (20 deep, 1-hour TTL). No filesystem edits — everything routes through HA's native REST/WebSocket APIs.
- **Diagnostics & control** (`CONF_ENABLE_DIAGNOSTICS`, v1.2.0+) — ask Claude to troubleshoot. Read-only tools for the HA system log, logbook, state history, statistics, repairs, and system_health. An `ExtendedServiceCall` tool dispatches a broader allowlist of services with per-service classification (read-safe fires immediately; state-mutating goes through the same approval gate). Approval-gated lifecycle tools for reloading integrations, enabling/disabling entities, setting logger levels, and triggering `check_config`. Responses are summarized and capped (64 KiB / 3 calls per turn) so voice answers stay short; the agent is prompted to ask clarifying questions before running an unfiltered log dump.

## Supported Models

Both the initial setup flow and the options flow populate their model dropdown by calling `bedrock:ListInferenceProfiles`, filtered to Anthropic entries in `ACTIVE` status. Whatever Claude inference profiles your AWS account/region has access to will appear automatically — the user picks one, there is no silent default.

If that API call fails (missing IAM permission, network error, etc.), the dropdown falls back to the built-in `AVAILABLE_MODELS` list in [`const.py`](custom_components/bedrock_ha_agent/const.py). Custom model IDs can also be typed manually — the dropdown accepts free-form values.

## Requirements

- **Home Assistant 2025.6.0 or later** with HACS installed. The integration depends on the `ai_task` component and the 2025.3+ chat-log streaming API; older HA versions are not supported. Users on HA 2024.12–2025.5 must stay on integration version `1.0.59`.
- An AWS account with Bedrock access
- An IAM user with `bedrock:InvokeModel` and `bedrock:ListFoundationModels`
- Model access granted for your chosen Claude model in the AWS Bedrock console

## Installation

### HACS (recommended)

1. Open **HACS → Integrations**.
2. Menu (⋮) → **Custom repositories** → add `https://github.com/sparkleHazard/homeassistant-bedrock-ha-agent` as category **Integration**.
3. Search for **Bedrock Home Assistant Agent** and install it.
4. Restart Home Assistant.

### Manual

1. Copy `custom_components/bedrock_ha_agent/` into your Home Assistant `config/custom_components/` directory.
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
        "bedrock:InvokeModelWithResponseStream",
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

1. **Settings → Devices & Services → Add Integration** → search "Bedrock Home Assistant Agent".
2. **Step 1 — credentials.** Enter AWS region (e.g. `us-west-2`), access key id, secret access key, and optionally a session token. Submitting runs a live `ListFoundationModels` call to verify credentials.
3. **Step 2 — model.** Pick the Claude inference profile you want to use. The dropdown is populated by `ListInferenceProfiles` for your account/region; if the call fails it falls back to a built-in list, and you can also type a custom id.

### 3. Expose devices

For the model to control a device, it must be exposed:

**Settings → Voice assistants → Expose** → tick the entities you want the assistant to see.

Only exposed entities appear in the system prompt.

### 4. Create a voice assistant

**Settings → Voice assistants → Add Assistant**, set the **Conversation agent** to *Bedrock Home Assistant Agent*, and configure STT/TTS as desired.

## Configuration Options

After setup, use **Devices & Services → Bedrock Home Assistant Agent → Configure** to adjust:

| Option | Constant | Default | Notes |
|--------|----------|---------|-------|
| Model ID | `CONF_MODEL_ID` | (chosen during setup) | Picked from the dynamic list fetched via `bedrock:ListInferenceProfiles`, the built-in fallback, or a free-form custom ID. Required — no silent default. |
| System prompt template | `CONF_PROMPT` | Built-in template | Supports `{{persona}}`, `{{current_date}}`, `{{devices}}` placeholders plus Jinja. The legacy `<persona>` / `<current_date>` / `<devices>` syntax is still accepted for backward compatibility. |
| Max tokens | `CONF_MAX_TOKENS` | 4096 | Bedrock response cap. Slider bound to the selected model's limit (e.g. 8 192 for Haiku 4.5, 64 000 for Sonnet 4.5); clamped on save. |
| Temperature | `CONF_TEMPERATURE` | 1.0 | Sampling temperature. Claude treats temperature and top_p as mutually exclusive, and Bedrock's Claude path only accepts temperature — there is no top_p option. |
| Refresh system prompt each turn | `CONF_REFRESH_SYSTEM_PROMPT` | `True` | If true, device states are refreshed before every turn. |
| Remember conversation | `CONF_REMEMBER_CONVERSATION` | `True` | Keep chat history across turns. |
| Number of interactions to remember | `CONF_REMEMBER_NUM_INTERACTIONS` | 10 | History length (not including the system prompt). |
| Max tool call iterations | `CONF_MAX_TOOL_CALL_ITERATIONS` | 5 | Safety ceiling on tool-calling loop. |
| Extra attributes to expose | `CONF_EXTRA_ATTRIBUTES_TO_EXPOSE` | brightness, rgb_color, temperature, humidity, fan_mode, hvac_mode, etc. | Which entity attributes appear in the prompt. |
| Expose areas only | `CONF_EXPOSE_AREAS_ONLY` | `[]` (all) | Optional list of area ids. When set, the device list in the system prompt only includes entities in those areas. Big token win on large homes. |
| Device list format | `CONF_DEVICE_PROMPT_MODE` | `full` | `full` (current state + attributes), `compact` (state, no attributes), `names_only` (entity + area, no state). `names_only` drops an 8 KB / 270-device list to roughly 2 KB. |
| Max tokens in device list | `CONF_MAX_PROMPT_TOKENS` | `0` (uncapped) | Soft cap on the rendered device list size. If exceeded, extra devices are omitted and the model is told how many were dropped. |
| Home Assistant LLM API | `CONF_LLM_HASS_API` | `bedrock_ha_agent_services` | Which LLM API exposes tools to the model. |
| Polly voice | `CONF_TTS_VOICE_ID` | `Joanna` | Amazon Polly `VoiceId`. Dropdown is populated from `polly:DescribeVoices`; custom IDs are accepted. |
| Polly engine | `CONF_TTS_ENGINE` | `neural` | One of `standard`, `neural`, `long-form`, `generative`. Neural has the best price/quality for general use. |
| Language | `CONF_SELECTED_LANGUAGE` | `en` | Currently only English persona/device-prompt strings ship. |

### Config editing (opt-in, v1.1.0+)

| Option | Constant | Default | Notes |
|--------|----------|---------|-------|
| Enable config editing | `CONF_ENABLE_CONFIG_EDITING` | `False` | Kill switch. When on, Claude can propose changes to automations, scripts, scenes, helpers, Lovelace, and registries — every change is gated by explicit user approval. Off by default. |
| Undo stack depth | `CONF_CONFIG_UNDO_DEPTH` | `20` | How many applied changes the in-memory undo log keeps per conversation. Range 1–50. |
| Undo TTL (seconds) | `CONF_CONFIG_UNDO_TTL_SECONDS` | `3600` | How long an undo entry is retained. Range 60–86400. |
| Approval TTL (seconds) | `CONF_CONFIG_APPROVAL_TTL_SECONDS` | `300` | How long a pending change waits for user confirmation. Range 30–3600. |

### Diagnostics & control (opt-in, v1.2.0+)

| Option | Constant | Default | Notes |
|--------|----------|---------|-------|
| Enable diagnostics & control | `CONF_ENABLE_DIAGNOSTICS` | `False` | Kill switch. Registers read-only log/state/history/repairs/health tools, a broader service-call tool, and approval-gated lifecycle tools (reload integration, enable/disable entity, set logger level, check config). Off by default. |
| Max log entries per call | `CONF_DIAGNOSTICS_LOG_MAX_LINES` | `50` | Hard cap on how many system-log entries a single tool call can return. Range 10–500. |
| Max history lookback (hours) | `CONF_DIAGNOSTICS_HISTORY_MAX_HOURS` | `24` | Ceiling for the logbook/state-history window. Range 1–168 (one week). |
| Diagnostic calls per turn | `CONF_DIAGNOSTICS_CALL_BUDGET_PER_TURN` | `3` | Maximum number of diagnostic tool calls Claude may make in a single response. Prevents runaway log-scan loops. Range 1–10. |

## Vision Input (camera snapshots)

Two ways to get Claude to look at something:

### 1. `bedrock_ha_agent.ask_with_image` service

One-shot question about one or more camera snapshots. Returns the reply as a service response — no conversation history, no tools. Use this from automations.

```yaml
service: bedrock_ha_agent.ask_with_image
data:
  message: "Is the driveway empty?"
  camera_entity_id: camera.front_driveway
response_variable: result
```

You can also pass a list of camera entity_ids. Set `config_entry_id` if you have more than one Bedrock entry configured.

### 2. Auto-attach exposed cameras (options-flow toggle)

Turn on **"Attach exposed camera snapshots to each turn"** in the options. Every conversation turn then pulls a fresh snapshot from each `camera.*` entity you've exposed via **Settings → Voice assistants → Expose** and attaches it to the user's message before sending to Bedrock.

Caveats:
- Only the **first Bedrock call** per user turn attaches images — not every tool-calling iteration — to keep token cost sane.
- Adds roughly 1.5K input tokens per image per turn.
- Requires a vision-capable model. The default (`claude-haiku-4-5`) does **not** support images; switch to `claude-sonnet-4-5` if you want vision.

## Services

The integration registers two Home Assistant services (both via `hass.services.async_register`, so they appear in **Developer tools → Services**):

### `bedrock_ha_agent.ask_with_image`

One-shot question about one or more camera snapshots. See the [Vision Input](#vision-input-camera-snapshots) section above.

### `bedrock_ha_agent.undo_last_config_change`

Pops the undo stack and reverses the most recent applied config-editing change. Complementary to the in-chat "undo that" intent. Admin-only.

```yaml
service: bedrock_ha_agent.undo_last_config_change
data:
  # Optional — only needed if you have more than one Bedrock entry configured.
  config_entry_id: "<entry_id>"
  # Optional — disambiguates when multiple conversations have non-empty undo stacks.
  conversation_id: "<conversation_id>"
```

Available only when `CONF_ENABLE_CONFIG_EDITING` is on. Returns `{"undone": true, "summary": "..."}` on success; `{"undone": false, "summary": "nothing to undo"}` when the stack is empty. When two conversations both have pending undos and you didn't specify `conversation_id`, it returns a structured `"ambiguous_conversation"` error listing the candidate ids.

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

## Usage & Cost Sensors

Each config entry creates five sensors:

- `sensor.<entry>_input_tokens_today`
- `sensor.<entry>_output_tokens_today`
- `sensor.<entry>_cached_tokens_today` (cache_read + cache_write combined)
- `sensor.<entry>_estimated_cost_today` (USD, rolls over at UTC midnight)
- `sensor.<entry>_estimated_cost_total` (USD, cumulative since integration reload)

Pricing uses a built-in per-model rate card (see `usage_tracker.py::_PRICING`). Unknown custom models report token counts but not cost.

## How Tool Calling Works

### Core device control (always on)

1. User: "Turn on the kitchen light."
2. Claude emits a `tool_use` block naming the `HassCallService` tool with `service="light.turn_on"` and `target_device="light.kitchen"`.
3. The integration validates the service against `SERVICE_TOOL_ALLOWED_DOMAINS` / `SERVICE_TOOL_ALLOWED_SERVICES` and calls `hass.services.async_call(..., blocking=False)`.
4. The result is fed back to Claude.
5. Claude returns a natural-language confirmation, which becomes the intent response.

The allowlists live in [`const.py`](custom_components/bedrock_ha_agent/const.py) and cover lights, switches, fans, climates, covers, media players, locks, scripts, scenes, inputs, and timers.

### Config editing (when `CONF_ENABLE_CONFIG_EDITING` is on)

~20 additional tools register when the flag is on — e.g. `ConfigAutomationCreate`, `ConfigScriptEdit`, `ConfigSceneDelete`, `ConfigLovelaceCardAdd`, `ConfigAreaRename`, `ConfigEntityAssignArea`, `ConfigLabelCreate`, and so on. Each follows the same two-phase flow:

1. Claude calls the tool. The integration validates the payload (schema + entity existence; no filesystem writes, no `check_config` side-effects) and returns `{"status": "pending_approval", "proposal_id": "...", "proposed_summary": "Would add automation 'Porch light at sunset' ...", "proposed_diff": "..."}`.
2. Claude describes the proposal to the user and waits.
3. User replies "yes" / "apply" / "do it". A message-boundary interceptor in `conversation.async_process` matches the intent, looks up the pending change, and calls its `apply_change()` — which goes through HA's config REST/WebSocket APIs, fires the matching `.reload` service, and pushes an `UndoEntry`.
4. On post-apply failure (e.g. reload raises), the undo is popped automatically and the user sees a structured error.
5. "Undo that" / "revert that" / the `bedrock_ha_agent.undo_last_config_change` service pops the undo stack and restores via the stored inverse operation.

Feature-flag-off leaves the tool list and system prompt unchanged — existing automations and voice assistants are unaffected.

### Diagnostics & control (when `CONF_ENABLE_DIAGNOSTICS` is on)

15 more tools register when the flag is on, across four buckets:

- **Read-only:** `DiagnosticsSystemLogList`, `DiagnosticsLogbookRead`, `DiagnosticsRepairsList`, `DiagnosticsHealthCheck`, `DiagnosticsStateRead`, `DiagnosticsStateHistory`, `DiagnosticsStatistics`, `DiagnosticsIntegrationList`. Execute immediately. Each response is capped at 64 KiB with a lossy-truncation marker; per-turn call budget (default 3) prevents runaway log-scan loops.
- **Extended service calls:** `ExtendedServiceCall` dispatches a broader allowlist than `HassCallService`. Each entry is classified `read_safe` (fires immediately — `persistent_notification.*`, `system_log.clear`, `zone.reload`, `homeassistant.update_entity`) or `mutating` (routed through the same approval gate as config-editing — `automation.trigger`, `script.turn_on`, `timer.*`, `counter.*`, `input_boolean.*`). Services not on the allowlist are refused.
- **Lifecycle (approval-gated):** `DiagnosticsReloadIntegration`, `DiagnosticsReloadConfigEntry`, `DiagnosticsEntityEnable`, `DiagnosticsEntityDisable`, `DiagnosticsLoggerSetLevel`, `DiagnosticsCheckConfig`. Entity enable/disable and logger level set have real inverse operations; reloads push a no-op undo since reload is one-way.
- **Safety rails:** log content is wrapped in `<<UNTRUSTED>>…<<END_UNTRUSTED>>` markers and the system prompt tells Claude never to treat that content as instructions. Secrets matching `api_key`, `password`, `bearer_token`, `client_secret`, `Authorization`, JWT/AWS/OpenAI key patterns, and related keys are redacted from both request echoes and service responses. `homeassistant.restart`, `recorder.purge`, and supervisor operations are on an explicit deny list.

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
    custom_components.bedrock_ha_agent: debug
```

Restart Home Assistant, reproduce the issue, then inspect `home-assistant.log`. Look for:

- `Calling Bedrock model: ...` — request was dispatched
- `Received response from Bedrock (stop_reason: ...)` — request completed
- `Found tool use '...'` / `Tool ... completed` — tool-calling loop activity

If you see `Bedrock API call timed out`, the network path to Bedrock is slow or the model is overloaded; retry or switch to a faster model.

### "Unexpected error during intent recognition"

This is HA's generic wrapper around a Python exception. The real traceback is in `home-assistant.log`; look for `ERROR homeassistant.components.assist_pipeline.pipeline`. v1.2.3/v1.2.4 fixed the two common variants (Bedrock tool-schema rejection and an `LLMContext` attribute mismatch) — make sure you're on at least v1.2.4. If you're seeing it with diagnostics enabled, a stack trace from the log is the fastest way to diagnose; open an issue with the excerpt.

### "That request didn't pass the AI service's validation"

Bedrock rejected the request body before Claude saw it — almost always a malformed tool `input_schema`. v1.2.3 fixed the three known variants (function-as-key, `default` in input_schema, `vol.Any(None, dict)` producing a malformed type). Upgrade to v1.2.3 or later; if it persists, capture the HA log and open an issue.

### Device not being controlled

- Confirm the entity is exposed (**Settings → Voice assistants → Expose**).
- Confirm `CONF_MAX_TOOL_CALL_ITERATIONS` is > 0.
- Check logs for `Service domain '...' is not allowed` — that domain is not in the allowlist.

### Claude keeps saying "I added the automation" but nothing happened

You likely have `CONF_ENABLE_CONFIG_EDITING` on and Claude is confabulating success on a `pending_approval` response. The system prompt tells the model not to do this; a runtime detector logs `WARNING: pending proposal ... still awaiting approval; assistant text claims success` whenever it happens. Check the log for that string. Say "yes" or "apply" to approve the pending change, or "no" / "cancel that" to discard it.

### Log responses are too long on voice

v1.3.0 slims the diagnostics response shape and tells the model to ask before running an unfiltered log dump ("which integration? which severity?"). Upgrade to v1.3.0 or later. You can also tighten `CONF_DIAGNOSTICS_LOG_MAX_LINES` and `CONF_DIAGNOSTICS_CALL_BUDGET_PER_TURN` in the options flow.

## Documentation for Contributors

- [`DEVELOPMENT.md`](DEVELOPMENT.md) — local development, Makefile targets, release workflow
- [`AGENTS.md`](AGENTS.md) and the per-directory `AGENTS.md` files — architecture reference for AI agents and humans
- [`CHANGELOG.md`](CHANGELOG.md) — release history

## License

MIT. See [`LICENSE`](LICENSE).

## Credits

Inspired by [home-llm](https://github.com/acon96/home-llm) by @acon96.
