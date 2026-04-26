# Changelog

All notable changes to this project are documented here.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions. Detailed per-release notes live on GitHub Releases; this file captures the higher-level history.

## 1.5.2 — CI/CD hardening + strict typing

### Added
- **Multi-job GitHub Actions pipeline** replacing the single `pytest` job. `.github/workflows/test.yml` now runs, in parallel on every push and PR: ruff lint, strict mypy, HACS validation (`hacs/action`), Home Assistant `hassfest`, the pytest suite pinned to the HA 2025.6.0 floor (with Codecov upload), and a non-blocking `test-latest` job against the HA nightly release so drift surfaces before users report it. Pip cache via `actions/setup-python@v5`'s `cache: pip` cuts CI wall time roughly in half.
- **Release workflow** (`.github/workflows/release.yml`) triggered by `workflow_dispatch` or a `v*` tag push. Reads the version from `custom_components/bedrock_ha_agent/manifest.json`, validates that a pushed tag matches the manifest, creates the tag (on manual dispatch), extracts the matching CHANGELOG section as release notes, and publishes via `softprops/action-gh-release@v2`. Uses the built-in `GITHUB_TOKEN`, no `gh` auth fiddling. The local `make release` target still works as a fallback.
- **Dependabot config** (`.github/dependabot.yml`): weekly pip + github-actions updates, grouped by domain (Home Assistant, pytest, tooling, AWS) so we get one rollup PR per group per week instead of N noise PRs.
- **Strict mypy across the integration.** `[tool.mypy]` in `pyproject.toml` with `strict = true`, `ignore_missing_imports = true` for HA / boto3 / amazon-transcribe (no PEP 561 stubs). New `[tool.ruff]` config with `target-version = "py313"` and `per-file-ignores` for tests-only patterns (E402, F841). `mypy` and `ruff` added to `requirements-test.txt`.

### Changed
- **443 → 0 mypy errors** across 37 files. Almost all fixes were real type annotations (function return types, dict/list generics, narrow `isinstance` assertions before dict lookups). A handful of genuine defects were uncovered and fixed along the way — notably `RestoreFn = Callable[[], Awaitable[None]]` was widened to `Callable[[], Awaitable[None | dict[str, Any]]]` to match what `diagnostics/lifecycle.py`'s reload-undo functions actually return, and `_async_bootstrap_automations_yaml` had its return tuple annotation bumped from `tuple[bool, bool]` to `tuple[bool, bool, bool]` to match the 3-value unpack at the caller. Config flow return types now declare `ConfigFlowResult` instead of the parent-incompatible `FlowResult`.
- **Ruff auto-fix** removed 27 unused imports across the test suite and fixed a few other minor pyflakes issues. No runtime code affected.

### Tests
- 294 passing (3 skipped, 1 xpassed). Ruff + mypy both clean.

## 1.5.1 — Bundled brand icons

### Added
- `custom_components/bedrock_ha_agent/brand/icon.png` (256×256) and `brand/logo.png` (512×512), picked up automatically by HA 2026.3.0+ via the [Brands Proxy API](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api). The integration card in *Settings → Devices & services* now shows the Bedrock logo instead of the generic puzzle-piece placeholder. No manifest changes needed. On HA < 2026.3 the placeholder remains until the upstream `home-assistant/brands` repo ships an entry.

## 1.5.0 — AI Task image generation (`ai_task.generate_image`)

### Added
- **`GENERATE_IMAGE` support on the AI Task entity.** Automations and scripts can now call `ai_task.generate_image` against the Bedrock entity to produce a PNG, which HA stores in the `ai_task` media source and returns as a signed URL. Routed through the same `BedrockAITaskEntity` that already handles `generate_data`.
- **Three Bedrock image-generation model families** are supported, dispatched automatically by the new `image_model_family()` helper in `const.py`:
  - **Amazon Nova Canvas** (`amazon.nova-canvas-v1:0`) — `taskType: TEXT_IMAGE` body schema.
  - **Amazon Titan Image Generator G1 v1 / v2** — same `taskType` schema as Nova Canvas.
  - **Stability AI** (SD3.5 Large, Stable Image Core, Stable Image Ultra) — `mode: text-to-image` body schema. `CONTENT_FILTERED` finish reasons surface as a friendly `HomeAssistantError`.
- **New `CONF_IMAGE_MODEL_ID` option** in the options flow — a dropdown seeded with the curated list above, `custom_value=True` so power users can paste any future model id. Leaving it empty keeps image generation inert (the service call returns a clear "no image model selected" error).
- **New `BedrockClient.async_generate_image(prompt, options)`** — one-shot `invoke_model` path with the same retry / timeout / error-mapping plumbing as `async_generate_vision`. 60-second timeout (images take longer than text turns). Returns a `GeneratedImage` dataclass with raw bytes, mime type, width, height, and model id.

