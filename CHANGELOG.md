# Changelog

All notable changes to this project are documented here.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions. Detailed per-release notes live on GitHub Releases; this file captures the higher-level history.

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
`https://github.com/cronus42/homeassistant-aws-bedrock-conversation-agent/releases`.
