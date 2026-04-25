"""Script configuration editing tools."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.helpers import llm

from custom_components.bedrock_conversation.config_tools import (
    ConfigEditingTool,
    RestoreFn,
)
from custom_components.bedrock_conversation.config_tools.diff import (
    render_spoken_summary,
    render_unified_diff,
)
from custom_components.bedrock_conversation.config_tools.ha_client import script as ha_script
from custom_components.bedrock_conversation.config_tools.validation import (
    ValidationResult,
    extract_entity_ids_from_automation,
    validate_entities_exist,
    validate_script,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Script config schema — scripts use 'sequence' not 'action'
_SCRIPT_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required("alias"): str,
        vol.Required("sequence"): list,
        vol.Optional("mode"): vol.In(["single", "restart", "queued", "parallel"]),
        vol.Optional("icon"): str,
        vol.Optional("description"): str,
        vol.Optional("fields"): dict,
        vol.Optional("max"): int,
    }
)


class ConfigScriptCreate(ConfigEditingTool):
    """Tool for creating a new script."""

    name = "ConfigScriptCreate"
    description = "Create a new Home Assistant script with triggers and actions"
    parameters = vol.Schema(
        {
            vol.Required("object_id"): str,
            vol.Required("alias"): str,
            vol.Required("sequence"): list,
            vol.Optional("mode"): str,
            vol.Optional("icon"): str,
            vol.Optional("description"): str,
        }
    )

    async def build_pre_state(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict | None:
        """Check if script already exists (for create, should be None)."""
        object_id = tool_input.tool_args["object_id"]
        return await ha_script.get_script(hass, object_id)

    async def build_proposed_payload(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict | None:
        """Build the script config from tool args."""
        args = tool_input.tool_args
        payload = {
            "object_id": args["object_id"],  # Store for apply_change
            "alias": args["alias"],
            "sequence": args["sequence"],
        }
        if "mode" in args:
            payload["mode"] = args["mode"]
        if "icon" in args:
            payload["icon"] = args["icon"]
        if "description" in args:
            payload["description"] = args["description"]
        return payload

    async def validate(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> ValidationResult:
        """Validate the proposed script config."""
        if pre_state is not None:
            from custom_components.bedrock_conversation.config_tools.validation import (
                ValidationError,
            )

            return ValidationResult.failure(
                [
                    ValidationError(
                        code="script_already_exists",
                        message=f"Script '{pre_state.get('alias', 'unknown')}' already exists",
                    )
                ]
            )

        # Remove object_id before schema validation (it's metadata, not part of script config)
        script_config = {k: v for k, v in proposed.items() if k != "object_id"}

        # Schema validation
        result = validate_script(script_config)
        if not result.ok:
            return result

        # Entity existence validation
        entity_ids = extract_entity_ids_from_automation(proposed)
        return validate_entities_exist(hass, entity_ids)

    def build_proposed_summary(
        self, proposed: dict | None, pre_state: dict | None
    ) -> str:
        """Build TTS-safe spoken summary."""
        if proposed is None:
            return "Would delete the script"
        alias = proposed.get("alias", "unknown")
        return render_spoken_summary("Would add", f"script '{alias}'")

    def build_proposed_diff(self, proposed: dict | None, pre_state: dict | None) -> str:
        """Build unified diff."""
        return render_unified_diff(
            pre_state, proposed, fromfile="before", tofile="after"
        )

    async def build_restore_fn(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> RestoreFn:
        """Build undo function (delete the created script)."""
        object_id = proposed.get("object_id") if proposed else None

        async def restore() -> None:
            if object_id:
                await ha_script.delete_script(hass, object_id)
                await ha_script.reload_scripts(hass)

        return restore

    async def apply_change(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> dict:
        """Apply the script creation."""
        if proposed is None:
            raise ValueError("Cannot apply script creation with no payload")

        object_id = proposed.pop("object_id", None)
        if not object_id:
            raise ValueError("object_id is required")

        await ha_script.create_or_update_script(hass, object_id, proposed)
        await ha_script.reload_scripts(hass)

        return {
            "object_id": object_id,
            "entity_id": f"script.{object_id}",
        }


class ConfigScriptEdit(ConfigEditingTool):
    """Tool for editing an existing script."""

    name = "ConfigScriptEdit"
    description = "Edit an existing Home Assistant script"
    parameters = vol.Schema(
        {
            vol.Required("object_id"): str,
            vol.Optional("alias"): str,
            vol.Optional("sequence"): list,
            vol.Optional("mode"): str,
            vol.Optional("icon"): str,
            vol.Optional("description"): str,
        }
    )

    async def build_pre_state(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict | None:
        """Get the current script config."""
        object_id = tool_input.tool_args["object_id"]
        return await ha_script.get_script(hass, object_id)

    async def build_proposed_payload(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict | None:
        """Build the updated script config."""
        args = tool_input.tool_args
        pre_state = await self.build_pre_state(hass, tool_input)
        if pre_state is None:
            return None

        # Merge changes into existing config
        payload = dict(pre_state)
        if "alias" in args:
            payload["alias"] = args["alias"]
        if "sequence" in args:
            payload["sequence"] = args["sequence"]
        if "mode" in args:
            payload["mode"] = args["mode"]
        if "icon" in args:
            payload["icon"] = args["icon"]
        if "description" in args:
            payload["description"] = args["description"]

        payload["object_id"] = args["object_id"]
        return payload

    async def validate(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> ValidationResult:
        """Validate the proposed edit."""
        if pre_state is None:
            from custom_components.bedrock_conversation.config_tools.validation import (
                ValidationError,
            )

            return ValidationResult.failure(
                [
                    ValidationError(
                        code="unknown_script",
                        message="Script does not exist",
                    )
                ]
            )

        # Remove object_id before schema validation (it's metadata, not part of script config)
        script_config = {k: v for k, v in proposed.items() if k != "object_id"}

        # Schema validation
        result = validate_script(script_config)
        if not result.ok:
            return result

        # Entity existence validation
        entity_ids = extract_entity_ids_from_automation(proposed)
        return validate_entities_exist(hass, entity_ids)

    def build_proposed_summary(
        self, proposed: dict | None, pre_state: dict | None
    ) -> str:
        """Build TTS-safe spoken summary."""
        if proposed is None:
            return "Would not update (script not found)"
        alias = proposed.get("alias", "unknown")
        return render_spoken_summary("Would update", f"script '{alias}'")

    def build_proposed_diff(self, proposed: dict | None, pre_state: dict | None) -> str:
        """Build unified diff showing both sides."""
        return render_unified_diff(
            pre_state, proposed, fromfile="before", tofile="after"
        )

    async def build_restore_fn(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> RestoreFn:
        """Build undo function (restore previous config)."""
        object_id = proposed.get("object_id") if proposed else None
        original_config = dict(pre_state) if pre_state else None

        async def restore() -> None:
            if object_id and original_config:
                await ha_script.create_or_update_script(hass, object_id, original_config)
                await ha_script.reload_scripts(hass)

        return restore

    async def apply_change(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> dict:
        """Apply the script update."""
        if proposed is None:
            raise ValueError("Cannot apply script edit with no payload")

        object_id = proposed.pop("object_id", None)
        if not object_id:
            raise ValueError("object_id is required")

        await ha_script.create_or_update_script(hass, object_id, proposed)
        await ha_script.reload_scripts(hass)

        return {
            "object_id": object_id,
            "entity_id": f"script.{object_id}",
        }


class ConfigScriptDelete(ConfigEditingTool):
    """Tool for deleting a script."""

    name = "ConfigScriptDelete"
    description = "Delete a Home Assistant script"
    parameters = vol.Schema(
        {
            vol.Required("object_id"): str,
        }
    )

    async def build_pre_state(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict | None:
        """Get the current script config for undo."""
        object_id = tool_input.tool_args["object_id"]
        return await ha_script.get_script(hass, object_id)

    async def build_proposed_payload(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict | None:
        """Store metadata needed for delete (object_id), but mark as delete operation."""
        # For deletes, we store metadata in proposed_payload for apply_change to use
        return {"object_id": tool_input.tool_args["object_id"], "_delete": True}

    async def validate(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> ValidationResult:
        """Validate the delete operation."""
        if pre_state is None:
            from custom_components.bedrock_conversation.config_tools.validation import (
                ValidationError,
            )

            return ValidationResult.failure(
                [
                    ValidationError(
                        code="unknown_script",
                        message="Script does not exist",
                    )
                ]
            )
        return ValidationResult.success()

    def build_proposed_summary(
        self, proposed: dict | None, pre_state: dict | None
    ) -> str:
        """Build TTS-safe spoken summary."""
        if pre_state is None:
            return "Would not delete (script not found)"
        alias = pre_state.get("alias", "unknown")
        return render_spoken_summary("Would delete", f"script '{alias}'")

    def build_proposed_diff(self, proposed: dict | None, pre_state: dict | None) -> str:
        """Build unified diff showing deletion."""
        return render_unified_diff(
            pre_state, None, fromfile="before", tofile="after"
        )

    async def build_restore_fn(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> RestoreFn:
        """Build undo function (recreate the script)."""
        object_id = proposed.get("object_id") if proposed else None
        original_config = dict(pre_state) if pre_state else None

        async def restore() -> None:
            if object_id and original_config:
                # Remove our metadata marker before restoring
                clean_config = {k: v for k, v in original_config.items() if not k.startswith("_")}
                await ha_script.create_or_update_script(hass, object_id, clean_config)
                await ha_script.reload_scripts(hass)

        return restore

    async def apply_change(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> dict:
        """Apply the script deletion."""
        if proposed is None or pre_state is None:
            raise ValueError("Cannot delete script - not found")

        object_id = proposed.get("object_id")
        if not object_id:
            raise ValueError("object_id is required for delete")

        await ha_script.delete_script(hass, object_id)
        await ha_script.reload_scripts(hass)

        return {
            "object_id": object_id,
            "entity_id": f"script.{object_id}",
        }


def get_tools(hass: HomeAssistant, entry: ConfigEntry) -> list[llm.Tool]:
    """Return script editing tools."""
    return [
        ConfigScriptCreate(),
        ConfigScriptEdit(),
        ConfigScriptDelete(),
    ]
