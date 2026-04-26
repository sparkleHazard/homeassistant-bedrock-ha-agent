<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-25 | Updated: 2026-04-26 -->
<!-- MANUAL: -->

# tests

## Purpose
Automated pytest suite for the `bedrock_ha_agent` integration. Uses `pytest-homeassistant-custom-component` to simulate the HA runtime and mocks `boto3` + the `config_tools/ha_client/` transport so tests never touch real AWS or the filesystem. Invoked via `make test` (full coverage, release gate) or `make test-simple` (curated subset).

## Key Files

| File | Description |
|------|-------------|
| `conftest.py` | Shared fixtures: `mock_setup_entry`, `mock_unload_entry`, and a **custom synchronous `hass` MagicMock** that intentionally overrides the autouse `hass` fixture from `pytest-homeassistant-custom-component` to avoid asyncio entanglement in simple tests. |
| `test_init.py` | Integration constants, `HassServiceTool` schema/allowlists, `runtime_data` initialization, `_ha_api_smoke` failure modes. |
| `test_bedrock_client.py` | `DeviceInfo` dataclass, `BedrockClient` wiring, streaming response handling, placeholder substitution (dual-syntax). |
| `test_config_flow.py` | `validate_aws_credentials` AWS error-code → HA form-error mapping, options-flow `CONF_ENABLE_CONFIG_EDITING` + Haiku advisory. |
| `test_utils.py` | `closest_color` against known RGB inputs. |
| `test_translations.py` | Asserts `strings.json` keys are present in every `translations/*.json`. |
| `test_diff.py` | `render_unified_diff`, `render_spoken_summary`, TTS safety asserts, `_to_plain` normalization of `NodeDictClass`/`NodeStrClass` subclasses (v1.1.9 regression guard). |
| `test_validation.py` | Schema + entity-existence validators; asserts no `check_config` side effects (spec §3.d). |
| `test_pending_manager.py` | `PendingChangeManager` TTL expiry + `_global` key fallback (the v1.1.4 regression guard). |
| `test_undo_stack.py` | `UndoStack` per-(entry_id, conversation_id) isolation, restore ordering. |
| `test_undo_service_auth.py` | Admin-gated `bedrock_ha_agent.undo_last` service. |
| `test_ha_api_smoke.py` | `_ha_api_smoke.py`'s required-attr list resolves on the installed HA; failure message names the missing helper + introducing version. |
| `test_ha_client_shape.py` | Asserts automation/scene writes are single-item lists and script writes are dict-at-top-level (v1.1.8 regression guard). |
| `test_ha_client_lovelace.py` | WS-command shapes for Lovelace ops. |
| `test_ha_client_registry.py` | Area / label / entity-registry transport. |
| `test_no_file_io.py` | AST-level lint: no `open()`/`Path.write_*()`/`os.remove()` outside `config_tools/ha_client/`. |
| `test_config_editing_tool_base.py` | `ConfigEditingTool` 8-hook contract, `_extract_config` dual-shape handling (v1.1.5 regression guard). |
| `test_config_editing_automation.py` | `ConfigAutomation{Create,Edit,Delete}` — pending shape, validation failure, apply, restore. |
| `test_config_editing_script.py` | Same matrix for scripts. |
| `test_config_editing_scene.py` | Same matrix for scenes. |
| `test_config_editing_helper.py` | Same matrix for helper entities (all 8 domains). |
| `test_config_editing_registry.py` | Area/label/entity-registry tools including shared-dict restore pattern. |
| `test_config_editing_lovelace.py` | Dashboard + card tools; YAML-mode rejection path. |
| `test_config_editing_end_to_end.py` | Full turn: tool call → pending_approval payload → approval interceptor → apply. |
| `test_config_editing_voice.py` | Voice-pipeline TTS recorder — verifies spoken summaries stay TTS-safe (AC12). |
| `test_config_editing_usage.py` | Usage tracker increments on config-editing tool calls. |
| `test_past_tense_correction.py` | AC17 confabulation guard — past-tense words in a pending summary trigger the correction path. |
| `test_phase3_wiring.py` | `register_config_tools` respects the kill switch; re-registration on options-flow flip. |
| | **Diagnostics (v1.2.0)** |
| `test_diagnostics_flag_off.py` | Invisibility (AC D1): `get_tools` returns `[]` when `CONF_ENABLE_DIAGNOSTICS=False`; full 15-tool list when on. |
| `test_diagnostics_ha_api_smoke.py` | HA-API smoke (AC D46): imports every HA symbol the diagnostics plan depends on (`EventProcessor`, `LogErrorHandler`, `statistics_during_period`, `SERVICE_SET_LEVEL_SCHEMA`, `async_check_ha_config_file`, etc.) and asserts each resolves at the installed HA. |
| `test_diagnostics_redact_and_cap.py` | `redact_secrets` substring + regex coverage; `enforce_byte_cap` truncation with metadata (`rows_returned` / `rows_available_estimate`). |
| `test_diagnostics_budget.py` | AC D47 per-turn budget: allow N, reject N+1, reset clears counter, per-conversation isolation. |
| `test_extended_service_call.py` | Classification-table sanity (1 passing test + 5 skipped tests documenting full-pipeline coverage needed: read_safe immediate, mutating pending, denied refusal, unlisted refusal, entity_id-required refusal). |
| `test_diagnostics_reload_undo.py` | AC D43: reload UndoEntry's `restore_fn` is a no-op AND the summary/warnings contain "reload is one-way" (currently skipped pending ConfigEditingTool infrastructure in tests). |
| `test_past_tense_tokens.py` | AC D49: both `config_tools/pending.py::_PAST_TENSE_TOKENS` AND `conversation.py::_PAST_TENSE_REGEX` include the widened lifecycle tokens (`reloaded`, `restarted`, `disabled`, `enabled`). |
| `test_diagnostics_config_editing_nonregression.py` | Smoke test asserting existing config-editing test modules still import cleanly. |
| `test_automation_object_id.py` | Slugification, collision suffix, 64-char cap. |
| `test_api_entry_resolution.py` | `_get_runtime_data` resolution + error paths. |
| `test_concurrent_voice.py` | Multiple concurrent voice sessions don't cross-contaminate runtime state. |
| `test_system_prompt.py` *(legacy naming)* | Template substitution, Jinja rendering of the device list. |
| `test_device_context.py` *(legacy naming)* | `get_exposed_devices` against a mocked entity registry. |
| `test_tool_calling.py` *(legacy naming)* | End-to-end tool-calling loop, Bedrock response parsing, iteration limits. |

