"""Automation config-editing tools.

Each tool inherits ConfigEditingTool and implements the 8 hooks:
build_pre_state, build_proposed_payload, validate, build_proposed_summary,
build_proposed_diff, build_restore_fn, apply_change, tool_warnings.

Per Principle #1, async_call in the base class produces a PendingChange only;
these tools never write in async_call — apply_change is invoked later by the
Phase-3 interceptor after user approval.
"""
from __future__ import annotations

import logging
import re
from typing import Any, TYPE_CHECKING

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from custom_components.bedrock_conversation.config_tools import ConfigEditingTool
from custom_components.bedrock_conversation.config_tools.validation import (
    ValidationError,
    ValidationResult,
    extract_entity_ids_from_automation,
    validate_automation,
    validate_entities_exist,
)
from custom_components.bedrock_conversation.config_tools.diff import (
    render_spoken_summary,
    render_unified_diff,
)
from custom_components.bedrock_conversation.config_tools.ha_client import automation as ha_automation

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import llm


_LOGGER = logging.getLogger(__name__)


# Shared schema fragment for an automation config dict
_AUTOMATION_CONFIG_SCHEMA = vol.Schema({
    vol.Required("alias"): cv.string,
    vol.Required("trigger"): vol.All(cv.ensure_list, [dict]),
    vol.Optional("condition"): vol.All(cv.ensure_list, [dict]),
    vol.Required("action"): vol.All(cv.ensure_list, [dict]),
    vol.Optional("mode"): cv.string,
    vol.Optional("description"): cv.string,
    vol.Optional("id"): cv.string,
}, extra=vol.ALLOW_EXTRA)


class ConfigAutomationCreate(ConfigEditingTool):
    """Create a new automation. Inverse = delete."""

    name = "ConfigAutomationCreate"
    description = (
        "Create a new Home Assistant automation from a structured config. "
        "Returns a pending_approval proposal; the user must confirm before "
        "the automation is actually created."
    )
    parameters = vol.Schema({
        vol.Required("config"): _AUTOMATION_CONFIG_SCHEMA,
        vol.Optional("object_id"): cv.string,
    })

    async def build_pre_state(self, hass, tool_input):
        # Create has no pre-state.
        return None

    async def build_proposed_payload(self, hass, tool_input):
        config = dict(tool_input.tool_args["config"])
        # Assign a deterministic object_id if the caller didn't supply one
        object_id = tool_input.tool_args.get("object_id") or self._slugify_alias(config.get("alias", "new_automation"))
        config["_object_id"] = object_id  # convenience for apply_change; stripped before write
        return config

    async def validate(self, hass, proposed, pre_state):
        if proposed is None:
            return ValidationResult.failure([ValidationError(code="missing_payload", message="No proposed config")])
        # 1. Schema
        payload_without_marker = {k: v for k, v in proposed.items() if k != "_object_id"}
        schema_result = validate_automation(payload_without_marker)
        if not schema_result.ok:
            return schema_result
        # 2. Entity existence
        entity_ids = extract_entity_ids_from_automation(payload_without_marker)
        if entity_ids:
            ent_result = validate_entities_exist(hass, entity_ids)
            if not ent_result.ok:
                return ent_result
        return ValidationResult.success()

    def build_proposed_summary(self, proposed, pre_state):
        alias = (proposed or {}).get("alias", "a new automation")
        return render_spoken_summary(
            "Would add",
            f"automation {alias!r}",
        )

    def build_proposed_diff(self, proposed, pre_state):
        clean = {k: v for k, v in (proposed or {}).items() if k != "_object_id"}
        return render_unified_diff(None, clean)

    async def build_restore_fn(self, hass, proposed, pre_state):
        object_id = (proposed or {}).get("_object_id")

        async def _restore() -> None:
            if object_id:
                try:
                    await ha_automation.delete_automation(hass, object_id)
                except Exception as err:
                    _LOGGER.warning("undo of automation create failed: %s", err)
            await ha_automation.reload_automations(hass)

        return _restore

    async def apply_change(self, hass, proposed, pre_state):
        payload = {k: v for k, v in (proposed or {}).items() if k != "_object_id"}
        object_id = (proposed or {}).get("_object_id")
        await ha_automation.create_or_update_automation(hass, object_id, payload)
        await ha_automation.reload_automations(hass)
        return {"status": "applied", "object_id": object_id, "alias": payload.get("alias")}

    @staticmethod
    def _slugify_alias(alias: str) -> str:
        slug = re.sub(r"[^a-z0-9_]+", "_", alias.lower()).strip("_")
        return slug or "unnamed_automation"