### Architecture
- No new entity, no new subentry type, no entity_id migration — the existing `ai_task.bedrock_ai_task` just advertises `GENERATE_IMAGE` in its supported-features mask after upgrade.
- Image models don't report token usage; `async_generate_image` wires `record_error` for failure paths but skips the per-token `tracker.record(...)` success path. A per-image cost counter is a follow-up.

### Tests
- `test_ai_task_entity_feature_flags` updated: `GENERATE_IMAGE` is now asserted present, not absent.
- New `tests/test_ai_task_image.py` covers `image_model_family` routing, per-family body shape, base64 decode round-trip, the content-filter error path, and the "no image model selected" guard.

## 1.4.1 — Fix AI Task entity naming

### Fixed
- **AI Task entity was registered as `ai_task.ai_task`** (too generic, no hint it's the Bedrock one) and its device showed up as **"Unnamed device"** in the UI. Root cause: v1.4.0 shipped the entity with `_attr_name = "AI Task"` and a minimal `device_info` that had only `identifiers` — no `name`, `manufacturer`, or `model`. With `_attr_has_entity_name = True`, HA derived `entity_id` from `_attr_name` alone, and the device had no display name. Fix:
  - `_attr_name = None` so entity_id defers to the device name (matches how `openai_conversation` and `google_generative_ai_conversation` ship).
  - Per-subentry `dr.DeviceInfo(identifiers=(DOMAIN, subentry.subentry_id), name=subentry.title, manufacturer="AWS", model="Bedrock", entry_type=SERVICE)` so each AI Task entity gets a distinguishable device. The subentry title drives the slug; fresh installs get `ai_task.bedrock_ai_task`.
  - New migration `_async_migrate_ai_task_entity_id` removes any v1.4.0 orphan entity (detected by `entity_id == "ai_task.ai_task"` or missing/invalid `config_subentry_id`) and its unnamed device; the platform then re-registers cleanly on the same startup. Fires a one-time `persistent_notification` so users know to update any automations referencing the old id.

### Migration notes for existing v1.4.0 installs
- On first startup after update, the old `ai_task.ai_task` entity and its "Unnamed device" will be removed, and a new `ai_task.bedrock_ai_task` entity will appear with a proper "Bedrock AI Task" device.
- A `persistent_notification` explains the rename. Automations referencing `ai_task.ai_task` need to be updated to the new id.

### Tests
- 275 passed, 3 skipped, 1 xpassed. Test fixtures updated to include the required `subentry.title` attribute (new device_info needs it).

## 1.4.0 — AI Task entity (`ai_task.generate_data`)

### Added
- **AI Task entity** implementing HA's [AI Task building block](https://www.home-assistant.io/integrations/ai_task/). Any automation or script can now ask Claude for text or structured JSON via `ai_task.generate_data` without going through the voice-assistant pipeline. The entity is `ai_task.bedrock_ha_agent_ai_task` and registers automatically alongside the conversation, TTS, STT, and sensor entities.
- **`GENERATE_DATA` + `SUPPORT_ATTACHMENTS`** supported features: plain-text prompts, structured responses (pass a `structure` schema), and multimodal attachments (images via `media-source://` URIs or local paths — requires a vision-capable model). `GENERATE_IMAGE` is not shipped; Claude on Bedrock does not generate images, so there is no provider.
- Tool access parity: the AI Task entity receives the same `llm_api` as the conversation entity, so `HassCallService`, config-editing tools (if enabled), and diagnostics tools (if enabled) are all reachable from `ai_task.generate_data` invocations. Use `CONF_LLM_HASS_API: null` in the options flow to disable tool access on both entities at once.
- **Subentry auto-provisioning:** on first setup after update, an `ai_task_data` subentry is created for each existing Bedrock config entry (idempotent — no duplicates on subsequent restarts). New installs create the subentry during initial setup. The config flow exposes `async_get_supported_subentry_types` so HA's UI can add additional AI Task entities per config entry if needed.

### Architecture
- New file `ai_task.py` (~300 LOC). Entity subclasses `ai_task.AITaskEntity + RestoreEntity`. `_async_generate_data` drives a minimal Bedrock tool-loop that mirrors the conversation entity's streaming path but skips the conversation-specific pre-turn logic (approval interceptor, past-tense check, diagnostics budget reset, history trimming).
- `Platform.AI_TASK` added to `PLATFORMS` tuple; no changes to conversation/TTS/STT/sensor platforms.
- `_attr_suggested_object_id = "bedrock_ha_agent_ai_task"` so new installs get a clean entity_id. No entity_id migration needed — the entity is new.

### Tests
- 7 new tests in `tests/test_ai_task.py` locking in: feature flags, base-class inheritance, unique_id scheme, subentry auto-creation (idempotent), platform subentry filtering, config-flow subentry registration, Platform.AI_TASK in PLATFORMS. 3 further tests (deep `_async_generate_data` paths requiring a mocked Bedrock streaming client) documented as skips for a future uplift.
- 275 passed, 3 skipped, 1 xpassed.

## 1.3.1 — Clean up conversation entity_id

### Changed
- **Conversation entity_id is now `conversation.bedrock_ha_agent`** instead of the auto-derived `conversation.bedrock_ha_agent_<config-entry-ulid>`. This matches the naming pattern used by the sensors, TTS, and STT entities (which were already clean). New installs get the tidy id from the start; existing installs are renamed automatically on first startup after update and see a one-time `persistent_notification` so any automations/scripts/dashboards referencing the old id can be updated.

### Migration behavior
- Idempotent: running against an already-migrated entry is a no-op.
- Collision-safe: if the target id is somehow taken (e.g. two Bedrock config entries), subsequent entries get `conversation.bedrock_ha_agent_2`, `_3`, etc.
- Fresh installs: `_attr_suggested_object_id = "bedrock_ha_agent"` is set on the entity; HA uses it on first registration so no migration runs.

### Tests
- 4 new tests in `tests/test_conversation_entity_migration.py` covering rename, already-clean no-op, fresh-install short-circuit, and collision suffixing. 268 passed, 0 skipped, 1 xpassed.

## 1.3.0 — Voice-friendly diagnostics responses

### Changed (user-visible)
- **Log diving is now ask-first.** When the user says something vague like "check the logs" or "look for errors," the agent is instructed to ask a clarifying question (level filter? specific integration? time window?) before querying. Unfiltered log fetches produce hundreds of lines that are painful over voice.
- **Summarize, don't recite.** The api_prompt addendum now tells Claude to summarize diagnostic tool results in one or two sentences (e.g., "MQTT reported 3 errors, the latest about missing command_topic") instead of reading entries back verbatim. Individual entries are only recited on explicit request.
- **New filter params on read tools:**
  - `DiagnosticsSystemLogList`: `level_filter` (ERROR/WARNING/INFO/DEBUG), `logger_contains` (substring match on logger name).
  - `DiagnosticsRepairsList`: `domain` (filter to one integration), `limit`.
  - `DiagnosticsHealthCheck`: `domain` (drill into one integration; no-arg returns a health summary instead of the full info dict).
- **Lower defaults:**
  - `DiagnosticsSystemLogList.limit`: 50 → 10.
  - `DiagnosticsLogbookRead.max_events`: 100 → 20; `hours_back`: 24 → 6.
  - `DiagnosticsRepairsList.limit`: unbounded → 20.

### Response shape trimmed
- System log entries drop `source`, `exception`, `first_occurred`, `count`; only `{level, logger, timestamp, message}` remain.
- Logbook events drop `context_*`, `domain`, `entity_id`, `icon`; only `{when, name, message, state}` remain.
- Repairs entries drop `is_fixable`, `is_persistent`, `translation_key`, `translation_placeholders`, `created`, `dismissed_version`; only `{domain, issue_id, severity}` remain.
- Per-message character cap (200 chars for system log, 160 for logbook) — long tracebacks are truncated with `…`.
- Health check returns a summary `{ha_version, integration_count, ok_count, errors: {domain: msg}}` by default instead of every integration's full info_dict.

### No production behavior change for other tools
- Config-editing, ExtendedServiceCall, lifecycle tools unchanged. Read-only log/state tools keep their existing approval semantics (immediate execute).

### Tests
- 264 passed, 0 skipped, 1 xpassed.

## 1.2.4 — Fix AttributeError on diagnostics tool dispatch

### Fixed
- **`AttributeError: 'LLMContext' object has no attribute 'conversation_id'`** on every diagnostics tool call — surfaced as "Unexpected error during intent recognition." v1.2.0 code keyed the per-turn budget on `llm_context.conversation_id`, but the real `homeassistant.helpers.llm.LLMContext` dataclass has no such field (its fields are `platform`, `context`, `language`, `assistant`, `device_id`). The v1.2.2 test suite used a `MagicMock(spec=llm.LLMContext)` with `conversation_id` attached as an extra attribute, so the mismatch never surfaced in tests. Fix:
  - New `_conv_id_from_context(llm_context)` helper reads `getattr(llm_context, 'conversation_id', None)` first (preserves test shape), then falls back to `llm_context.context.id` (the per-turn ULID from HA's `Context`), and finally to `_global`.
  - `reset_turn_budget` now clears ALL counters for an entry at `async_process` entry rather than keying on a single conv_id — the real semantics of "reset when the user talks to Claude" now match the real semantics of "budget tool calls within that response."

### Tests
- Two new regression guards in `tests/test_diagnostics_budget.py`:
  - `test_real_llm_context_without_conversation_id` — builds a dataclass mirroring the real `LLMContext` shape and drives `check_and_consume_budget`; fails if budget derivation ever `AttributeError`s on a real-shaped context.
  - `test_llm_context_dataclass_has_no_conversation_id` — guards the fallback-code-path assumption; if HA ever adds `conversation_id` to `LLMContext`, this test fails and we revisit.
- 264 passed, 0 skipped, 1 xpassed.

## 1.2.3 — Fix Bedrock tool-schema validation errors

### Fixed
- **Bedrock rejected the entire tool list with `ValidationException`** (user-visible as "That request didn't pass the AI service's validation"). Three distinct schema defects in the v1.2.1 voluptuous converter slipped past the v1.2.1 test suite because the tests didn't exercise every tool's parameters shape. Fixed:
  - **Function-as-key leaked into `properties`.** `DiagnosticsLoggerSetLevel` uses `vol.Schema({cv.string: ...}, extra=vol.ALLOW_EXTRA)` for free-form `{logger_name: level}` payloads. The converter stringified the `cv.string` function as the property key, producing a literal `"<function string at 0x10b74c180>"` — invalid JSON Schema. Fix: skip non-Required/Optional non-string keys from `properties` and rely on `additionalProperties: true` to describe them.
  - **`default` fields in input_schema.** Bedrock's JSON Schema subset rejects `default`; the converter was emitting it for every `vol.Optional(..., default=X)` key. Fix: drop `default` entirely.
  - **`vol.Any(None, dict)` became `type: string` with `default: null`.** `ExtendedServiceCall.target` and `data` are `vol.Any(None, dict)`. The converter returned `{}`, then the default-handling path slapped `type: string` and `default: null` on it. Fix: `vol.Any` now picks the first concrete non-None branch (so `vol.Any(None, dict)` becomes `type: object`).
- **Regression guards** added in `tests/test_bedrock_tool_schema.py`: assert no `default` in any converter output, assert function-typed keys are never property names, assert `vol.Any(None, dict)` produces `type: object`, and assert `DiagnosticsLoggerSetLevel` uses `additionalProperties: true` rather than empty properties.

### Tests
- 262 passed, 0 skipped, 1 xpassed (was 259 passed — +3 new regression tests).

## 1.2.2 — Integrate pytest-homeassistant async hass fixture (tests only)

### Tests
- Removed the synchronous `MagicMock`-based `mock_hass` fixture from `tests/conftest.py`. All tests that needed it now use the real async `hass` fixture from `pytest-homeassistant-custom-component` via `pytest_plugins = ["pytest_homeassistant_custom_component"]`, or construct their own inline `MagicMock` when only a stand-in object is required.
- Unblocked **7 previously-skipped tests** that had been waiting on real `hass` infrastructure:
  - 5 tests in `test_extended_service_call.py` covering read_safe immediate execution, mutating approval creation, denied-service refusal, unlisted-service refusal, and entity_id-required validation (ACs D44, D45, D48).
  - 1 test in `test_diagnostics_reload_undo.py` locking in the no-op undo contract (`{"restored": False, "reason": "reload is one-way"}`) for `DiagnosticsReloadIntegration`. Added a twin test for `DiagnosticsReloadConfigEntry`.
  - 1 end-to-end test in `test_bedrock_tool_schema.py::test_api_instance_end_to_end` that builds a real `BedrockServicesAPI` via `async_get_api_instance` and verifies every tool spec passes through `format_tools_for_bedrock` with a valid non-empty `input_schema` — this is the exact shape that would have caught the v1.2.1 bug pre-release.
- Ported 4 test files off the removed `mock_hass` fixture (`test_api_entry_resolution.py`, `test_automation_object_id.py`, `test_config_editing_lovelace.py`, `test_config_editing_script.py`, `test_past_tense_correction.py`) to inline `MagicMock()` per test.
- Tightened assertions on all 7 unblocked tests: they now check deterministic contract fields (exact status strings, specific error codes, exact restore-fn return dicts, invariant that mutating services DO NOT fire before approval) rather than permissive OR-of-many-strings matches.

### No production code changes
- Test suite: **259 passed, 0 skipped, 1 xpassed** (was 251 passed, 7 skipped). Runtime 1.07s (was 3.44s).

## 1.2.1 — Fix Bedrock tool-schema conversion

### Fixed
- **Bedrock received empty `input_schema` for every tool except `HassCallService`.** `messages.format_tools_for_bedrock` was only hand-rolling a JSON schema for `HassCallService`; every other tool (all 15 diagnostics tools, plus the full config-editing suite) advertised zero parameters to Claude. When Claude tried to call a tool that required arguments like `entity_id`, the request was malformed — surfaced to users as "Unexpected error during intent recognition." This was a latent bug in the config-editing port (1.1.0) that became sharply visible in 1.2.0 because diagnostics tools are the natural first choice for "check the logs"-style prompts.
- Added a generic voluptuous → JSON Schema converter (`_vol_schema_to_json_schema`) that handles `vol.Required`/`vol.Optional` keys, `cv.entity_id`/`cv.string`/`cv.slug` validators, `vol.All(int, vol.Range(...))`, `vol.Length`, `vol.In`, `vol.Any`, `vol.Schema({}, extra=vol.ALLOW_EXTRA)`, and nested `vol.Schema` recursion. Unknown validators fall back to a permissive empty schema with a warning log rather than crashing.
- Preserved the existing hand-written `HassCallService` schema (its voluptuous keys don't introspect cleanly).

### Tests
- New `tests/test_bedrock_tool_schema.py` — 9 passing tests covering the converter + an integration-style regression test that locks in non-empty properties for every diagnostics tool that declares required fields.

## 1.2.0 — Diagnostics & Control Tool Suite (opt-in)

### Added
- Opt-in diagnostics & control tool suite for Claude to help troubleshoot and administer Home Assistant. Disabled by default. Enable via Settings → Devices & Services → Bedrock HA Agent → Configure → "Enable diagnostics & control."
- **Log diving:** `DiagnosticsSystemLogList`, `DiagnosticsLogbookRead`, `DiagnosticsRepairsList`, `DiagnosticsHealthCheck` — read-only.
- **State & history:** `DiagnosticsStateRead`, `DiagnosticsStateHistory`, `DiagnosticsStatistics`, `DiagnosticsIntegrationList` — read-only.
- **Broader service calls:** `ExtendedServiceCall` with per-service classification — read-safe services (`persistent_notification.*`, `system_log.clear`, `zone.reload`, `homeassistant.update_entity`) execute immediately; state-mutating services (`automation.trigger`, `script.turn_on`, timer/counter/input_* helpers) go through the same pending-approval gate as the config-editing tools.
- **Lifecycle control:** `DiagnosticsReloadIntegration`, `DiagnosticsReloadConfigEntry`, `DiagnosticsEntityEnable`, `DiagnosticsEntityDisable`, `DiagnosticsLoggerSetLevel`, `DiagnosticsCheckConfig` — all approval-gated. Reload tools have a no-op undo (reload is one-way); entity enable/disable and logger level changes have real inverses snapshotted on apply.

### Safety
- Hard 64 KiB cap per tool response with lossy list-field truncation and a `truncated: true` marker.
- Per-turn budget (default 3, configurable 1-10) caps diagnostic tool-call loops in a single Bedrock turn.
- Secrets in payloads (`access_token`, `password`, `api_key`, `auth_token`) are redacted in both the echoed request and the service response.
- HA restart, recorder purge, and supervisor ops are on an explicit deny list.
- Self-reload of the bedrock_ha_agent integration is refused (would kill in-flight tool calls).
- Entities disabled by INTEGRATION / CONFIG_ENTRY / DEVICE origins cannot be toggled via diagnostics (HA restricts WS updates to USER origin).
- Flipping `Enable diagnostics & control` off immediately sweeps any pending diagnostic proposals for that entry.

### Added options
- `Enable diagnostics & control` (bool, default OFF)
- `Max log entries per request` (int, 10-500, default 50)
- `Max history lookback (hours)` (int, 1-168, default 24)
- `Diagnostic tool-call budget per turn` (int, 1-10, default 3)

### Known limitations
- HA restart is NOT offered as a tool. Use HA's own UI or `homeassistant.restart` service directly.
- `ExtendedServiceCall` is an explicit allowlist — services not listed there are refused by design.
- Reload operations have no real undo (push a no-op UndoEntry to preserve the undo-stack invariant).
- Long-term statistics are read-only; `recorder.purge` is denied.
- Logbook reads are limited to a single entity per call in v1.

## 1.1.15 — Distinguish "not found" from "sourced elsewhere" on edit/delete

### Changed
- When Claude tries to edit or delete an automation/script/scene that
  isn't in the file this integration manages (`automations.yaml`,
  `scripts/<id>.yaml`, `scenes/<id>.yaml`), the tool used to return a
  generic `unknown_<domain>` validation failure — even when the entity
  was plainly visible in HA's UI (because it was sourced from a
  package, `.storage`, or a different include).
- New shared helper `unknown_entry_error(hass, domain, object_id)`
  checks `hass.states` for the entity. If present in HA but not in our
  file, returns `{domain}_not_editable_by_agent` with a message that
  names the likely sources (package / .storage / other includes) so
  Claude can tell the user. If truly unknown, returns the old
  `unknown_{domain}` error unchanged.
- Wired into `ConfigAutomationEdit/Delete`, `ConfigScriptEdit/Delete`,
  and `ConfigSceneEdit/Delete`. Create paths unaffected.

### Tests
- Added positive + negative tests for the helper
  (`test_unknown_entry_error_truly_missing`,
  `test_unknown_entry_error_exists_elsewhere`).
- Existing `test_script_delete_unknown_object_id` now explicitly sets
  `hass.states.get` to return None to simulate the "really missing"
  case (the MagicMock default returned truthy, tripping the new
  exists-elsewhere branch).

## 1.1.14 — Revert orphan cleanup; correct the named-suffix misadvice

### Fixed
- **Reverted the v1.1.13 orphan cleanup.** The `state=unavailable +
  restored=true` fingerprint also matches real automations that happen
  to be unavailable at reload time (e.g. their backing integration is
  still booting). Field test deleted a live automation
  (`automation.garden_scare_away_animals`) that way. The cleanup is
  gone until HA exposes a signal that distinguishes registry stubs
  from merely-unavailable live entities.

### Changed
- **v1.1.11 notification wording was wrong.** It suggested named-suffix
  keys (`automation ui:` + `automation legacy:`) to run both layouts
  side-by-side, but HA only supports ONE `automation:` key at the top
  level — named suffixes are parsed as a different domain
  (`automation-ui`) and silently dropped with only a warning in
  `check_config`. The bootstrap notification now tells users to pick
  one layout: `automation: !include automations.yaml` (UI-editable) or
  `automation: !include_dir_merge_list automations/` (dir, not
  UI-editable). If both are present, it instructs the user to switch
  to the file form and migrate `/config/automations/` by hand.

## 1.1.13 — Clean orphan automation registry stubs on reload

### Fixed
- Agent-created automations were written correctly to `automations.yaml`
  and loaded by HA, but the UI kept showing an older stale entity
  (state `unavailable`, `restored: true`) left over from earlier
  versions' different storage paths (v1.1.0-v1.1.7 tried `.storage`,
  per-file directories, and collision-suffixed object_ids). The stub
  occupied the `entity_id` slot and masked the real, loaded automation.
