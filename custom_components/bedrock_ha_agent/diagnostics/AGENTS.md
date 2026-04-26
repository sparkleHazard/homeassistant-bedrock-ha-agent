<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-26 | Updated: 2026-04-26 -->

# diagnostics

## Purpose
Read + controlled-write diagnostics tools for troubleshooting Home Assistant. 15 tools gated by `CONF_ENABLE_DIAGNOSTICS` (default False, independent of config editing). Reads are budget-capped (per-turn counter, 64 KiB response envelope). Mutating tools (`reload`, `entity_enable/disable`, `logger_set_level`, `check_config`) inherit `ConfigEditingTool` and flow through the PendingChange → approve → apply → UndoStack pipeline.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Gate + registration. Exports `get_tools(hass, entry)` returning all 15 tools when flag is on, else `[]`. Validates class names match `DIAGNOSTICS_TOOL_NAMES` frozenset. Adds `api_prompt` addendum explaining `<<UNTRUSTED>>` markers. |
| `base.py` | `DiagnosticsReadTool` base class. Shared helpers: `check_and_consume_budget`, `reset_turn_budget`, `redact_secrets`, `enforce_byte_cap`. Wraps `async_call` to enforce per-turn budget + response-size cap + secret redaction on every read. |
| `logs.py` | Read-only log-diving: `DiagnosticsSystemLogList`, `DiagnosticsLogbookRead`, `DiagnosticsRepairsList`, `DiagnosticsHealthCheck`. Log content wrapped in `<<UNTRUSTED>>...<<END_UNTRUSTED>>` markers. |
| `states.py` | State/integration inspection: `DiagnosticsStateRead` (strips GPS/SSID/MAC from `person.*`/`device_tracker.*`, strips `context.user_id` from all), `DiagnosticsIntegrationList`. |
| `history.py` | Historical reads: `DiagnosticsStateHistory` (significant_states, capped lookback), `DiagnosticsStatistics` (recorder statistics_during_period). |
| `services.py` | `ExtendedServiceCall` — broader-allowlist service dispatcher. Classifies via `DIAGNOSTICS_ALLOWED_SERVICES[service]["class"]` into `read_safe` (immediate) or `mutating` (routed to PendingChange pipeline). Denied services refused outright. |
| `lifecycle.py` | 6 approval-gated lifecycle tools: `DiagnosticsReloadIntegration`, `DiagnosticsReloadConfigEntry` (both return no-op UndoEntry with `"reload is one-way"`), `DiagnosticsEntityEnable`, `DiagnosticsEntityDisable` (refuse non-USER `disabled_by`), `DiagnosticsLoggerSetLevel` (deny silencing core/bootstrap/setup at error/critical), `DiagnosticsCheckConfig` (calls `async_check_ha_config_file`). |

## For AI Agents

### Safety Rails

1. **Budget per turn.** Each tool decrements `runtime_data.diagnostics_turn_counts[(conv_id, "current")]`. `reset_turn_budget` MUST be called at the start of every Bedrock turn in `conversation.py::async_process`. Forgetting this starves the model.
2. **Response cap.** 64 KiB per tool. `enforce_byte_cap` binary-searches the largest list field to fit, reserving metadata (`rows_returned`, `rows_available_estimate`, `truncation_reason`).
3. **Redaction covers key + regex value match.** Keys: `access_token`, `password`, `api_key`, `auth_token`, `bearer_token`, `bearer`, `authorization`, `client_secret`, `refresh_token`, AWS/secret/credentials/private_key, `cookie`, `session_id`, `pin`, `ssid`. Regexes: JWT, AWS access key, Bearer header, `sk-…`.
4. **`<<UNTRUSTED>>` envelopes on logs.** `DiagnosticsSystemLogList` and `DiagnosticsLogbookRead` wrap attacker-influenceable fields (message, exception, name) so Claude treats them as data. The `api_prompt` addendum in `__init__.py` explains the convention.
5. **Reload = no-op undo.** `DiagnosticsReloadIntegration.restore_fn` returns `{"restored": False, "reason": "reload is one-way"}`. UndoEntry summary/warnings contain the literal string `"reload is one-way"` — AC D43 enforces this.
6. **Per-service classification is authoritative.** `DIAGNOSTICS_ALLOWED_SERVICES` in `const.py` is the single source. Never add `if service == "..."` short-circuits — extend the classification dict.
7. **Flag flip-off sweeps pending proposals.** The update listener in `__init__.py` clears any pending change whose `tool_name in DIAGNOSTICS_TOOL_NAMES` when `CONF_ENABLE_DIAGNOSTICS` flips True → False.
8. **`DIAGNOSTICS_TOOL_NAMES` must match.** `__init__.py::get_tools` raises `RuntimeError` if exported class names drift from the frozenset. Keep them in lockstep.

### Testing Requirements
- Tests live in `tests/test_diagnostics_*.py` + `tests/test_extended_service_call.py` + `tests/test_past_tense_tokens.py`.
- Mock at the `config_tools/ha_client/` transport boundary.
- 6 tests skipped with documented reasons — need full HA pipeline integration fixtures to drive ExtendedServiceCall classification/approval paths end-to-end. Known v1.2.1+ uplift.

## Dependencies

### Internal
- `..config_tools` — reuses `ConfigEditingTool`, `PendingChange`, `UndoEntry`, `PendingChangeManager`.
- `..config_tools.ha_client.{system_log, logbook, history, states, repairs, health}` — read transport.
- `..const` — `DIAGNOSTICS_*` constants, allowlists, redaction keys, tool names, caps.
- `..runtime_data.BedrockRuntimeData` — hosts `diagnostics_turn_counts`, `last_diagnostics_flag`.

### External
- `homeassistant.components.logbook.processor.EventProcessor` — logbook reads (HA 2025.3+).
- `homeassistant.components.system_log.LogErrorHandler` — system_log records.
- `homeassistant.components.recorder` (`get_instance`, `statistics`, `history`) — historical reads.
- `homeassistant.components.logger.helpers.set_log_levels` — per-logger level dict.
- `homeassistant.helpers.check_config.async_check_ha_config_file` — config validation.
- `homeassistant.helpers.issue_registry` / `entity_registry` — repair issues, entity enable/disable.

<!-- MANUAL: -->
