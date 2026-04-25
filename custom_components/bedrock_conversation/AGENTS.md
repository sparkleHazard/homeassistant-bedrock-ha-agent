<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-25 | Updated: 2026-04-25 -->

# bedrock_conversation

## Purpose
The AWS Bedrock conversation integration for Home Assistant. Registers a `ConversationEntity` that converts user utterances into Bedrock `InvokeModel` calls, executes tool-use blocks against Home Assistant services, and returns the model's final reply as an `IntentResponse`. Domain: `bedrock_conversation`. LLM API id: `bedrock_conversation_services`.

## Key Files

| File | Description |
|------|-------------|
| `manifest.json` | Integration metadata. **Single source of truth for the release version.** Declares `boto3` and `webcolors` as Python requirements and depends on `conversation` + `ai_task`. |
| `__init__.py` | `async_setup_entry` wiring; registers the `BedrockServicesAPI` LLM API, constructs `BedrockClient` on `entry.runtime_data`, forwards setup to the `conversation` platform, and defines `HassServiceTool` — the single tool exposed to the model for device control. |
| `const.py` | All config keys (`CONF_*`), defaults, allowed service/domain allowlists, `AVAILABLE_MODELS` / `RECOMMENDED_MODELS`, and the Jinja prompt fragments (`PERSONA_PROMPTS`, `CURRENT_DATE_PROMPT`, `DEVICES_PROMPT`). Edit this file when adding a new model or config knob. |
| `bedrock_client.py` | `BedrockClient` — wraps `boto3` `bedrock-runtime`. Builds the system prompt from exposed entities, converts HA `llm.Tool` instances into Bedrock `toolSpec` schemas, translates conversation history into Bedrock messages, and calls `invoke_model` via `hass.async_add_executor_job`. Also defines the `DeviceInfo` dataclass. |
| `conversation.py` | `BedrockConversationAgent` (HA `ConversationEntity`). Owns the tool-calling loop: generate → parse tool calls → execute via `llm.async_call_tool` → feed results back → repeat up to `CONF_MAX_TOOL_CALL_ITERATIONS`. Also handles conversation memory trimming and optional per-turn system-prompt refresh. |
| `config_flow.py` | `BedrockConversationConfigFlow` (initial setup) and `BedrockConversationOptionsFlow` (reconfigure). `validate_aws_credentials` issues a `bedrock.list_foundation_models` call to verify credentials and maps AWS error codes to HA form errors. |
| `utils.py` | `closest_color(rgb_tuple)` — nearest CSS3 color name via `webcolors`. Used by `BedrockClient` when formatting `rgb_color` attributes into device prompts. |
| `strings.json` | Source strings for HA's translation pipeline. |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `translations/` | Localized strings consumed by the Home Assistant frontend (see `translations/AGENTS.md`). |

## For AI Agents

### Working In This Directory

- **Tool-calling flow**: `conversation.py` (loop) → `bedrock_client.py` (request shaping + API call) → `__init__.py::HassServiceTool` (service execution). When debugging tool calls, trace through all three.
- **Prompt construction**: `BedrockClient._generate_system_prompt` substitutes `<persona>`, `<current_date>`, `<devices>` placeholders and then renders the result as a Jinja template with the serialized device list. If you change the template format, update `DEFAULT_PROMPT` in `const.py` **and** all `PERSONA_PROMPTS` / `DEVICES_PROMPT` entries.
- **Allowlists are security boundaries.** `SERVICE_TOOL_ALLOWED_DOMAINS`, `SERVICE_TOOL_ALLOWED_SERVICES`, and `ALLOWED_SERVICE_CALL_ARGUMENTS` in `const.py` gate what the model can call. Don't add entries casually; an over-broad allowlist turns a prompt-injection into a real-world action.
- **Config vs. options split**: AWS credentials and region live in `entry.data` (setup flow). Everything else — model id, prompt, temperature, memory, tool iterations — lives in `entry.options` (options flow). The conversation agent merges both (`{**entry.data, **entry.options}`) before use.
- **Conversation history semantics**: Home Assistant's chat log supplies `SystemContent`, `UserContent`, `AssistantContent`, `ToolResultContent` objects. `_build_bedrock_messages` maps these onto Bedrock's `messages` list; system messages go in the top-level `system` field, not in `messages`. Keep that split if you add new content types.
- **Model-family quirks**: `top_p` is only sent for non-Claude models (Claude treats `temperature` and `top_p` as mutually exclusive). Adding a new model family means deciding (and testing) which Bedrock body fields apply.
- **Executor offload**: `invoke_model` is blocking; always call it via `hass.async_add_executor_job`. Do not `await` it directly.
- **Version bumps**: update `manifest.json` → commit → `make release`.

### Testing Requirements
- Tests live in `../../tests/` and mock `boto3` at the client boundary — never make a real API call.
- If you add a new `CONF_*` constant, add a test that asserts its default and that the config/options flow exposes it.
- If you extend the service allowlist, add an integration test through `HassServiceTool.async_call` to confirm the new service is validated.

### Common Patterns
- **All constants belong in `const.py`.** No `"foo"` string literals for config keys anywhere else.
- **Dataclasses for structured HA data**: `DeviceInfo` is the template-facing shape for exposed entities. Add fields there, not ad-hoc dicts, if you want them reachable from Jinja.
- **Raise `HomeAssistantError`** for user-visible failures from `BedrockClient`; lower-level boto3 exceptions should be caught and converted at the client boundary.
- **Error mapping in config flow**: follow the `invalid_credentials` / `access_denied` / `cannot_connect` / `unknown` → `strings.json` key scheme. New errors need matching entries in `strings.json` and every `translations/*.json`.

## Dependencies

### Internal
- `utils.closest_color` used by `bedrock_client.py`.
- `const` imported by every other module.
- `__init__.py::HassServiceTool` is the only tool currently wired into `BedrockServicesAPI`.

### External
- `homeassistant.components.conversation` — base `ConversationEntity` and chat-log helpers.
- `homeassistant.helpers.llm` — `Tool`, `APIInstance`, `async_call_tool`, `async_get_api`.
- `homeassistant.helpers.entity_registry` / `area_registry` / `template` — for device enumeration and Jinja rendering.
- `boto3` — Bedrock runtime and control-plane clients.
- `webcolors` — CSS3 color-name lookup.

<!-- MANUAL: -->