- `reload_automations()` now runs a cleanup pass after `automation.reload`:
  scans the entity registry for `automation.*` entries whose `unique_id`
  isn't present in `automations.yaml`, and removes only those that are
  currently `unavailable` with `restored: true` — the exact fingerprint
  of a registry stub whose config is gone. Live automations (from
  `.storage`, packages, or the YAML file itself) are never touched.

### Tests
- `test_ha_client_shape.py` shape tests now ignore private (leading
  underscore) coroutines; the new `_cleanup_orphan_registry_entries`
  helper is private and not part of the public transport API.

## 1.1.12 — Stop awaiting sync persistent_notification functions

### Fixed
- Setup crashed with `TypeError: 'NoneType' object can't be awaited`
  in `_async_bootstrap_automations_yaml` on installs that hadn't yet
  wired `!include automations.yaml`. Cause: `pn.async_create` and
  `pn.async_dismiss` are `@callback`-decorated **synchronous**
  functions in current HA — they return `None`, so awaiting them
  raises. v1.1.10/v1.1.11 also broke the pre-existing Haiku advisory
  in `_async_update_listener` for the same reason, but that code path
  only fires on options changes so it wasn't visible until the
  bootstrap ran at setup time. Both call sites now use the callbacks
  without `await`.

## 1.1.11 — Detect automations.yaml include specifically; coexist with the dir form