## For AI Agents

### Working In This Directory

- **Never make real AWS calls.** Every `boto3.client(...)` must be patched. The `hass` fixture in `conftest.py` is deliberately a MagicMock — simple tests here do not spin up a real HA instance.
- **Never touch the filesystem.** Mock `ha_client/` transport modules at the function level, not at `open()`. `test_no_file_io.py` is the enforcement; if your new code needs raw I/O, put it behind an `ha_client/` function first.
- **The custom `hass` fixture overrides the autouse one.** If you add a test that needs the real async HA fixture from `pytest-homeassistant-custom-component`, override `hass` locally in that test module or use a differently-named fixture — don't delete `conftest.py`'s version.
- **Coverage target is `custom_components.bedrock_ha_agent`.** Tests that import from other paths won't contribute to coverage and won't gate `make release`.
- **`make test-simple` is the curated fast subset** (`test_bedrock_client.py`, `test_config_flow.py`, `test_init.py`, `test_utils.py`). `make release` uses this — it's the release gate. The larger config-editing suite runs under `make test` but not `make release`. Be aware which bucket your test lands in.
- **Regression guards exist for every post-port bug** (v1.1.1 through v1.1.9). When fixing a bug, add or extend the matching `test_*.py` — don't let a silent fix ship without a test.
- **Some diagnostics tests are skipped pending HA integration fixtures.** `test_extended_service_call.py` skips 5 and `test_diagnostics_reload_undo.py` skips 1 because the `hass` MagicMock in `conftest.py` doesn't reproduce `hass.services` registration realistically enough to drive the full PendingChange pipeline. Promote these to integration-style tests (using `pytest-homeassistant-custom-component`'s real `hass` fixture and `SessionMaker` from recorder) when v1.2.1+ uplift lands.

### Testing Requirements
- Use `pytest.mark.asyncio` for async tests.
- Mock at the `boto3.client(...)` boundary (Bedrock client), not at the HTTP layer.
- Mock at the `ha_client/` function boundary (config editing), not at the YAML-file layer.
- Assert on structured results (`{"status": "pending_approval", ...}`, `{"status": "applied", ...}`) rather than free-text error messages.

### Common Patterns
- `AsyncMock` for awaitable methods on the `hass` mock; `MagicMock` for synchronous ones.
- Parametrize AWS error-code mappings and validation failure paths rather than duplicating cases.
- Tool-class tests use a small fixture factory to build a `ToolInput` with both flat and nested `tool_args` to exercise `_extract_config`.

## Dependencies

### Internal
- `custom_components.bedrock_ha_agent.*` — the code under test.

### External
- `pytest` + `pytest-asyncio`.
- `pytest-homeassistant-custom-component` — HA test harness, including the `hass` fixture this directory overrides.
- `hassil`, `home-assistant-intents` — HA intent infrastructure pulled in by `pytest-homeassistant-custom-component`.
- `PyTurboJPEG`, `av` — camera-snapshot / vision test deps (needs `libturbojpeg0-dev` in CI).
- `unittest.mock` — `AsyncMock`, `MagicMock`, `patch`.

<!-- MANUAL: -->
