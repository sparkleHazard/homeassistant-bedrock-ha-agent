<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-25 | Updated: 2026-04-26 -->

# bedrock_ha_agent

## Purpose
The AWS Bedrock conversation integration for Home Assistant. Registers a `ConversationEntity` that converts user utterances into Bedrock `InvokeModel` calls (streaming via Anthropic Messages), executes tool-use blocks against HA services, and returns the model's reply as an `IntentResponse`. Additionally provides Amazon Polly TTS, Amazon Transcribe STT, camera-snapshot vision input, token-usage sensors, and — when `CONF_ENABLE_CONFIG_EDITING` is on — a full suite of approval-gated natural-language config-editing tools for automations, scripts, scenes, helpers, Lovelace, and registries. Domain: `bedrock_ha_agent`. LLM API id: `bedrock_ha_agent_services`.

## Key Files

| File | Description |
|------|-------------|
| `manifest.json` | Integration metadata. **Single source of truth for the release version.** Declares `boto3`, `webcolors`, `amazon-transcribe` as Python requirements. Depends on `conversation` + `ai_task`. |
| `__init__.py` | `async_setup_entry` wiring: runs `_ha_api_smoke`, constructs `BedrockClient` + `UsageTracker` into `BedrockRuntimeData`, registers the `BedrockServicesAPI` LLM API, forwards setup to conversation/tts/stt/sensor platforms, wires the `bedrock_ha_agent.undo_last` service (admin-gated), and installs the update listener for the Haiku advisory. Defines `HassServiceTool`. |
| `runtime_data.py` | `BedrockRuntimeData` dataclass stored on `entry.runtime_data`. Fields: `pending` (per-conversation_id PendingChange), `undo` (per-conversation_id UndoStack), `last_config_editing_flag`, `last_model_warned_for`, `lovelace_mode`, `bedrock_client`, `usage`. |
| `const.py` | All config keys (`CONF_*`), defaults, allowlists, `AVAILABLE_MODELS` / `RECOMMENDED_MODELS`, Jinja prompt fragments, approval/undo token vocabularies (`APPROVAL_TOKENS`, `UNDO_TOKENS`, `BARE_APPROVAL_UTTERANCES`, `BARE_UNDO_UTTERANCES`), and `CONF_ENABLE_CONFIG_EDITING` (kill switch, default False). |
| `bedrock_client.py` | `BedrockClient` wraps `boto3 bedrock-runtime`. Streams responses, handles retry/backoff, records usage, substitutes prompt placeholders (both `<token>` and `{{token}}` syntaxes for back-compat). Uses `_runtime_usage_tracker(entry)` helper to read usage off `entry.runtime_data`. |
| `conversation.py` | `BedrockConversationAgent` (HA `ConversationEntity`). Owns `async_process` + the tool-calling loop via `_stream_one_bedrock_turn`. Contains the **approval interceptor** that inspects the first-utterance of each turn for approve/undo intent (via `_lookup_pending(runtime_data, conv_id)` with `_global` fallback) and routes accordingly BEFORE the turn hits Bedrock. Also implements `_check_past_tense_vs_pending` (AC17 confabulation guard) and `_split_proposal_for_stream`. |
| `conversation_helpers.py` | Pure helpers extracted from `conversation.py`: `BedrockResponse` dataclass, single-tool-call executor, intent-response builders. |
| `config_flow.py` | `BedrockConversationConfigFlow` (setup) + `BedrockConversationOptionsFlow` (reconfigure). `validate_aws_credentials` probes `bedrock.list_foundation_models`. `fetch_claude_inference_profiles` populates the model dropdown from `bedrock:ListInferenceProfiles` with a fallback. Options flow surfaces `CONF_ENABLE_CONFIG_EDITING` and the Haiku advisory trigger. |
| `aws_session.py` | Shared factory `build_session(...)` consumed by config flow, Bedrock client, Polly TTS, and Transcribe STT so they all build boto3 sessions identically. |
| `messages.py` | Pure translation of HA `Content` objects ↔ Bedrock Anthropic-Messages shapes, and of `llm.Tool` instances into Bedrock `toolSpec`. Cache-tags the last tool. |
| `device_info.py` | `DeviceInfo` dataclass + `get_exposed_devices(hass)` — enumerates exposed entities and formats attributes (e.g. `rgb_color` via `closest_color`). Feeds the `<devices>` / `{{devices}}` prompt placeholder. |
| `vision.py` | Camera-snapshot capture + base64-encoding into Bedrock image blocks. JPEG/PNG/GIF/WebP only. |
| `sensor.py` | Five sensors per entry: input-tokens-today, output-tokens-today, cached-tokens-today, cost-today (USD), cost-total (USD). Push-refreshed via `UsageTracker` callbacks. |
| `usage_tracker.py` | `UsageTracker` + `ModelPricing`. Per-model Anthropic pricing table keyed by substring match. Daily counters auto-reset at UTC midnight; total counters persist until reload. |
| `stt.py` | Amazon Transcribe streaming STT platform. |
| `tts.py` | Amazon Polly TTS platform. |
| `_ha_api_smoke.py` | Runs at integration setup AND in tests. Verifies every HA helper this integration imports exists on the installed HA version; raises `ConfigEntryNotReady` with an actionable "minimum HA version X.Y" message on mismatch. |
| `utils.py` | `closest_color(rgb_tuple)` — nearest CSS3 color name via `webcolors`. |
| `strings.json` | Source strings for HA's translation pipeline (config flow, options flow, service descriptions). |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `config_tools/` | Approval-gated config-editing tools, base class, validation, pending/undo state, diff rendering (see `config_tools/AGENTS.md`). Only mounted when `CONF_ENABLE_CONFIG_EDITING` is True. |
| `translations/` | Localized strings for the config/options flow UI (see `translations/AGENTS.md`). |