### Fixed
- The v1.1.10 bootstrap treated `!include_dir_merge_list automations/`
  as "wired" and skipped the persistent_notification in that case,
  even though our transport writes to `automations.yaml` and the dir
  form does NOT load that file. Users with only the dir layout would
  have silently-not-loaded agent automations.
- Bootstrap now checks specifically for `!include automations.yaml`.
  If it's missing but the dir form IS present, the notification tells
  the user to add a named suffix so BOTH layouts coexist:

  ```yaml
  automation ui: !include automations.yaml
  automation legacy: !include_dir_merge_list automations/
  ```

  HA merges entries from both keys into one automation list. Old
  `automations/<id>.yaml` files keep loading; new agent-created
  automations land in `automations.yaml` and stay UI-editable.

## 1.1.10 — Write automations to UI-editable `automations.yaml`

### Fixed
- Agent-created automations landed in `automations/<object_id>.yaml`
  under the directory-merge layout — they loaded correctly but the HA
  UI editor refused to open them with the warning "This automation
  cannot be edited from the UI, because it is not stored in the
  automations.yaml file, or doesn't have an ID." HA's config.automation
  integration hardcodes the filename `automations.yaml` for the UI
  editor's round-trip path (`CONFIG_PATH` in
  `homeassistant/components/config/automation.py`).
