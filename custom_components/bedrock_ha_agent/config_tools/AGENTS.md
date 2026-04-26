<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-26 | Updated: 2026-04-26 -->

# config_tools

## Purpose
Approval-gated natural-language configuration editing. Mounted onto `BedrockServicesAPI` only when `CONF_ENABLE_CONFIG_EDITING` is True. Every tool here inherits `ConfigEditingTool` and follows an 8-hook contract: `build_pre_state`, `build_proposed_payload`, `validate`, `build_proposed_summary`, `build_proposed_diff`, `build_restore_fn`, `apply_change`, `tool_warnings`. The base class's `async_call` runs the first five hooks and returns a `pending_approval` tool_result payload — **it never mutates HA state**. The approval interceptor in `conversation.py::async_process` calls `apply_change` on the next turn after the user approves.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | `ConfigEditingTool` base class, `PendingApprovalResult` dataclass (imperative/future field names — AC17 confabulation guard), `RestoreFn` type alias, `register_config_tools(hass, entry, api)` entry point, `_extract_config(tool_args, metadata_keys)` helper that accepts both flat and nested tool-arg shapes. |
| `pending.py` | `PendingChange` dataclass + `PendingChangeManager` that keys changes by `conversation_id` with a `_global` fallback bucket (because HA's llm_context doesn't reliably carry conversation_id). TTL-based expiry. Also defines `_PAST_TENSE_TOKENS` used by the AC17 guard. |
| `undo.py` | `UndoEntry` + `UndoStack`. In-memory only (per Round-4 spec decision), per-(entry_id, conversation_id), cleared on HA restart. Each entry holds the async `restore_fn` that reverses the mutation. |
| `validation.py` | `ValidationError` + `ValidationResult`, plus per-domain validators (`validate_automation`, `validate_script`, `validate_scene`, `validate_helper`, `validate_lovelace_card`, `validate_entities_exist`, `extract_entity_ids_from_*`). **Does NOT call HA's `check_config`** — spec §3.d forbids it (reload side-effects risk). Schema + entity-existence lookup is the full gate. |
| `diff.py` | `render_unified_diff(before, after)` and `render_spoken_summary(verb, noun_phrase, ...)`. `_to_plain()` normalizes HA's `NodeDictClass`/`NodeStrClass`/`NodeListClass` YAML subclasses to plain types before `yaml.safe_dump` (v1.1.9 fix; without this, delete/edit paths crashed with `RepresenterError`). `render_spoken_summary` is TTS-safe: no diff markers, ≤200 chars, imperative/conditional verb. |
| `automation.py` | `ConfigAutomationCreate` / `Edit` / `Delete`. Object_id slugified from alias with collision-suffix handling. |
| `script.py` | `ConfigScriptCreate` / `Edit` / `Delete`. |
| `scene.py` | `ConfigSceneCreate` / `Edit` / `Delete`. |
| `helper.py` | `ConfigHelperCreate` / `Edit` / `Delete` for `input_boolean`, `input_number`, `input_select`, `input_text`, `input_datetime`, `input_button`, `timer`, `counter`. |
| `lovelace.py` | Lovelace dashboard + card editing via WebSocket commands (`lovelace/dashboards`, `lovelace/config`, `lovelace/config/save`, etc). Rejected in YAML-mode dashboards. |
| `registry.py` | Area / label / entity-registry tools. Area and label create tools use a shared-dict trick to capture generated IDs at apply-time for a restore_fn built before apply. |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `ha_client/` | Transport layer — wraps HA's filesystem YAML + registries + WS APIs. No schema, no approval gating, no tool classes (see `ha_client/AGENTS.md`). |

## For AI Agents

### Working In This Directory

- **The two-phase contract is load-bearing.** `async_call` NEVER mutates. It computes pre_state, proposed_payload, validation, summary, diff, restore_fn, stores a `PendingChange`, and returns a `pending_approval` payload. `apply_change` runs later from the interceptor. If you find yourself calling `ha_client.create_or_update_*` inside `async_call`, you've broken the contract.
- **Past-tense field names are forbidden** in the pending_approval payload. The model will pattern-match past-tense summaries as "already applied" and confabulate to the user. AC17 enforces this via `_check_past_tense_vs_pending` in `conversation.py`; if ≥3 hits show up in QA, switch the offending tool to `external=True` per the plan's Option C fallback.
- **Restore functions are the undo contract.** Every tool MUST build a real restore_fn in `build_restore_fn`. Pair table:
  - create → delete-by-object_id
  - update → update-to-pre_state
  - delete → create-with-pre_state
  - area rename → rename-back
  - label add → label delete
  - etc.
  No "TBD" restores. If an inverse doesn't exist, the tool doesn't ship.
- **Validation runs before the diff is shown.** A tool that fails validation returns `{"status": "validation_failed", "errors": [...]}` without ever becoming pending. This is the point — the user sees "I can't do that because X" instead of a broken diff.
- **Conversation-id vs _global bucket.** `PendingChangeManager._resolve_key` tries `conversation_id` then `_global`. The interceptor's `_lookup_pending` does the same. Keep these symmetric. Do not remove the fallback — HA's llm_context drops conversation_id somewhere between `async_process` and `async_call_tool`, and we can't route approval without it.
- **`_extract_config(tool_args, metadata_keys)` is canonical.** Claude Bedrock sometimes nests args under `config`, sometimes flattens them. Don't hand-roll key-fishing; the helper handles both shapes and strips the metadata keys you pass in (`object_id`, etc).
- **Tool warnings are advisory, not blocking.** Surface them in the pending_approval payload under `warnings`; don't fail the proposal on warning conditions.

### Testing Requirements
- Mock the `ha_client/` transport — never the filesystem, never real HA services.
- Every tool needs tests for: `pending_approval` shape, validation failure, apply success, restore_fn correctness.
- `tests/test_no_file_io.py` is an AST-level lint: no direct `open()`/`Path.write_*()`/`os.remove()` outside `ha_client/`. If you need raw I/O, put it in a new `ha_client/` module.
- `tests/test_past_tense_correction.py` is the AC17 guard regression.

### Common Patterns
- One class per (resource, verb). `ConfigAutomationCreate`, not `ConfigAutomationTool` with a `verb` arg.
- Schemas use `voluptuous`. `vol.Schema({...}, extra=vol.ALLOW_EXTRA)` for config bodies so users can pass HA-recognized keys we don't model.
- `get_tools(hass, entry)` is the factory each module exports; `register_config_tools` iterates them into the api.
- Slugify helpers use `re.sub(r"[^a-z0-9_]+", "_", s.lower()).strip("_")` then a 64-char cap. Falls back to a deterministic `unnamed_<type>` on empty.

## Dependencies

### Internal
- `ha_client/` — the transport for all mutations.
- `../runtime_data` — `_get_runtime_data(hass, entry_id)` resolves to the `BedrockRuntimeData` that holds the per-conversation pending/undo state.
- `../const` — kill switch (`CONF_ENABLE_CONFIG_EDITING`), approval/undo vocabularies, TTL defaults.

### External
- `homeassistant.helpers.llm` — `Tool` base class.
- `homeassistant.helpers.config_validation` — schema primitives.
- `voluptuous` — schema library.
- `yaml` (via `homeassistant.util.yaml`) — read side; write side goes through `ha_client/`.

<!-- MANUAL: -->
