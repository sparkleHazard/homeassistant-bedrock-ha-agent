<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-26 | Updated: 2026-04-26 -->

# ha_client

## Purpose
Transport layer for HA config APIs. **No schema, no approval gating, no tool classes** — pure I/O against Home Assistant's filesystem YAML, registries, and WebSocket APIs. Every mutating operation that `config_tools/` runs from `apply_change` or a `restore_fn` lands here. Keeping this layer thin lets the tool-class layer stay side-effect-free in `async_call`, and lets tests mock at the transport boundary instead of the filesystem.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Marker docstring. No re-exports; import submodules directly (e.g. `from .ha_client import automation as ha_automation`). |
| `automation.py` | Per-file-per-object transport for automations. Writes `<config>/automations/<object_id>.yaml` wrapped in a **single-item list** (required by HA's `!include_dir_merge_list` loader, which silently skips non-list files). Atomic via `homeassistant.util.file.write_utf8_file_atomic`. Exports `list_automations`, `get_automation`, `create_or_update_automation`, `delete_automation`, `reload_automations`. |
| `script.py` | Per-file-per-object transport for scripts. Writes a **dict-at-top-level** (`{object_id: {...}}`) because the script schema is dict-valued under `!include_dir_merge_named`. Exports `list_scripts`, `get_script`, `create_or_update_script`, `delete_script`, `reload_scripts`. |
| `scene.py` | Per-file-per-object transport for scenes. Writes a **single-item list** like automations (scene schema is list-valued under `!include_dir_merge_list`). Exports `list_scenes`, `get_scene`, `create_or_update_scene`, `delete_scene`, `reload_scenes`. |
| `helper.py` | Helper entities (`input_boolean`, `input_number`, `input_select`, `input_text`, `input_datetime`, `input_button`, `timer`, `counter`). `SUPPORTED_HELPER_DOMAINS` is the canonical allowlist. Helpers are created via HA services / storage collections, not YAML files. |
| `registry.py` | Area, label, and entity-registry access via `homeassistant.helpers.area_registry` / `label_registry` / `entity_registry`. List/get/create/update/delete for areas + labels; rename/relabel/expose/unexpose for entities. |
| `lovelace.py` | Dashboards + cards via WebSocket commands: `lovelace/dashboards`, `lovelace/config`, `lovelace/config/save`, `lovelace/dashboards/create`, `lovelace/dashboards/update`, `lovelace/dashboards/delete`. Rejected for YAML-mode installs; caller must check `runtime_data.lovelace_mode` before invoking. |

## For AI Agents

### Working In This Directory

- **YAML loader shape matters.** HA's `!include_dir_merge_list` loader in `annotatedyaml/loader.py::_include_dir_merge_list_yaml` explicitly tests `isinstance(loaded_yaml, list)` and silently skips files that aren't lists — no warning, no error. Automations and scenes MUST be written wrapped in a single-item list `[{...}]`. Scripts use `!include_dir_merge_named` (dict-valued) and must be written dict-at-top-level `{object_id: {...}}`. Getting this wrong makes `apply_change` succeed while the entity never loads.
- **Read-side tolerates both shapes.** `list_*` and `get_*` handle both list-wrapped and bare-dict files so legacy/hand-authored files still parse. Writes must conform to the canonical shape above; reads must be permissive.
- **Writes are atomic.** Use `homeassistant.util.file.write_utf8_file_atomic(path, contents)`. Never open-for-write directly; a partial write under `automations/` with the target filename already present will be picked up by the next reload.
- **Always fire the corresponding `.reload` service** after a mutation: `automation.reload`, `script.reload`, `scene.reload`. `reload_*` helpers wrap these. A write without a reload leaves HA with stale in-memory state.
- **Read path uses HA's YAML loader.** `homeassistant.util.yaml.load_yaml` returns `NodeDictClass`/`NodeStrClass`/`NodeListClass` subclasses tagged with source-file+line. These aren't safe to hand to `yaml.safe_dump`; `config_tools/diff.py::_to_plain` normalizes them before dumping.
- **WebSocket ops need a `hass.components.websocket_api` connection.** Lovelace operations go through `hass.data["lovelace"].async_ws_*` or the WS command registry — see `lovelace.py` for the exact command names verified against HA ≥2024.12.0.
- **Registries are async but in-memory.** `area_registry.async_get(hass).async_create(...)` is non-blocking. Don't wrap these in executor jobs — they're not filesystem ops despite the `async_` prefix.

### Testing Requirements
- Tests mock `homeassistant.util.yaml.load_yaml`, `homeassistant.util.file.write_utf8_file_atomic`, and registry factory functions. No real filesystem.
- `tests/test_ha_client_shape.py` asserts the list-vs-dict write shape for each resource. If you change a transport's output shape, that test must be updated (and tell the reader why in the test's docstring).
- `tests/test_no_file_io.py` enforces that all filesystem I/O lives here. If you need raw I/O, add a function here and call it from `config_tools/`.

### Common Patterns
- Each module exports `list_*`, `get_*`, `create_or_update_*`, `delete_*`, `reload_*` (symmetrical surface).
- `_file_for(hass, object_id)` and `_<domain>_dir(hass)` are the private helpers for path construction; never compute paths inline.
- Errors on delete of missing objects raise `KeyError` — callers convert that to a validation error.
- Logging is INFO on write + path + byte count; WARNING on parse failure of individual files in list walks.

## Dependencies

### Internal
None — this is the lowest layer.

### External
- `homeassistant.util.yaml` (`load_yaml`, `dump`) — read side.
- `homeassistant.util.file.write_utf8_file_atomic` — atomic writes.
- `homeassistant.const.CONF_ID` — canonical id key.
- `homeassistant.helpers.area_registry` / `label_registry` / `entity_registry` — registry ops.
- `homeassistant.components.websocket_api` — Lovelace WS commands.

<!-- MANUAL: -->