- `config_tools/ha_client/automation.py` rewritten to upsert into a
  flat `automations.yaml` (list of `{id, alias, ...}` dicts, the exact
  shape the UI editor produces). List entries are matched/replaced by
  `id` in place; new entries append. Old per-file writes under
  `automations/` are no longer produced — stale files there can be
  deleted manually.
- `_to_plain` normalization carried over so HA's `NodeDictClass` /
  `NodeStrClass` / `NodeListClass` YAML subclasses don't blow up
  `safe_dump` on round-trip (same defense as v1.1.9 for the diff path).

### Added
- Setup-time bootstrap in `__init__.py::_async_bootstrap_automations_yaml`.
  When `CONF_ENABLE_CONFIG_EDITING` is True (either at setup or when
  the option is toggled on), the integration:
    1. Creates `automations.yaml` as `[]` if it's missing.
    2. Scans `configuration.yaml` for
       `automation: !include automations.yaml` or
       `!include_dir_merge_list automations`. If neither is present,
       fires a one-time `persistent_notification` with the exact line
       the user needs to add and a note that HA must be restarted.
  The notification is idempotent via `notification_id` and is
  dismissed automatically if a later setup detects the include.

### Notes
- Scripts and scenes continue to use the v1.1.8 per-file-per-object
  layout. The HA UI has dedicated editors for both, and neither has
  reported the same UI-editability regression yet. If they do, mirror
  the automations.yaml approach then.
