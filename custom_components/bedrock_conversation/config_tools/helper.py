"""Helper entity config-editing tools.

Each tool inherits ConfigEditingTool and implements the 8 hooks:
build_pre_state, build_proposed_payload, validate, build_proposed_summary,
build_proposed_diff, build_restore_fn, apply_change, tool_warnings.

Per Principle #1, async_call in the base class produces a PendingChange only;
these tools never write in async_call — apply_change is invoked later by the
Phase-3 interceptor after user approval.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from custom_components.bedrock_conversation.config_tools import ConfigEditingTool
from custom_components.bedrock_conversation.config_tools.validation import (
    ValidationError,
    ValidationResult,
    validate_helper,
)
from custom_components.bedrock_conversation.config_tools.diff import (
    render_spoken_summary,
    render_unified_diff,
)
from custom_components.bedrock_conversation.config_tools.ha_client import helper as ha_helper
from custom_components.bedrock_conversation.config_tools.ha_client.helper import (
    SUPPORTED_HELPER_DOMAINS,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import llm


_LOGGER = logging.getLogger(__name__)


# Shared schema fragments
_HELPER_CREATE_SCHEMA = vol.Schema({
    vol.Required("domain"): vol.In(sorted(SUPPORTED_HELPER_DOMAINS)),
    vol.Required("config"): dict,  # type-specific; validation.validate_helper does the heavy lifting
})

_HELPER_EDIT_SCHEMA = vol.Schema({
    vol.Required("domain"): vol.In(sorted(SUPPORTED_HELPER_DOMAINS)),
    vol.Required("object_id"): cv.string,
    vol.Required("config"): dict,
})

_HELPER_DELETE_SCHEMA = vol.Schema({
    vol.Required("domain"): vol.In(sorted(SUPPORTED_HELPER_DOMAINS)),
    vol.Required("object_id"): cv.string,
})


class ConfigHelperCreate(ConfigEditingTool):
    """Create a new helper entity. Inverse = delete."""

    name = "ConfigHelperCreate"
    description = (
        "Create a new Home Assistant helper entity (input_boolean, input_number, "
        "input_select, input_text, input_datetime, input_button, timer, counter) "
        "from a structured config. Returns a pending_approval proposal; the user "
        "must confirm before the helper is actually created."
    )
    parameters = _HELPER_CREATE_SCHEMA

    async def build_pre_state(self, hass, tool_input):
        # Create has no pre-state.
        return None

    async def build_proposed_payload(self, hass, tool_input):
        domain = tool_input.tool_args["domain"]
        config = dict(tool_input.tool_args["config"])
        config["_domain"] = domain  # convenience for apply_change; stripped before validation
        return config

    async def validate(self, hass, proposed, pre_state):
        if proposed is None:
            return ValidationResult.failure([ValidationError(code="missing_payload", message="No proposed config")])

        domain = proposed.get("_domain")
        if not domain:
            return ValidationResult.failure([ValidationError(code="missing_domain", message="Domain not specified")])

        # Validate using the domain-specific validator
        payload_without_marker = {k: v for k, v in proposed.items() if k != "_domain"}
        return validate_helper(domain, payload_without_marker)

    def build_proposed_summary(self, proposed, pre_state):
        domain = (proposed or {}).get("_domain", "helper")
        name = (proposed or {}).get("name", "a new helper")
        return render_spoken_summary(
            "Would add",
            f"{domain} {name!r}",
        )

    def build_proposed_diff(self, proposed, pre_state):
        clean = {k: v for k, v in (proposed or {}).items() if k != "_domain"}
        return render_unified_diff(None, clean)

    async def build_restore_fn(self, hass, proposed, pre_state):
        domain = (proposed or {}).get("_domain")

        async def _restore() -> None:
            # object_id is populated by apply_change after creation
            object_id = (proposed or {}).get("_created_object_id") if proposed else None
            if domain and object_id:
                try:
                    await ha_helper.delete_helper(hass, domain, object_id)
                except Exception as err:
                    _LOGGER.warning("undo of helper create failed: %s", err)
            if domain:
                await ha_helper.reload_helper_domain(hass, domain)

        return _restore

    async def apply_change(self, hass, proposed, pre_state):
        domain = (proposed or {}).get("_domain")
        payload = {k: v for k, v in (proposed or {}).items() if not k.startswith("_")}
        object_id = await ha_helper.create_helper(hass, domain, payload)
        await ha_helper.reload_helper_domain(hass, domain)
        # Stash object_id for undo
        if proposed is not None:
            proposed["_created_object_id"] = object_id
        return {"status": "applied", "domain": domain, "object_id": object_id, "name": payload.get("name")}


class ConfigHelperEdit(ConfigEditingTool):
    """Edit an existing helper entity. Inverse = update-to-before."""

    name = "ConfigHelperEdit"
    description = (
        "Edit an existing Home Assistant helper entity by object_id. "
        "Returns a pending_approval proposal with a diff; the user must confirm."
    )
    parameters = _HELPER_EDIT_SCHEMA

    async def build_pre_state(self, hass, tool_input):
        domain = tool_input.tool_args["domain"]
        object_id = tool_input.tool_args["object_id"]
        current = await ha_helper.get_helper(hass, domain, object_id)
        if current is None:
            return None  # validate() will catch this
        return {"domain": domain, "object_id": object_id, "config": dict(current)}

    async def build_proposed_payload(self, hass, tool_input):
        domain = tool_input.tool_args["domain"]
        object_id = tool_input.tool_args["object_id"]
        config = dict(tool_input.tool_args["config"])
        # Stash domain/object_id so apply_change can recover them
        config["_domain"] = domain
        config["_object_id"] = object_id
        return config

    async def validate(self, hass, proposed, pre_state):
        if pre_state is None:
            return ValidationResult.failure([ValidationError(
                code="unknown_helper",
                message="No helper found with that object_id",
                path="object_id",
            )])
        domain = (proposed or {}).get("_domain")
        payload_without_marker = {k: v for k, v in (proposed or {}).items() if not k.startswith("_")}
        return validate_helper(domain, payload_without_marker)

    def build_proposed_summary(self, proposed, pre_state):
        domain = (proposed or {}).get("_domain") or (pre_state or {}).get("domain", "helper")
        name = (proposed or {}).get("name") or (pre_state or {}).get("config", {}).get("name", "helper")
        return render_spoken_summary("Would update", f"{domain} {name!r}")

    def build_proposed_diff(self, proposed, pre_state):
        clean = {k: v for k, v in (proposed or {}).items() if not k.startswith("_")}
        old_config = (pre_state or {}).get("config", {})
        return render_unified_diff(old_config, clean)

    async def build_restore_fn(self, hass, proposed, pre_state):
        if pre_state is None:
            async def _noop(): return None
            return _noop

        domain = pre_state.get("domain")
        object_id = pre_state.get("object_id")
        config = pre_state.get("config")

        async def _restore() -> None:
            if domain and object_id and config:
                await ha_helper.update_helper(hass, domain, object_id, config)
                await ha_helper.reload_helper_domain(hass, domain)
        return _restore

    async def apply_change(self, hass, proposed, pre_state):
        domain = (proposed or {}).get("_domain")
        object_id = (proposed or {}).get("_object_id")
        if domain is None or object_id is None:
            _LOGGER.warning("ConfigHelperEdit.apply_change: missing domain/object_id in proposed payload")
            raise RuntimeError("Missing domain or object_id")
        payload = {k: v for k, v in (proposed or {}).items() if not k.startswith("_")}
        await ha_helper.update_helper(hass, domain, object_id, payload)
        await ha_helper.reload_helper_domain(hass, domain)
        return {"status": "applied", "domain": domain, "object_id": object_id, "name": payload.get("name")}


class ConfigHelperDelete(ConfigEditingTool):
    """Delete a helper entity. Inverse = create-with-prior-state."""

    name = "ConfigHelperDelete"
    description = (
        "Delete an existing Home Assistant helper entity by object_id. "
        "Returns a pending_approval proposal; the user must confirm before deletion."
    )
    parameters = _HELPER_DELETE_SCHEMA

    async def build_pre_state(self, hass, tool_input):
        domain = tool_input.tool_args["domain"]
        object_id = tool_input.tool_args["object_id"]
        current = await ha_helper.get_helper(hass, domain, object_id)
        if current is None:
            return None
        return {"domain": domain, "object_id": object_id, "config": dict(current)}

    async def build_proposed_payload(self, hass, tool_input):
        # Delete has no post-state — None is the "after" so that the diff shows pure removal.
        return None

    async def validate(self, hass, proposed, pre_state):
        if pre_state is None:
            return ValidationResult.failure([ValidationError(
                code="unknown_helper",
                message="No helper found with that object_id",
                path="object_id",
            )])
        return ValidationResult.success()

    def build_proposed_summary(self, proposed, pre_state):
        domain = (pre_state or {}).get("domain", "helper")
        name = (pre_state or {}).get("config", {}).get("name", "a helper")
        return render_spoken_summary("Would delete", f"{domain} {name!r}")

    def build_proposed_diff(self, proposed, pre_state):
        # Diff shows the full pre_state being removed.
        old_config = (pre_state or {}).get("config", {})
        return render_unified_diff(old_config, None)

    def tool_warnings(self, proposed, pre_state) -> list[str]:
        """Warn about id regeneration on undo."""
        return [
            "Note: if undone, the helper's content will be restored but the internal "
            "id may differ if Home Assistant assigns a new auto-generated id."
        ]

    async def build_restore_fn(self, hass, proposed, pre_state):
        if pre_state is None:
            async def _noop(): return None
            return _noop

        domain = pre_state.get("domain")
        config = pre_state.get("config")

        async def _restore() -> None:
            if domain and config:
                await ha_helper.create_helper(hass, domain, config)
                await ha_helper.reload_helper_domain(hass, domain)
        return _restore

    async def apply_change(self, hass, proposed, pre_state):
        if pre_state is None:
            raise RuntimeError("apply_change called without pre_state (validation should have blocked)")
        domain = pre_state.get("domain")
        object_id = pre_state.get("object_id")
        await ha_helper.delete_helper(hass, domain, object_id)
        await ha_helper.reload_helper_domain(hass, domain)
        return {"status": "applied", "domain": domain, "object_id": object_id, "deleted_name": pre_state.get("config", {}).get("name")}


def get_tools(hass: "HomeAssistant", entry: "ConfigEntry") -> list:
    """Factory called by register_config_tools when the kill switch is on."""
    return [
        ConfigHelperCreate(),
        ConfigHelperEdit(),
        ConfigHelperDelete(),
    ]