class ConfigAutomationEdit(ConfigEditingTool):
    """Edit an existing automation. Inverse = update-to-before."""

    name = "ConfigAutomationEdit"
    description = (
        "Edit an existing Home Assistant automation by object_id. "
        "Returns a pending_approval proposal with a diff; the user must confirm."
    )
    parameters = vol.Schema({
        vol.Required("object_id"): cv.string,
        vol.Required("config"): _AUTOMATION_CONFIG_SCHEMA,
    })

    async def build_pre_state(self, hass, tool_input):
        object_id = tool_input.tool_args["object_id"]
        current = await ha_automation.get_automation(hass, object_id)
        if current is None:
            return None  # validate() will catch this
        return dict(current)

    async def build_proposed_payload(self, hass, tool_input):
        config = dict(tool_input.tool_args["config"])
        # Stash object_id so apply_change can recover it
        config["_object_id"] = tool_input.tool_args["object_id"]
        return config

    async def validate(self, hass, proposed, pre_state):
        if pre_state is None:
            return ValidationResult.failure([ValidationError(
                code="unknown_automation",
                message="No automation found with that object_id",
                path="object_id",
            )])
        payload_without_marker = {k: v for k, v in (proposed or {}).items() if k != "_object_id"}
        schema_result = validate_automation(payload_without_marker)
        if not schema_result.ok:
            return schema_result
        entity_ids = extract_entity_ids_from_automation(payload_without_marker)
        if entity_ids:
            ent_result = validate_entities_exist(hass, entity_ids)
            if not ent_result.ok:
                return ent_result
        return ValidationResult.success()

    def build_proposed_summary(self, proposed, pre_state):
        alias = (proposed or {}).get("alias") or (pre_state or {}).get("alias", "automation")
        return render_spoken_summary("Would update", f"automation {alias!r}")

    def build_proposed_diff(self, proposed, pre_state):
        clean = {k: v for k, v in (proposed or {}).items() if k != "_object_id"}
        return render_unified_diff(pre_state, clean)

    async def build_restore_fn(self, hass, proposed, pre_state):
        object_id = (proposed or {}).get("_object_id")

        async def _restore() -> None:
            if pre_state is not None and object_id:
                await ha_automation.create_or_update_automation(hass, object_id, pre_state)
                await ha_automation.reload_automations(hass)
        return _restore

    async def apply_change(self, hass, proposed, pre_state):
        object_id = (proposed or {}).get("_object_id")
        if object_id is None:
            _LOGGER.warning("ConfigAutomationEdit.apply_change: missing object_id in proposed payload")
            # Fallback to pre_state
            object_id = (pre_state or {}).get("id")
        payload = {k: v for k, v in (proposed or {}).items() if k != "_object_id"}
        await ha_automation.create_or_update_automation(hass, object_id, payload)
        await ha_automation.reload_automations(hass)
        return {"status": "applied", "object_id": object_id, "alias": payload.get("alias")}


class ConfigAutomationDelete(ConfigEditingTool):
    """Delete an automation. Inverse = create-with-prior-state."""

    name = "ConfigAutomationDelete"
    description = (
        "Delete an existing Home Assistant automation by object_id. "
        "Returns a pending_approval proposal; the user must confirm before deletion."
    )
    parameters = vol.Schema({
        vol.Required("object_id"): cv.string,
    })

    async def build_pre_state(self, hass, tool_input):
        object_id = tool_input.tool_args["object_id"]
        current = await ha_automation.get_automation(hass, object_id)
        if current is None:
            return None
        return {"object_id": object_id, "config": dict(current)}

    async def build_proposed_payload(self, hass, tool_input):
        # Delete has no post-state — the empty dict is the "after" so that the diff shows pure removal.
        return None

    async def validate(self, hass, proposed, pre_state):
        if pre_state is None:
            return ValidationResult.failure([ValidationError(
                code="unknown_automation",
                message="No automation found with that object_id",
                path="object_id",
            )])
        return ValidationResult.success()

    def build_proposed_summary(self, proposed, pre_state):
        alias = (pre_state or {}).get("config", {}).get("alias", "an automation")
        return render_spoken_summary("Would delete", f"automation {alias!r}")

    def build_proposed_diff(self, proposed, pre_state):
        # Diff shows the full pre_state being removed.
        return render_unified_diff((pre_state or {}).get("config"), None)

    async def build_restore_fn(self, hass, proposed, pre_state):
        if pre_state is None:
            async def _noop(): return None
            return _noop
        object_id = pre_state.get("object_id")
        config = pre_state.get("config")

        async def _restore() -> None:
            if object_id and config:
                await ha_automation.create_or_update_automation(hass, object_id, config)
                await ha_automation.reload_automations(hass)
        return _restore

    async def apply_change(self, hass, proposed, pre_state):
        if pre_state is None:
            raise RuntimeError("apply_change called without pre_state (validation should have blocked)")
        object_id = pre_state.get("object_id")
        await ha_automation.delete_automation(hass, object_id)
        await ha_automation.reload_automations(hass)
        return {"status": "applied", "object_id": object_id, "deleted_alias": pre_state.get("config", {}).get("alias")}


def get_tools(hass: "HomeAssistant", entry: "ConfigEntry") -> list:
    """Factory called by register_config_tools when the kill switch is on."""
    return [
        ConfigAutomationCreate(),
        ConfigAutomationEdit(),
        ConfigAutomationDelete(),
    ]