## For AI Agents

### Working In This Directory

- **Two-phase config-editing contract.** Tool calls like `ConfigAutomationCreate` MUST NOT mutate state in `async_call`. The base `ConfigEditingTool.async_call` (in `config_tools/__init__.py`) builds a `PendingChange`, stores it in `runtime_data.pending[conv_id]`, and returns a `pending_approval` tool_result payload with imperative/future-tense fields (`proposed_summary`, `proposed_diff`). The user approves in the next turn; the approval interceptor in `conversation.py::async_process` fires `apply_change`. Past-tense field names are a confabulation-guard violation (AC17).
- **Per-conversation state keyed off `conversation_id` with `_global` fallback.** HA's `llm_context` does NOT reliably thread `conversation_id` through to tool calls. `PendingChangeManager._resolve_key` falls back to a `_global` bucket, and the interceptor's `_lookup_pending` uses the same fallback on read. Keep these two paths symmetric; a divergence silently orphans pending changes.
- **Kill switch is load-bearing.** Every config-editing code path must be reachable only when `CONF_ENABLE_CONFIG_EDITING` is True. `register_config_tools` is the only entry point; do not add setup-time side effects outside that gate. The options-flow listener re-registers tools when the flag flips; test any new tool under both True and False.
- **Tool-arg shape is both flat and nested.** Claude Bedrock inconsistently wraps tool arguments. Use `ConfigEditingTool._extract_config(tool_args, metadata_keys)` — it accepts both `tool_args["config"]` and flat `tool_args`. Don't hand-roll this; the helper is canonical.
- **Prompt placeholders accept both syntaxes.** `BedrockClient._generate_system_prompt` substitutes both `<current_date>` / `{{current_date}}` and `<devices>` / `{{devices}}`. Historical users have either. If you add a placeholder, support both and update `DEFAULT_PROMPT` + all `PERSONA_PROMPTS` entries.
- **Allowlists are security boundaries.** `SERVICE_TOOL_ALLOWED_DOMAINS`, `SERVICE_TOOL_ALLOWED_SERVICES`, `ALLOWED_SERVICE_CALL_ARGUMENTS` in `const.py` gate `HassServiceTool`. Don't expand them casually.
- **Config vs. options split.** AWS credentials + region live in `entry.data` (setup flow). Everything else lives in `entry.options` (options flow). The conversation agent merges both (`{**entry.data, **entry.options}`) before reads.
- **Runtime data is a dataclass, not a dict.** Access it via attribute (`runtime_data.pending`, `runtime_data.usage`) — the v1.1.0 → v1.1.2 bugs were from holdover `.get("usage")` style reads. Use `_runtime_usage_tracker(entry)` if you need the UsageTracker from inside `bedrock_client.py`.
- **Model-family quirks.** `top_p` is only sent for non-Claude models. Adding a new model family means deciding (and testing) which Bedrock body fields apply.
- **Bedrock calls are streaming.** Use the chat_log delta-content stream API (`async_add_delta_content_stream` / `async_add_assistant_content_without_tools` — HA 2025.3+). Do not fall back to non-streaming.
- **Version bumps:** update `manifest.json` → add CHANGELOG entry → commit → `make release`.

### Testing Requirements
- Tests live in `../../tests/` and mock `boto3` at the client boundary — never make a real API call.
- Config-editing tests mock at the `config_tools/ha_client/` transport boundary; validation and tool-class tests stay in-memory.
- If you add a new `CONF_*` constant, add a test that asserts its default and that the config/options flow exposes it.
- If you add a new config-editing tool, add tests for: (a) `pending_approval` payload shape, (b) validation-failure path, (c) apply path, (d) restore_fn correctness (inverse operation).

### Common Patterns
- **All constants belong in `const.py`.** No `"foo"` string literals for config keys anywhere else.
- **Dataclasses for structured HA data**: `DeviceInfo`, `BedrockRuntimeData`, `BedrockResponse`, `PendingChange`, `UndoEntry`, `ModelPricing`.
- **Raise `HomeAssistantError`** for user-visible failures; catch and convert boto3 exceptions at the client boundary.
- **Error mapping in config flow**: `invalid_credentials` / `access_denied` / `cannot_connect` / `unknown` → `strings.json` key scheme. New errors need matching entries in `strings.json` and every `translations/*.json`.
- **Health sensor keys live on `UsageTracker`**, not on the entry. Sensors subscribe via the tracker's callback list.

## Dependencies

### Internal
- `config_tools/` — the config-editing toolset (only used when kill switch is on).
- `utils.closest_color` used by `device_info.py`.
- `const` imported by every other module.
- `runtime_data` imported by `bedrock_client`, `sensor`, `conversation`, and everything in `config_tools/`.
- `aws_session.build_session` used by `bedrock_client`, `tts`, `stt`, `config_flow`.

### External
- `homeassistant.components.conversation` — base `ConversationEntity`, `ChatLog`, streaming delta API.
- `homeassistant.helpers.llm` — `Tool`, `APIInstance`, `async_call_tool`, `async_register_api`.
- `homeassistant.helpers.entity_registry` / `area_registry` / `label_registry` / `template` — device enumeration, Jinja rendering, registry tools.
- `homeassistant.util.yaml` — YAML loading (returns `NodeDictClass`/`NodeStrClass` subclasses; `config_tools/diff.py::_to_plain` normalizes before dumping).
- `homeassistant.util.file.write_utf8_file_atomic` — atomic writes in `config_tools/ha_client/{automation,script,scene}.py`.
- `boto3` — Bedrock runtime + control-plane + Polly.
- `amazon_transcribe` — streaming STT.
- `webcolors` — CSS3 color-name lookup.

<!-- MANUAL: -->
