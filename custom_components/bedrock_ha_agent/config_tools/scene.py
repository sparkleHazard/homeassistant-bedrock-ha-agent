"""Scene config-editing tools (AC7).

Three tools: ConfigSceneCreate, ConfigSceneEdit, ConfigSceneDelete.
Scene payloads: {"name": str, "entities": {entity_id: state_or_attrs}, "icon"?: str}.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.helpers import config_validation as cv, llm

from custom_components.bedrock_ha_agent.config_tools import (
    ConfigEditingTool,
    RestoreFn,
)
from custom_components.bedrock_ha_agent.config_tools.diff import (
    render_spoken_summary,
    render_unified_diff,
)
from custom_components.bedrock_ha_agent.config_tools.ha_client import scene
from custom_components.bedrock_ha_agent.config_tools.validation import (
    ValidationResult,
    validate_entities_exist,
    validate_scene,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_SCENE_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("entities"): vol.Schema({cv.entity_id: vol.Any(cv.string, dict)}),
        vol.Optional("icon"): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)


class ConfigSceneCreate(ConfigEditingTool):
    """Create a new scene."""

    name = "ConfigSceneCreate"
    description = "Create a new Home Assistant scene with the given configuration."
    parameters = vol.Schema(
        {
            vol.Required("object_id"): cv.string,
            vol.Required("config"): _SCENE_CONFIG_SCHEMA,
        }
    )

    async def build_pre_state(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict | None:
        """No pre-state for create."""
        return None

    async def build_proposed_payload(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict | None:
        """Return the scene config to create."""
        return dict(tool_input.tool_args["config"])

    async def validate(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> ValidationResult:
        """Validate schema + entity existence."""
        if proposed is None:
            return ValidationResult.failure(
                [{"code": "no_payload", "message": "Scene create requires a config payload"}]
            )
        # Schema validation
        result = validate_scene(proposed)
        if not result.ok:
            return result
        # Entity existence
        entity_ids = list(proposed.get("entities", {}).keys())
        return validate_entities_exist(hass, entity_ids)

    def build_proposed_summary(
        self, proposed: dict | None, pre_state: dict | None
    ) -> str:
        """Build TTS-safe summary."""
        scene_name = proposed.get("name", "unnamed") if proposed else "unnamed"
        return render_spoken_summary("Would add", f"scene '{scene_name}'")

    def build_proposed_diff(self, proposed: dict | None, pre_state: dict | None) -> str:
        """Build unified diff."""
        return render_unified_diff(None, proposed, fromfile="(new)", tofile="scene")

    async def build_restore_fn(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> RestoreFn:
        """Undo = delete the created scene."""
        object_id = self._object_id

        async def restore() -> None:
            await scene.delete_scene(hass, object_id)
            await scene.reload_scenes(hass)

        return restore

    async def apply_change(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> dict:
        """Create the scene."""
        object_id = self._object_id
        await scene.create_or_update_scene(hass, object_id, proposed)
        await scene.reload_scenes(hass)
        return {"object_id": object_id, "entity_id": f"scene.{object_id}"}

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        """Store object_id for use in apply/restore."""
        self._object_id = tool_input.tool_args["object_id"]
        return await super().async_call(hass, tool_input, llm_context)


class ConfigSceneEdit(ConfigEditingTool):
    """Edit an existing scene."""

    name = "ConfigSceneEdit"
    description = "Update an existing Home Assistant scene configuration."
    parameters = vol.Schema(
        {
            vol.Required("object_id"): cv.string,
            vol.Required("config"): _SCENE_CONFIG_SCHEMA,
        }
    )

    async def build_pre_state(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict | None:
        """Return current scene config."""
        object_id = tool_input.tool_args["object_id"]
        return await scene.get_scene(hass, object_id)

    async def build_proposed_payload(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict | None:
        """Return the updated scene config."""
        return dict(tool_input.tool_args["config"])

    async def validate(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> ValidationResult:
        """Validate schema + entity existence + scene exists."""
        if pre_state is None:
            from custom_components.bedrock_ha_agent.config_tools.validation import (
                ValidationError,
            )

            return ValidationResult.failure(
                [
                    ValidationError(
                        code="unknown_scene",
                        message=f"Scene '{self._object_id}' does not exist",
                    )
                ]
            )
        if proposed is None:
            from custom_components.bedrock_ha_agent.config_tools.validation import (
                ValidationError,
            )

            return ValidationResult.failure(
                [ValidationError(code="no_payload", message="Scene edit requires a config payload")]
            )
        # Schema validation
        result = validate_scene(proposed)
        if not result.ok:
            return result
        # Entity existence
        entity_ids = list(proposed.get("entities", {}).keys())
        return validate_entities_exist(hass, entity_ids)

    def build_proposed_summary(
        self, proposed: dict | None, pre_state: dict | None
    ) -> str:
        """Build TTS-safe summary."""
        scene_name = proposed.get("name", "unnamed") if proposed else "unnamed"
        return render_spoken_summary("Would update", f"scene '{scene_name}'")

    def build_proposed_diff(self, proposed: dict | None, pre_state: dict | None) -> str:
        """Build unified diff."""
        return render_unified_diff(pre_state, proposed, fromfile="before", tofile="after")

    async def build_restore_fn(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> RestoreFn:
        """Undo = restore the previous scene config."""
        object_id = self._object_id
        before = pre_state

        async def restore() -> None:
            await scene.create_or_update_scene(hass, object_id, before)
            await scene.reload_scenes(hass)

        return restore

    async def apply_change(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> dict:
        """Update the scene."""
        object_id = self._object_id
        await scene.create_or_update_scene(hass, object_id, proposed)
        await scene.reload_scenes(hass)
        return {"object_id": object_id, "entity_id": f"scene.{object_id}"}

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        """Store object_id for use in apply/restore."""
        self._object_id = tool_input.tool_args["object_id"]
        return await super().async_call(hass, tool_input, llm_context)


class ConfigSceneDelete(ConfigEditingTool):
    """Delete an existing scene."""

    name = "ConfigSceneDelete"
    description = "Delete an existing Home Assistant scene."
    parameters = vol.Schema(
        {
            vol.Required("object_id"): cv.string,
        }
    )

    async def build_pre_state(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict | None:
        """Return current scene config for undo."""
        object_id = tool_input.tool_args["object_id"]
        return await scene.get_scene(hass, object_id)

    async def build_proposed_payload(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict | None:
        """Delete has no proposed payload."""
        return None

    async def validate(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> ValidationResult:
        """Validate that the scene exists."""
        if pre_state is None:
            from custom_components.bedrock_ha_agent.config_tools.validation import (
                ValidationError,
            )

            return ValidationResult.failure(
                [
                    ValidationError(
                        code="unknown_scene",
                        message=f"Scene '{self._object_id}' does not exist",
                    )
                ]
            )
        return ValidationResult.success()

    def build_proposed_summary(
        self, proposed: dict | None, pre_state: dict | None
    ) -> str:
        """Build TTS-safe summary."""
        scene_name = pre_state.get("name", "unnamed") if pre_state else "unnamed"
        return render_spoken_summary("Would delete", f"scene '{scene_name}'")

    def build_proposed_diff(self, proposed: dict | None, pre_state: dict | None) -> str:
        """Build unified diff."""
        return render_unified_diff(pre_state, None, fromfile="scene", tofile="(deleted)")

    async def build_restore_fn(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> RestoreFn:
        """Undo = recreate the deleted scene."""
        object_id = self._object_id
        before = pre_state

        async def restore() -> None:
            await scene.create_or_update_scene(hass, object_id, before)
            await scene.reload_scenes(hass)

        return restore

    async def apply_change(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> dict:
        """Delete the scene."""
        object_id = self._object_id
        await scene.delete_scene(hass, object_id)
        await scene.reload_scenes(hass)
        return {"object_id": object_id}

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        """Store object_id for use in apply/restore."""
        self._object_id = tool_input.tool_args["object_id"]
        return await super().async_call(hass, tool_input, llm_context)


def get_tools(hass: HomeAssistant, entry: ConfigEntry) -> list[llm.Tool]:
    """Return the three scene config-editing tools."""
    return [
        ConfigSceneCreate(),
        ConfigSceneEdit(),
        ConfigSceneDelete(),
    ]