- Users who still have files under `automations/` from v1.1.7-v1.1.9
  can delete them manually; v1.1.10 won't touch that directory.

## 1.1.9 — Normalize HA YAML node subclasses before diffing

### Fixed
- Deleting an existing automation (and, by symmetry, editing one) raised
  `Unexpected error during intent recognition` with a
  `yaml.representer.RepresenterError: cannot represent an object`. Cause:
  HA's `util.yaml.load_yaml` returns `NodeDictClass`/`NodeStrClass`/
  `NodeListClass` — subclasses of `dict`/`str`/`list` that tag values with
  their source filename+line. The default `SafeDumper` has no representer
  for those subclasses, so `build_proposed_diff` blew up the moment
  `pre_state` (loaded from YAML for edit/delete) was fed to `safe_dump`.
- `config_tools/diff.py::_dump_yaml` now normalizes through a `_to_plain`
  pass first, converting NodeDictClass→dict, NodeListClass→list,
  NodeStrClass→str, and bools/ints/floats to their plain types recursively.
  Create proposals were unaffected (pre_state is None), which is why
  the bug only surfaced on the first delete attempt.

## 1.1.8 — Wrap automation/scene writes in a list for merge_list compatibility

### Fixed
- v1.1.7 wrote one YAML file per object into `automations/` but each file
  contained a bare dict. HA's `!include_dir_merge_list` loader
  (`annotatedyaml/loader.py::_include_dir_merge_list_yaml`) explicitly
  tests `isinstance(loaded_yaml, list)` and **silently skips files that
  aren't lists** — no warning, no error, just omitted from the merged
  config. Confirmed by reading the loader source after observing
  apply-succeeds-but-no-entity for the Nth time.
