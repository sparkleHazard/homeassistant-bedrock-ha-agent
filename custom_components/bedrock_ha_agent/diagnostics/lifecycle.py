"""Diagnostics lifecycle tools (reload, entity enable/disable, logger, check_config).

All tools inherit ConfigEditingTool and go through the PendingChange → approve → apply → UndoStack pipeline.

Tools:
- DiagnosticsReloadIntegration: reload all config entries for a domain (no-op undo per C1)
- DiagnosticsReloadConfigEntry: reload a single config entry (no-op undo per C1)
- DiagnosticsEntityEnable: set disabled_by=None on an entity (real inverse)
- DiagnosticsEntityDisable: set disabled_by="user" on an entity (real inverse)
- DiagnosticsLoggerSetLevel: call logger.set_level with {logger_name: level} (real inverse per C5)
- DiagnosticsCheckConfig: trigger homeassistant.check_config service (no-op undo)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.helpers import config_validation as cv, llm

from ..config_tools import ConfigEditingTool, RestoreFn
from ..config_tools.validation import (
    ValidationError,
    ValidationResult,
)
from ..config_tools.diff import (
    render_spoken_summary,
    render_unified_diff,
)
from ..config_tools.ha_client import registry

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


_LOGGER = logging.getLogger(__name__)


class DiagnosticsReloadIntegration(ConfigEditingTool):
    """Reload all config entries for a given integration domain. One-way (no real undo)."""

    name = "DiagnosticsReloadIntegration"
    description = (
        "Reload all config entries for a given integration domain. "
        "This is a one-way operation (no real undo is possible). "
        "Use this to refresh an integration after configuration changes."
    )
    parameters = vol.Schema({vol.Required("domain"): cv.string})

    async def build_pre_state(self, hass: HomeAssistant, tool_input: llm.ToolInput) -> dict[str, Any] | None:
        domain = tool_input.tool_args["domain"]
        entries = hass.config_entries.async_entries(domain)
        return {
            "domain": domain,
            "entry_ids": [e.entry_id for e in entries],
            "entry_count": len(entries),
        }

    async def build_proposed_payload(self, hass: HomeAssistant, tool_input: llm.ToolInput) -> dict[str, Any] | None:
        return {"domain": tool_input.tool_args["domain"]}

    async def validate(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> ValidationResult:
        if proposed is None or pre_state is None:
            return ValidationResult.failure([ValidationError(code="missing_data", message="Missing proposed or pre_state")])
        # Guard: refuse self-reload of our own integration
        if proposed["domain"] == "bedrock_ha_agent":
            return ValidationResult.failure([
                ValidationError(
                    code="cannot_reload_self",
                    message="Cannot reload bedrock_ha_agent; would kill in-flight tool call",
                )
            ])
        # Warn if no entries exist
        if pre_state["entry_count"] == 0:
            return ValidationResult.failure([
                ValidationError(
                    code="no_entries",
                    message=f"Domain '{proposed['domain']}' has no config entries to reload",
                )
            ])
        return ValidationResult.success()

    def build_proposed_summary(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        if proposed is None or pre_state is None:
            return "Would reload (invalid state)"
        domain = proposed["domain"]
        count = pre_state["entry_count"]
        return render_spoken_summary(
            "Would reload",
            f"integration '{domain}' ({count} {'entry' if count == 1 else 'entries'})",
        )

    def build_proposed_diff(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        if proposed is None or pre_state is None:
            return "N/A"
        domain = proposed["domain"]
        entry_ids = pre_state["entry_ids"]
        return render_unified_diff(
            {"domain": domain, "entry_ids": entry_ids},
            {"domain": domain, "entry_ids": entry_ids, "_action": "reload"},
        )

    async def build_restore_fn(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> RestoreFn:
        async def _noop_restore() -> dict[str, Any]:
            _LOGGER.info("reload is one-way; no state was restored")
            return {"restored": False, "reason": "reload is one-way"}
        return _noop_restore

    async def apply_change(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> dict[str, Any]:
        if proposed is None or pre_state is None:
            raise ValueError("Cannot apply change with missing data")
        for entry_id in pre_state["entry_ids"]:
            await hass.config_entries.async_reload(entry_id)
        return {
            "status": "applied",
            "domain": proposed["domain"],
            "reloaded_entry_ids": pre_state["entry_ids"],
        }

    def tool_warnings(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> list[str]:
        return ["This undo is a no-op; reload cannot be reversed."]


class DiagnosticsReloadConfigEntry(ConfigEditingTool):
    """Reload a single config entry by entry_id. One-way (no real undo)."""

    name = "DiagnosticsReloadConfigEntry"
    description = (
        "Reload a single config entry by entry_id. "
        "This is a one-way operation (no real undo is possible)."
    )
    parameters = vol.Schema({vol.Required("entry_id"): cv.string})

    async def build_pre_state(self, hass: HomeAssistant, tool_input: llm.ToolInput) -> dict[str, Any] | None:
        entry_id = tool_input.tool_args["entry_id"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            return {"entry_id": entry_id, "entry": None}
        return {
            "entry_id": entry_id,
            "domain": entry.domain,
            "title": entry.title,
        }

    async def build_proposed_payload(self, hass: HomeAssistant, tool_input: llm.ToolInput) -> dict[str, Any] | None:
        return {"entry_id": tool_input.tool_args["entry_id"]}

    async def validate(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> ValidationResult:
        if proposed is None or pre_state is None:
            return ValidationResult.failure([ValidationError(code="missing_data", message="Missing data")])
        if pre_state.get("entry") is None:
            return ValidationResult.failure([
                ValidationError(
                    code="unknown_entry",
                    message=f"Config entry '{proposed['entry_id']}' does not exist",
                )
            ])
        # Guard: refuse self-reload
        entry = hass.config_entries.async_get_entry(proposed["entry_id"])
        if entry and entry.domain == "bedrock_ha_agent":
            return ValidationResult.failure([
                ValidationError(
                    code="cannot_reload_self",
                    message="Cannot reload bedrock_ha_agent; would kill in-flight tool call",
                )
            ])
        return ValidationResult.success()

    def build_proposed_summary(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        if pre_state is None:
            return "Would reload (invalid state)"
        title = pre_state.get("title", "config entry")
        domain = pre_state.get("domain", "unknown")
        return render_spoken_summary(
            "Would reload",
            f"config entry '{title}' (domain: {domain})",
        )

    def build_proposed_diff(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        if pre_state is None:
            return "N/A"
        return render_unified_diff(
            {"entry_id": pre_state["entry_id"], "domain": pre_state.get("domain")},
            {"entry_id": pre_state["entry_id"], "domain": pre_state.get("domain"), "_action": "reload"},
        )

    async def build_restore_fn(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> RestoreFn:
        async def _noop_restore() -> dict[str, Any]:
            _LOGGER.info("reload is one-way; no state was restored")
            return {"restored": False, "reason": "reload is one-way"}
        return _noop_restore

    async def apply_change(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> dict[str, Any]:
        if proposed is None:
            raise ValueError("Cannot apply change with no proposed data")
        await hass.config_entries.async_reload(proposed["entry_id"])
        return {
            "status": "applied",
            "entry_id": proposed["entry_id"],
            "domain": pre_state.get("domain") if pre_state else None,
        }

    def tool_warnings(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> list[str]:
        return ["This undo is a no-op; reload cannot be reversed."]


class DiagnosticsEntityEnable(ConfigEditingTool):
    """Enable an entity by setting disabled_by=None. Real inverse (disable with previous origin)."""

    name = "DiagnosticsEntityEnable"
    description = (
        "Enable an entity by setting disabled_by=None. "
        "Only works on entities that are currently disabled by USER origin."
    )
    parameters = vol.Schema({vol.Required("entity_id"): cv.entity_id})

    async def build_pre_state(self, hass: HomeAssistant, tool_input: llm.ToolInput) -> dict[str, Any] | None:
        entity_id = tool_input.tool_args["entity_id"]
        entry = await registry.get_entity_registry_entry(hass, entity_id)
        if entry is None:
            return {"entity_id": entity_id, "entry": None}
        return {
            "entity_id": entity_id,
            "disabled_by": entry.get("disabled_by"),
            "name": entry.get("name") or entry.get("original_name"),
        }

    async def build_proposed_payload(self, hass: HomeAssistant, tool_input: llm.ToolInput) -> dict[str, Any] | None:
        return {"entity_id": tool_input.tool_args["entity_id"], "disabled_by": None}

    async def validate(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> ValidationResult:
        if proposed is None or pre_state is None:
            return ValidationResult.failure([ValidationError(code="missing_data", message="Missing data")])
        if pre_state.get("entry") is None:
            return ValidationResult.failure([
                ValidationError(
                    code="unknown_entity",
                    message=f"Entity '{proposed['entity_id']}' not found in registry",
                )
            ])
        # Check if already enabled
        if pre_state.get("disabled_by") is None:
            return ValidationResult.failure([
                ValidationError(
                    code="already_enabled",
                    message=f"Entity '{proposed['entity_id']}' is already enabled",
                )
            ])
        # F9: refuse if disabled_by is not USER
        disabled_by = pre_state.get("disabled_by")
        if disabled_by and disabled_by.lower() != "user":
            return ValidationResult.failure([
                ValidationError(
                    code="cannot_enable_non_user_disable",
                    message=f"Entity disabled_by={disabled_by!r}; only USER-origin disables are toggleable",
                )
            ])
        return ValidationResult.success()

    def build_proposed_summary(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        if proposed is None or pre_state is None:
            return "Would enable (invalid state)"
        name = pre_state.get("name") or proposed["entity_id"]
        return render_spoken_summary("Would enable", f"entity '{name}'")

    def build_proposed_diff(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        if proposed is None or pre_state is None:
            return "N/A"
        return render_unified_diff(
            {"entity_id": pre_state["entity_id"], "disabled_by": pre_state.get("disabled_by")},
            {"entity_id": proposed["entity_id"], "disabled_by": None},
        )

    async def build_restore_fn(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> RestoreFn:
        if pre_state is None:
            raise ValueError("Cannot build restore function without pre_state")
        entity_id = pre_state["entity_id"]
        original_disabled_by = pre_state.get("disabled_by")

        async def _restore() -> None:
            # Restore to previous disabled_by state
            await registry.update_entity_registry(hass, entity_id, disabled_by=original_disabled_by)
            _LOGGER.info(
                "Entity %s re-disabled (disabled_by=%s)",
                entity_id,
                original_disabled_by,
            )
        return _restore

    async def apply_change(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> dict[str, Any]:
        if proposed is None:
            raise ValueError("Cannot apply change without proposed data")
        await registry.update_entity_registry(hass, proposed["entity_id"], disabled_by=None)
        return {
            "status": "applied",
            "entity_id": proposed["entity_id"],
            "disabled_by": None,
        }


class DiagnosticsEntityDisable(ConfigEditingTool):
    """Disable an entity by setting disabled_by='user'. Real inverse (re-enable)."""

    name = "DiagnosticsEntityDisable"
    description = (
        "Disable an entity by setting disabled_by='user'. "
        "Only works on entities that are currently enabled or disabled by USER."
    )
    parameters = vol.Schema({vol.Required("entity_id"): cv.entity_id})

    async def build_pre_state(self, hass: HomeAssistant, tool_input: llm.ToolInput) -> dict[str, Any] | None:
        entity_id = tool_input.tool_args["entity_id"]
        entry = await registry.get_entity_registry_entry(hass, entity_id)
        if entry is None:
            return {"entity_id": entity_id, "entry": None}
        return {
            "entity_id": entity_id,
            "disabled_by": entry.get("disabled_by"),
            "name": entry.get("name") or entry.get("original_name"),
        }

    async def build_proposed_payload(self, hass: HomeAssistant, tool_input: llm.ToolInput) -> dict[str, Any] | None:
        return {"entity_id": tool_input.tool_args["entity_id"], "disabled_by": "user"}

    async def validate(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> ValidationResult:
        if proposed is None or pre_state is None:
            return ValidationResult.failure([ValidationError(code="missing_data", message="Missing data")])
        if pre_state.get("entry") is None:
            return ValidationResult.failure([
                ValidationError(
                    code="unknown_entity",
                    message=f"Entity '{proposed['entity_id']}' not found in registry",
                )
            ])
        # F9: refuse if already disabled by non-USER origin
        disabled_by = pre_state.get("disabled_by")
        if disabled_by and disabled_by.lower() != "user":
            return ValidationResult.failure([
                ValidationError(
                    code="cannot_modify_non_user_disable",
                    message=f"Entity disabled_by={disabled_by!r}; only USER-origin disables are toggleable",
                )
            ])
        # Check if already disabled by user
        if disabled_by and disabled_by.lower() == "user":
            return ValidationResult.failure([
                ValidationError(
                    code="already_disabled",
                    message=f"Entity '{proposed['entity_id']}' is already disabled by user",
                )
            ])
        return ValidationResult.success()

    def build_proposed_summary(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        if proposed is None or pre_state is None:
            return "Would disable (invalid state)"
        name = pre_state.get("name") or proposed["entity_id"]
        return render_spoken_summary("Would disable", f"entity '{name}'")

    def build_proposed_diff(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        if proposed is None or pre_state is None:
            return "N/A"
        return render_unified_diff(
            {"entity_id": pre_state["entity_id"], "disabled_by": pre_state.get("disabled_by")},
            {"entity_id": proposed["entity_id"], "disabled_by": "user"},
        )

    async def build_restore_fn(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> RestoreFn:
        if pre_state is None:
            raise ValueError("Cannot build restore function without pre_state")
        entity_id = pre_state["entity_id"]
        original_disabled_by = pre_state.get("disabled_by")

        async def _restore() -> None:
            # Restore to previous state (likely None = enabled)
            await registry.update_entity_registry(hass, entity_id, disabled_by=original_disabled_by)
            _LOGGER.info(
                "Entity %s re-enabled (disabled_by=%s)",
                entity_id,
                original_disabled_by,
            )
        return _restore

    async def apply_change(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> dict[str, Any]:
        if proposed is None:
            raise ValueError("Cannot apply change without proposed data")
        await registry.update_entity_registry(hass, proposed["entity_id"], disabled_by="user")
        return {
            "status": "applied",
            "entity_id": proposed["entity_id"],
            "disabled_by": "user",
        }


class DiagnosticsLoggerSetLevel(ConfigEditingTool):
    """Set logger level for one or more logger names. Real inverse (restore prior levels)."""

    name = "DiagnosticsLoggerSetLevel"
    description = (
        "Set log level for one or more logger names. "
        "Accepts free-form {logger_name: level} payload. "
        "Valid levels: DEBUG, INFO, WARNING, ERROR, CRITICAL."
    )
    # Schema: free-form dict of logger_name -> level_str
    parameters = vol.Schema(
        {cv.string: vol.All(vol.Upper, vol.In(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]))},
        extra=vol.ALLOW_EXTRA,
    )

    async def build_pre_state(self, hass: HomeAssistant, tool_input: llm.ToolInput) -> dict[str, Any] | None:
        """Snapshot current logger overrides and Python effective levels."""
        from homeassistant.components.logger.helpers import DATA_LOGGER

        logger_config = hass.data.get(DATA_LOGGER)
        if logger_config is None:
            return {"loggers": {}, "no_logger_integration": True}

        # Snapshot current overrides and effective levels
        loggers_snapshot = {}
        for logger_name in tool_input.tool_args.keys():
            override = logger_config.overrides.get(logger_name)
            py_logger = logging.getLogger(logger_name)
            effective = py_logger.getEffectiveLevel()
            loggers_snapshot[logger_name] = {
                "override": override,  # int or None
                "effective_level": effective,
            }
        return {"loggers": loggers_snapshot}

    async def build_proposed_payload(self, hass: HomeAssistant, tool_input: llm.ToolInput) -> dict[str, Any] | None:
        # Convert level strings to int via logging levels
        proposed = {}
        for logger_name, level_str in tool_input.tool_args.items():
            proposed[logger_name] = getattr(logging, level_str.upper())
        return proposed

    async def validate(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> ValidationResult:
        if pre_state is not None and pre_state.get("no_logger_integration"):
            return ValidationResult.failure([
                ValidationError(
                    code="logger_not_loaded",
                    message="Logger integration is not loaded",
                )
            ])
        # Schema already validated by parameters; just success
        return ValidationResult.success()

    def build_proposed_summary(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        if proposed is None:
            return "Would set log level (invalid state)"
        logger_count = len(proposed)
        logger_names = ", ".join(proposed.keys())
        return render_spoken_summary(
            "Would set log level for",
            f"{logger_count} {'logger' if logger_count == 1 else 'loggers'} ({logger_names})",
        )

    def build_proposed_diff(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        if proposed is None or pre_state is None:
            return "N/A"
        # Show before/after levels
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}
        for logger_name, level_int in proposed.items():
            old_override = pre_state["loggers"].get(logger_name, {}).get("override")
            before[logger_name] = logging.getLevelName(old_override) if old_override else "NOTSET"
            after[logger_name] = logging.getLevelName(level_int)
        return render_unified_diff(before, after)

    async def build_restore_fn(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> RestoreFn:
        """Restore prior logger levels."""
        if pre_state is None:
            raise ValueError("Cannot build restore function without pre_state")
        loggers_snapshot = pre_state["loggers"]

        async def _restore() -> None:
            from homeassistant.components.logger.helpers import set_log_levels

            # Build restore payload: {logger_name: old_level_int}
            restore_payload: dict[str, int] = {}
            for logger_name, snapshot in loggers_snapshot.items():
                old_override = snapshot.get("override")
                if old_override is not None:
                    restore_payload[logger_name] = old_override
                else:
                    # No previous override; restore to effective level (or NOTSET)
                    effective = snapshot.get("effective_level", logging.NOTSET)
                    restore_payload[logger_name] = effective

            set_log_levels(hass, restore_payload)
            _LOGGER.info("Logger levels restored: %s", restore_payload)
        return _restore

    async def apply_change(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> dict[str, Any]:
        """Apply logger level changes via logger.set_level service."""
        from homeassistant.components.logger.helpers import set_log_levels

        if proposed is None:
            raise ValueError("Cannot apply change without proposed data")
        set_log_levels(hass, proposed)
        return {
            "status": "applied",
            "loggers": {name: logging.getLevelName(level) for name, level in proposed.items()},
        }


class DiagnosticsCheckConfig(ConfigEditingTool):
    """Trigger homeassistant.check_config service and return the result. No-op undo."""

    name = "DiagnosticsCheckConfig"
    description = (
        "Trigger the homeassistant.check_config service to validate configuration files. "
        "This is a read-ish operation but can be noisy; no undo is performed."
    )
    parameters = vol.Schema({})

    async def build_pre_state(self, hass: HomeAssistant, tool_input: llm.ToolInput) -> dict[str, Any] | None:
        return {"action": "check_config"}

    async def build_proposed_payload(self, hass: HomeAssistant, tool_input: llm.ToolInput) -> dict[str, Any] | None:
        return {"action": "check_config"}

    async def validate(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> ValidationResult:
        # Always valid
        return ValidationResult.success()

    def build_proposed_summary(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        return render_spoken_summary("Would run", "configuration check")

    def build_proposed_diff(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        return render_unified_diff(None, {"action": "check_config"})

    async def build_restore_fn(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> RestoreFn:
        async def _noop_restore() -> None:
            _LOGGER.info("check_config is a read-ish check; no state was restored")
        return _noop_restore

    async def apply_change(self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> dict[str, Any]:
        """Call homeassistant.check_config with return_response=True."""
        result = await hass.services.async_call(
            "homeassistant",
            "check_config",
            blocking=True,
            return_response=True,
        )
        return {
            "status": "applied",
            "result": result,
        }

    def tool_warnings(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> list[str]:
        return ["This undo is a no-op; check_config is a read-ish operation."]


def get_tools(hass: "HomeAssistant", entry: "ConfigEntry") -> list[llm.Tool]:
    """Factory called by register_config_tools when the kill switch is on."""
    return [
        DiagnosticsReloadIntegration(),
        DiagnosticsReloadConfigEntry(),
        DiagnosticsEntityEnable(),
        DiagnosticsEntityDisable(),
        DiagnosticsLoggerSetLevel(),
        DiagnosticsCheckConfig(),
    ]
