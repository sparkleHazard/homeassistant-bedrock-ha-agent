# Changelog

All notable changes to this project are documented here.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions. Detailed per-release notes live on GitHub Releases; this file captures the higher-level history.

## 1.1.2 — Streaming generation fix

### Fixed
- Every conversation turn was failing with HA's generic
  `Unexpected error during intent recognition` wrapper. Root cause in
  `bedrock_client.async_generate_stream`: the function's outer `finally`
  block unconditionally re-raised `HomeAssistantError(f"Unexpected error:
  {err}")`, but `err` had never been bound at that scope — so both the
  happy path and any error path hit `UnboundLocalError`. The `finally`
  should only drain the pump executor; the outer try's own `raise`
  already handles real errors. Replaced the bogus re-raise with a
  suppressed `await pump_task`.
- Nine more `runtime_data.get("usage")` dict-subscript holdovers in
  `bedrock_client.py` converged on attribute access via a new
  `_runtime_usage_tracker(entry)` helper. 1.1.1 caught only the sensor +
  conversation + undo-service reads; these nine in `bedrock_client.py`
  slipped past that sweep (the grep pattern didn't match `.get("usage")`).
  Every usage-tracking call site now uses the same defensive helper.

## 1.1.1 — Entity registration + translation fix

### Fixed
- Integration now correctly registers its conversation agent + usage sensors
  at setup. In 1.1.0 the Phase-3 `BedrockRuntimeData` dataclass migration was
  incomplete: three read sites still used the old dict syntax
  (`entry.runtime_data["client"]` / `.get("usage")`) while the writer had
  already moved to attribute assignment. Result: sensor.py raised on `.get()`
  and the conversation agent raised on `["client"]`, so both platforms
  silently failed to add entities — only Polly TTS + Transcribe STT
  (which don't read `runtime_data`) appeared in HA. All four platforms now
  register as intended. Fix converges reads + writes on attribute access and
  adds `usage: UsageTracker | None` as a typed field on the dataclass.
- Translation error `UNCLOSED_TAG` resolved. The options-flow tooltip for the
  system-prompt template referenced the `<current_date>` and `<devices>`
  Jinja-style placeholders with literal angle brackets, which HA's
  translation renderer parsed as unclosed HTML tags. Bracketed tokens now
  use HTML-entity escapes (`&lt;current_date&gt;` / `&lt;devices&gt;`) so
  the renderer treats them as literal text.

## 1.1.0 — Config editing (opt-in)

### Breaking
- **Minimum Home Assistant version raised to 2025.6.0.** The integration's
  `manifest.json` already depends on `ai_task` (which landed in HA 2025.6), so
  the previous `hacs.json` floor of 2024.12 was inaccurate. Users on HA
  versions below 2025.6 MUST remain on integration version `1.0.59`; HACS will
  prevent the update automatically.

### Added
- Opt-in conversational config editing for automations, scripts, scenes,
  helpers, Lovelace dashboards & cards, areas, labels, and entity registry
  fields. Disabled by default. Enable via Settings → Devices & Services →
  Bedrock Home Assistant Agent → Configure → "Enable config editing."
- Per-conversation pending-approval flow: Claude proposes a change; you
  confirm with "yes"/"apply"/"do it"; the change applies. Cancel with "no"/
  "cancel"/"revert that" before applying.
- Per-conversation undo stack (20 deep, 1 hour TTL). Say "undo that" or call
  the new `bedrock_ha_agent.undo_last_config_change` service. Multiple
  concurrent voice satellites on one Bedrock entry do NOT share undo history.
- YAML-mode Lovelace dashboards are detected and refused with a clear error
  ("this dashboard is managed via configuration.yaml; edit the file manually").
- Model advisory: enabling config editing on a Claude Haiku model surfaces a
  one-time notification recommending Claude Sonnet 4.5 or Opus for large diffs.

### Safety
- All config-editing tools go through a pending-approval gate; the model cannot
  apply changes in a single turn.
- Post-apply reload failures auto-revert the change (undo-stack pop + restore).
- Pre-validation catches unknown entities and malformed schemas before the user
  sees a diff. `check_config` is NOT called (see known limitations).
- No file I/O under /config from the integration; all edits route through HA
  REST/WS APIs. AST-enforced (see `tests/test_no_file_io.py`).

### Known limitations
- Restoring an area or label that was deleted via the integration re-creates
  the entity but assigns a NEW `area_id` / `label_id`; existing references to
  the old id remain dangling. The undo success message calls this out.
- Entities whose `disabled_by` is `INTEGRATION`/`CONFIG_ENTRY`/`DEVICE` cannot
  be toggled by the integration (HA restricts WS updates to `USER` origin).
- Undo history is in-memory only and clears on HA restart.
- `check_config` is not called for pre-validation or post-apply verification in
  v1; reload-exception catching is the post-apply safety net.

### Migration
- No data migration. All new settings are optional `entry.options` keys that
  default to safe values. Users updating from 1.0.x will see the new options
  in the configure dialog but nothing changes until they opt in.

> **If you are on Home Assistant 2024.12 through 2025.5:** do NOT update to
> integration 1.1.x. Stay on 1.0.59. The 1.1.x series requires HA 2025.6+ due
> to its dependency on the `ai_task` component. Upgrade HA first, then update
> the integration.

## 1.0.59

### Added
- Three new options for cutting system-prompt size on large installs:
  - **Expose areas only** (`CONF_EXPOSE_AREAS_ONLY`) — multi-select area list; when set, only entities in those areas make it into the device list. Empty = all exposed (default).
  - **Device list format** (`CONF_DEVICE_PROMPT_MODE`) — `full` (current behavior), `compact` (drops per-entity attributes), or `names_only` (drops state + attributes, keeps entity/name/area). Going from `full` to `names_only` on a 270-device install takes the device list from ~20 KB to ~2 KB per turn.
  - **Max tokens in device list** (`CONF_MAX_PROMPT_TOKENS`) — soft cap on rendered size (4-chars/token heuristic). When exceeded, extra devices are omitted and the model is told how many were dropped. `0` = no cap (default).
- All three default to existing behavior, so upgraded installs see zero change until you opt in.

## 1.0.58

### Added
- **Vision input**. Claude can now look at Home Assistant camera snapshots. Two entry points:
  - New service `bedrock_ha_agent.ask_with_image`: takes `message` + `camera_entity_id` (string or list) and returns the reply as a service response. Best for automations — no conversation history, no tools, just image + question.
  - New options-flow toggle `Attach exposed camera snapshots to each turn`. When on, every conversation turn pulls fresh snapshots from all cameras you've exposed to conversation and attaches them to the user message. Only the first Bedrock call per turn attaches images (not every tool-calling iteration) to bound token cost.
- Model-capability gate: both paths refuse (or warn-and-drop) when the selected model isn't vision-capable. Current default (Haiku 4.5) does **not** support images; switch to Sonnet 4.5 to use vision. Claude 3/3.5 Sonnet, 3 Opus, 3 Haiku are also recognized as vision-capable (see `VISION_CAPABLE_MODELS`).
- Vision calls update the existing cost sensors normally (≈1.5K input tokens per image on Sonnet 4.5).

### Notes
- README IAM policy now includes `bedrock:InvokeModelWithResponseStream` for completeness (it was effectively required since 1.0.55; scoping may differ if you had a custom IAM policy).

## 1.0.57

### Added
- Automatic retry with exponential backoff (0.5s / 1s / 2s, 3 attempts total) on transient Bedrock errors: `ThrottlingException`, `TooManyRequestsException`, `ServiceUnavailableException`, `InternalServerException`, `ModelStreamErrorException`, `ModelTimeoutException`. Non-retryable errors (auth, validation, region mismatches) still fail fast so the user sees them immediately.
- Two new health sensors per config entry: `sensor.<entry>_last_successful_request` (timestamp) and `sensor.<entry>_last_error` (text, "none" when clean). Plug them into a dashboard to watch for persistent failures.
- Voice-friendly error responses. Instead of "Sorry, there was an error: An error occurred (ThrottlingException)...", the assistant now says things like "I'm being rate-limited right now. Try again in a minute." or "The selected model isn't available in this AWS region." AWS error codes are mapped in `_friendly_error_message` in `bedrock_client.py`.

## 1.0.56

### Fixed
- Streaming path (1.0.55) executed every tool call twice and then crashed with `TypeError: 'NoneType' object can't be awaited`. Two issues:
  - `chat_log.async_add_delta_content_stream` already runs non-external tools itself and yields the resulting `ToolResultContent` records; our old code re-executed them via `execute_tool_call`. Devices were turned on/off twice per request.
  - `chat_log.async_add_assistant_content_without_tools` is a sync method in this HA path — awaiting it raised `TypeError`.
- The streaming turn helper now collects both the `AssistantContent` and any `ToolResultContent` records yielded by `chat_log` and the outer loop just extends `message_history` with both. No double-execution, no spurious await.

## 1.0.55

### Added
- Streaming Bedrock responses. The conversation agent now uses `invoke_model_with_response_stream` and pipes text deltas straight into `chat_log.async_add_delta_content_stream`, so Home Assistant streams speech to TTS as the model generates it instead of waiting for the full response. Noticeable latency win on any terminal turn longer than a sentence.
- `BedrockClient.async_generate_stream` yields normalized `text_delta` / `tool_use_start` / `tool_use_delta` / `message_end` events. Tool-use turns still buffer the full JSON args before executing, so tool-calling semantics are unchanged.
- Usage sensors update from streamed responses too (counters read from the `message_delta` usage block).

### Changed
- Internal: shared request-body construction between streaming and non-streaming paths via `_build_request`. `async_generate` is retained as a non-streaming fallback.

### Requirements
- Home Assistant 2025.2 or newer (for `chat_log.async_add_delta_content_stream`). The production HA used in development (2026.4.x) is well past this.

## 1.0.54

### Added
- New `sensor` platform exposing Bedrock token usage + estimated cost per config entry: `input_tokens_today`, `output_tokens_today`, `cached_tokens_today`, `estimated_cost_today`, `estimated_cost_total`. Counters roll over at UTC midnight; totals accumulate since the last integration reload. Cost calculation uses a built-in per-model rate card (Sonnet 4.5, Haiku 4.5, plus Claude 3.x family); unknown custom models report tokens but not cost.
- `usage_tracker.py` (small internal helper) folds the `usage` block from every Bedrock response into the counters and pushes updates to the sensors.

## 1.0.53

### Added
- Prompt caching for Bedrock Claude. The system prompt and tool schema are now tagged with `cache_control: ephemeral` on every request, so repeated turns in a conversation (and the re-rendered device list when `refresh_prompt_per_turn` is on) hit Anthropic's prompt cache. Cache hits cost 90% less than a fresh read. Cache read/write token counts are logged per response so you can verify hit rate via HA's debug logs.

## 1.0.52

### Changed
- Internal refactor (no behaviour change): extract pure helpers out of `conversation.py::async_process` into `conversation_helpers.py`. `parse_bedrock_response` returns a typed `BedrockResponse` dataclass; `execute_tool_call` wraps one `llm_api.async_call_tool` with the 10-second timeout and converts errors to `ToolResultContent`; `error_result` / `speech_result` build `ConversationResult` values. `async_process` now reads top-to-bottom as the orchestration it is. `conversation.py` drops from 413 → 297 LOC.

## 1.0.51

### Changed
- Internal refactor (no behaviour change): split `bedrock_client.py` (585 LOC) into three focused modules. `device_info.py` now owns `DeviceInfo` and the exposed-entity enumeration (the attribute-extraction cascade is now a declarative table). `messages.py` owns the Bedrock messages + tool-schema construction as pure functions. `bedrock_client.py` shrinks to 270 LOC and keeps only what deals with AWS I/O. `DeviceInfo` is re-exported from `bedrock_client` for backward compatibility with existing imports / tests.

## 1.0.50

### Changed
- Internal refactor (no behaviour change): extract shared AWS-session factory into `aws_session.py`. Collapses six duplicated `boto3.Session(...)` call sites across `bedrock_client.py`, `config_flow.py`, and `tts.py` into one `build_session()` / `session_from_entry_data()` helper. Empty session-token strings are normalised to `None` in one place (boto3 distinguishes missing-token from empty-string-token and the latter causes signing failures).

## 1.0.49

### Changed
- The "?" documentation link in **Settings → Devices & Services** now points directly at the README (`manifest.json:documentation`) instead of the repo homepage.
- Corrected every remaining `cronus42/...` repo URL to the real `sparkleHazard/...` slug in README, DEVELOPMENT.md, CHANGELOG, and manifest.

## 1.0.48

### Removed
- "Top P" configuration option. Claude models only accept `temperature`, not `top_p`; the integration's `AVAILABLE_MODELS` list is Claude-only, so `top_p` was never actually sent to Bedrock — it was a slider that did nothing. `CONF_TOP_P` and the dead non-Claude conditional in `async_generate` are gone too. Existing entries with a stored `top_p` are harmless; the value is simply ignored.

### Changed
- Default system prompt template is now a readable, user-editable set of device-control instructions instead of just the three placeholders (`<persona>`, `<current_date>`, `<devices>`). The `<persona>` placeholder substitution still works for backward compatibility but is no longer used by the built-in default. Helper text under the prompt field now explains what `<current_date>` and `<devices>` do.

## 1.0.47

### Changed
- Polly voice pickers (both the options-flow dropdown and the pipeline UI voice selector) now filter by the currently configured Polly engine. Voices whose `SupportedEngines` do not include the chosen engine are hidden, so you can no longer pick a voice + engine combo that Polly would reject at runtime. The per-language voice cache keys on `(language, engine)` so switching engine invalidates the stale list cleanly.

## 1.0.46

### Changed
- "Max tokens" is now a slider whose upper bound adapts to the currently selected model's output-token limit (e.g. 8 192 for Claude Haiku 4.5, 64 000 for Claude Sonnet 4.5). Limits live in `const.MODEL_TOKEN_LIMITS` keyed by model-id substring; unknown / custom models fall back to a generous default. On save, the submitted value is clamped to the picked model's limit. Note: HA doesn't re-render options schemas as you change fields — if you switch the model in the options dialog, close and reopen it to see the new slider bounds.

## 1.0.45

### Fixed
- Polly read emoji phonetically ("smiling face emoji", "red heart", etc.). Strip them from the message before calling `SynthesizeSpeech`. Covers pictographic ranges, dingbats, misc symbols, regional indicators, variation selectors, and the zero-width joiner.

## 1.0.44

### Added
- Polly TTS entity implements `async_get_supported_voices`, so Home Assistant's voice-assistant pipeline UI now shows the real per-language voice list fetched live from `polly:DescribeVoices`. Results are cached per language for one hour to keep the UI snappy.

## 1.0.43

### Fixed
- `messages.1.content.N: tool_use ids must be unique` error when a single assistant turn contained two calls to the same tool (e.g. controlling two lights at once). `_build_bedrock_messages` was matching reconstructed `ToolInput` objects to `ToolResultContent` by `tool_name` alone, so every call to the same tool received the first result's id. Now matches in order and consumes each result exactly once, and the fallback id uses a counter instead of `id(obj)` so it can't collide across turns.

## 1.0.42

### Added
- Amazon Transcribe streaming speech-to-text entity (`stt.aws_transcribe`). Creates an STT entity next to the TTS one, using the same AWS credentials. Expects 16 kHz / 16-bit PCM mono input, which matches Home Assistant's voice pipeline defaults.
- `amazon-transcribe>=0.6.2` added to `manifest.json` requirements so Home Assistant installs the streaming SDK on first load.
- `transcribe:StartStreamTranscription` added to the recommended IAM policy (optional — only required if you use the STT entity).

## 1.0.41

### Added
- Amazon Polly text-to-speech entity. Creates a `tts.*` entity next to the conversation agent so Polly can be plugged straight into a voice-assistant pipeline. Voice list is fetched live via `polly:DescribeVoices`, with a fallback shortlist if the permission is missing. Engine picker supports `standard`, `neural`, `long-form`, and `generative`. Voice/engine can also be overridden per-call via `tts.speak` options.
- `polly:SynthesizeSpeech` and `polly:DescribeVoices` added to the recommended IAM policy (optional — only required if you use the TTS entity).

## 1.0.40

### Fixed
- "`max_tokens: Input should be a valid integer`" error from Bedrock. Home Assistant's `NumberSelector` always returns floats — even when configured with `step=1` — so the integer-semantic options (`max_tokens`, `remember_num_interactions`, `max_tool_call_iterations`) were reaching the Anthropic request schema as `4096.0` etc. Coerce to `int` at the boundaries in `bedrock_client.py` and `conversation.py`.

## 1.0.39

### Changed
- Initial setup is now a two-step flow: credentials first, then model selection. There is no silent `DEFAULT_MODEL_ID` picked for the user — the integration always starts with the model they explicitly chose, reducing surprise "invalid model" errors on first run.

### Added
- New `model` step in `strings.json` / `translations/en.json` for the model-picker form.

## 1.0.38

### Added
- Options flow model dropdown is now populated dynamically from `bedrock:ListInferenceProfiles`, filtered to Anthropic entries in `ACTIVE` status. Whatever Claude inference profiles your account has access to appear automatically.

### Changed
- IAM policy in the README now includes `bedrock:ListInferenceProfiles`. If it's missing, the options flow still opens — it just falls back to the built-in `AVAILABLE_MODELS` list.

## 1.0.37

### Fixed
- Options flow crashed with `AttributeError: property 'config_entry' of 'BedrockConversationOptionsFlow' object has no setter` in recent Home Assistant versions. The `OptionsFlow` base class now exposes `config_entry` as a read-only property and subclasses must not assign to it in `__init__`. Removed the override; the config entry is still available via `self.config_entry`.
- Model-id selector now tolerates a stored value that is no longer in `AVAILABLE_MODELS` (e.g. after removing legacy Claude 3.5 ids). The current value is appended to the dropdown options and `custom_value=True` is enabled so opening the options flow no longer fails for upgraded installs.

## Unreleased

### Changed
- Documentation overhaul: single primary README at the repo root; removed add-on-style installation content that did not apply to this custom integration.
- Logging: stripped emoji/debug banners and demoted lifecycle events from ERROR to INFO/DEBUG.

### Removed
- Legacy Goose-era memory files (`.goose/`, `.goosehints`).
- `top_k` configuration option — it was being silently discarded on the Bedrock request path, so the UI knob was dead.
- `INSTALL.md`, `WARP.md`, `TESTING_GUIDE.md`, and `tests/README.md` — obsolete or superseded by the new README/AGENTS.md layout.

### Added
- `brightness_pct` and `tilt_position` to the tool-calling service-argument allowlist.
- Hierarchical `AGENTS.md` files describing each part of the repo.

### Fixed
- Config-flow error keys (`unknown_error` → `unknown`) now match the entries in `strings.json` / `translations/en.json`.
- Double-blank-line / unused-import leftovers from the cleanup pass.

## 1.0.36 and earlier

Pre-1.0.36 history is tracked in git. Notable themes up to this version:

- Initial HACS custom integration delivering a Home Assistant conversation agent backed by AWS Bedrock.
- Claude 4.x model support (`claude-sonnet-4-5`, `claude-haiku-4-5`) with the haiku variant as default.
- Native Bedrock tool-calling wired through `homeassistant.helpers.llm.Tool` so Claude can invoke Home Assistant services directly (`HassCallService` tool).
- System-prompt generation from exposed entities and areas, with Jinja templating and per-turn refresh.
- Config flow with AWS credential validation via `bedrock:ListFoundationModels`, and an options flow for model parameters and memory behavior.
- `boto3` calls pushed onto the executor so the event loop is never blocked.
- Allowlist-based safety boundaries on the service-calling tool (`SERVICE_TOOL_ALLOWED_DOMAINS`, `SERVICE_TOOL_ALLOWED_SERVICES`, `ALLOWED_SERVICE_CALL_ARGUMENTS`).

For the exact diff between any two versions, use git tags:

```bash
git log --oneline v1.0.35..v1.0.36
```

or view the release on GitHub at
`https://github.com/sparkleHazard/homeassistant-bedrock-ha-agent/releases`.