- Transport now wraps each automation and scene payload in a single-item
  list `[{...}]` so the merge_list loader picks them up. Scripts keep
  the dict-at-top-level form since the script integration's schema is
  dict-valued (and uses `!include_dir_merge_named` / `!include_dir_named`
  instead). `list_*` / `get_*` continue to handle both shapes on the
  read side so old-format files are still parseable.

## 1.1.7 — Per-file-per-object transport for automations, scripts, scenes

### Fixed
- Config-editing apply paths silently succeeded but never created entities.
  Root cause: the transport wrote to `/config/automations.yaml` (and
  `scripts.yaml`, `scenes.yaml`) but setups using the common
  `automation: !include_dir_merge_list automations/` pattern don't load
  that flat file at all — HA only scans the `automations/` directory.
  The write succeeded, HA fired `automation.reload`, nothing got picked up.
- Transport rewritten to write one file per object into the matching
  directory: `automations/<object_id>.yaml`, `scripts/<object_id>.yaml`,
  `scenes/<object_id>.yaml`. `create_or_update_*` creates the directory
  if missing, writes atomically via HA's `write_utf8_file_atomic`, and
  fires the matching `.reload` service. `delete_*` unlinks the file.
  `list_*` walks the directory; `get_*` reads the single file for an
  object_id directly (no scan).
- Matches the HA-standard directory-based config layout and cleanly
  coexists with hand-authored files. Our writes are isolated from
  whatever else is in those directories.

### Notes
- Users on the single-file layout (`automation: !include automations.yaml`)
  may need to switch to `!include_dir_merge_list automations/` for
  config-editing to work. Most HA installations that have grown past
  5-10 automations already use the directory form.

## 1.1.6 — Diagnostic logging in the apply path

### Changed
- Added INFO-level logging at every step of `ConfigAutomationCreate.apply_change`:
  `config_editing: applying proposal <id> tool=<name>`,
  `create_or_update_automation: target path=<path> object_id=<id>`,
  `create_or_update_automation: loaded N existing automations`,
  `create_or_update_automation: after write data has N automations (updated=<bool>)`,
  `create_or_update_automation: wrote N bytes to <path>`,
  `config_editing: applied proposal <id> tool=<name> result=<dict>`.
- Motivated by a silent-success bug: Claude's "Applied" reply arrived but no
  automation entity materialized and no error logged. With these lines the
  next reproduction pins the exact step that fails (wrong path? empty
  load? no write?) without needing a full strace.
- No behavior change.

## 1.1.5 — Accept flat and nested config shapes from Claude

### Fixed
- `ConfigAutomationCreate` / `Edit` / `ConfigSceneCreate` / `Edit` /
  `ConfigHelperCreate` / `Edit` crashed with `KeyError: 'config'` when
  Claude called them. The parameter schemas nested the resource config
  under `"config"`, but Claude on Bedrock inconsistently flattens tool
  arguments — sometimes passing `{"config": {"alias": "...", ...}}` and
  sometimes passing `{"alias": "...", "trigger": [...], ...}` at the
  top level. The tool-call shape is driven by Claude's reading of the
  schema but is not strictly enforced, so either shape can arrive.
- Added `ConfigEditingTool._extract_config(tool_args, metadata_keys)`
  that accepts either shape: if `tool_args["config"]` is a dict, use it
  verbatim; otherwise build a config dict from all `tool_args` minus
  the caller-named metadata keys (e.g. `("object_id",)` for
  automations, `("domain", "object_id")` for helpers). Automation,
  scene, and helper tools now route their config reads through this
  helper. Script tools already used the flat shape and are unchanged.

## 1.1.4 — Approval interceptor finds tool-written pending changes

### Fixed
- Approval ("yes" / "apply" / "do it") turns were never intercepted, so
  pending automation/script/scene/etc. proposals silently stayed pending
  forever while Claude handled each follow-up as a new conversation turn.
  Root cause: `ConfigEditingTool.async_call` stored pending changes under
  the ``"_global"`` key (because HA's `llm.LLMContext` doesn't thread
  `conversation_id` through `ConversationInput.as_llm_context`), but the
  interceptor in `conversation.py:async_process` looked them up under the
  real `user_input.conversation_id`. Two different keys, zero matches,
  100% miss rate. Fixed by having `PendingChangeManager.get_current` and
  `clear_current` fall back from the requested conversation_id to
  ``"_global"`` when nothing is stored at the first key, and by routing
  the interceptor's two direct `runtime_data.pending.get(...)` reads
  through a new `_lookup_pending(runtime_data, conversation_id)` helper
  that applies the same fallback rule. Tool-side writes stay at
  ``"_global"``; interceptor-side reads find them.

## 1.1.3 — Prompt placeholder syntax + config-tool nudging

### Fixed
- UNCLOSED_TAG translation error when viewing the system-prompt template in
  the options flow. The default prompt body contained literal `<current_date>`
  and `<devices>` tokens, which HA's options UI parses as unclosed HTML tags.
  Switched placeholder syntax to `{{current_date}}` / `{{devices}}` /
  `{{persona}}` — safe for HA's renderer, and still substituted correctly by
  `BedrockClient._generate_system_prompt`. The legacy `<…>` syntax continues
  to work so custom prompts saved on earlier versions keep rendering.
- Config-editing tools were registered but never called. Root cause was in
  the DEFAULT_PROMPT body itself: six imperative bullets instructed Claude
  to call `HassCallService` for every request, with no mention of the
  config-editing tool family. Claude followed instructions and free-texted
  YAML for "create an automation" requests instead of calling
  ConfigAutomationCreate. New prompt explicitly separates runtime control
  (HassCallService) from configuration changes (Config* tools) and tells
  Claude to NEVER describe changes as YAML in chat when the matching
  config tool is available.

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
