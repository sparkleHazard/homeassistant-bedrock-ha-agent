"""Registry config-editing tools (area / label / entity-registry).

Each tool inherits ConfigEditingTool and implements the 8 hooks:
build_pre_state, build_proposed_payload, validate, build_proposed_summary,
build_proposed_diff, build_restore_fn, apply_change, tool_warnings.

Area/label create tools use a shared-dict pattern to capture generated IDs at
apply-time for restore_fn (which is built BEFORE apply but needs the new ID).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from custom_components.bedrock_conversation.config_tools import ConfigEditingTool
from custom_components.bedrock_conversation.config_tools.validation import (
    ValidationError,
    ValidationResult,
)
from custom_components.bedrock_conversation.config_tools.diff import (
    render_spoken_summary,
    render_unified_diff,
)
from custom_components.bedrock_conversation.config_tools.ha_client import registry as ha_registry

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


_LOGGER = logging.getLogger(__name__)


# --- Area Tools ---


class ConfigAreaCreate(ConfigEditingTool):
    """Create a new area. Inverse = delete the created area."""

    name = "ConfigAreaCreate"
    description = (
        "Create a new Home Assistant area. "
        "Returns a pending_approval proposal; the user must confirm."
    )
    parameters = vol.Schema({
        vol.Required("name"): cv.string,
    })

    async def build_pre_state(self, hass, tool_input):
        return None

    async def build_proposed_payload(self, hass, tool_input):
        return {"name": tool_input.tool_args["name"]}

    async def validate(self, hass, proposed, pre_state):
        if not proposed or not proposed.get("name"):
            return ValidationResult.failure([
                ValidationError(code="missing_name", message="Area name is required")
            ])
        # Check for duplicate name
        areas = await ha_registry.list_areas(hass)
        for area in areas:
            if area["name"].lower() == proposed["name"].lower():
                return ValidationResult.failure([
                    ValidationError(
                        code="duplicate_area",
                        message=f"Area '{proposed['name']}' already exists",
                        path="name"
                    )
                ])
        return ValidationResult.success()

    def build_proposed_summary(self, proposed, pre_state):
        name = (proposed or {}).get("name", "new area")
        return render_spoken_summary("Would add", f"area {name!r}")

    def build_proposed_diff(self, proposed, pre_state):
        return render_unified_diff(None, proposed)

    async def build_restore_fn(self, hass, proposed, pre_state):
        # Pattern: shared dict to capture area_id at apply-time
        apply_result: dict[str, Any] = {}

        async def _restore() -> None:
            area_id = apply_result.get("area_id")
            if area_id:
                try:
                    await ha_registry.delete_area(hass, area_id)
                except Exception as err:
                    _LOGGER.warning("undo of area create failed: %s", err)

        # Stash the dict so apply_change can write to it
        self._apply_result = apply_result  # type: ignore[attr-defined]
        return _restore

    async def apply_change(self, hass, proposed, pre_state):
        name = (proposed or {}).get("name", "")
        area_id = await ha_registry.create_area(hass, name)
        # Capture the new area_id for restore_fn
        self._apply_result["area_id"] = area_id  # type: ignore[attr-defined]
        return {"status": "applied", "area_id": area_id, "name": name}


class ConfigAreaRename(ConfigEditingTool):
    """Rename an existing area. Inverse = rename back."""

    name = "ConfigAreaRename"
    description = (
        "Rename an existing Home Assistant area. "
        "Returns a pending_approval proposal; the user must confirm."
    )
    parameters = vol.Schema({
        vol.Required("area_id"): cv.string,
        vol.Required("new_name"): cv.string,
    })

    async def build_pre_state(self, hass, tool_input):
        area_id = tool_input.tool_args["area_id"]
        areas = await ha_registry.list_areas(hass)
        for area in areas:
            if area["area_id"] == area_id:
                return area
        return None

    async def build_proposed_payload(self, hass, tool_input):
        return {
            "area_id": tool_input.tool_args["area_id"],
            "name": tool_input.tool_args["new_name"],
        }

    async def validate(self, hass, proposed, pre_state):
        if pre_state is None:
            return ValidationResult.failure([
                ValidationError(
                    code="unknown_area",
                    message="Area not found",
                    path="area_id"
                )
            ])
        new_name = (proposed or {}).get("name", "")
        if not new_name:
            return ValidationResult.failure([
                ValidationError(code="missing_name", message="New name is required")
            ])
        # Check for duplicate name (excluding current area)
        areas = await ha_registry.list_areas(hass)
        area_id = (proposed or {}).get("area_id")
        for area in areas:
            if area["area_id"] != area_id and area["name"].lower() == new_name.lower():
                return ValidationResult.failure([
                    ValidationError(
                        code="duplicate_area",
                        message=f"Area '{new_name}' already exists",
                        path="new_name"
                    )
                ])
        return ValidationResult.success()

    def build_proposed_summary(self, proposed, pre_state):
        old_name = (pre_state or {}).get("name", "area")
        new_name = (proposed or {}).get("name", "new name")
        return render_spoken_summary(
            "Would rename",
            f"area {old_name!r} to {new_name!r}"
        )

    def build_proposed_diff(self, proposed, pre_state):
        return render_unified_diff(pre_state, proposed)

    async def build_restore_fn(self, hass, proposed, pre_state):
        area_id = (proposed or {}).get("area_id")
        old_name = (pre_state or {}).get("name")

        async def _restore() -> None:
            if area_id and old_name:
                try:
                    await ha_registry.update_area(hass, area_id, name=old_name)
                except Exception as err:
                    _LOGGER.warning("undo of area rename failed: %s", err)

        return _restore

    async def apply_change(self, hass, proposed, pre_state):
        area_id = (proposed or {}).get("area_id")
        new_name = (proposed or {}).get("name")
        await ha_registry.update_area(hass, area_id, name=new_name)
        return {"status": "applied", "area_id": area_id, "name": new_name}


class ConfigAreaDelete(ConfigEditingTool):
    """Delete an area. Inverse = re-create with a new area_id (emits warning)."""

    name = "ConfigAreaDelete"
    description = (
        "Delete an existing Home Assistant area. "
        "Returns a pending_approval proposal; the user must confirm."
    )
    parameters = vol.Schema({
        vol.Required("area_id"): cv.string,
    })

    async def build_pre_state(self, hass, tool_input):
        area_id = tool_input.tool_args["area_id"]
        areas = await ha_registry.list_areas(hass)
        for area in areas:
            if area["area_id"] == area_id:
                return area
        return None

    async def build_proposed_payload(self, hass, tool_input):
        return None

    async def validate(self, hass, proposed, pre_state):
        if pre_state is None:
            return ValidationResult.failure([
                ValidationError(
                    code="unknown_area",
                    message="Area not found",
                    path="area_id"
                )
            ])
        return ValidationResult.success()

    def build_proposed_summary(self, proposed, pre_state):
        name = (pre_state or {}).get("name", "area")
        return render_spoken_summary(
            "Would delete",
            f"area {name!r} — NOTE: undoing this will re-create with a new area_id"
        )

    def build_proposed_diff(self, proposed, pre_state):
        return render_unified_diff(pre_state, None)

    async def build_restore_fn(self, hass, proposed, pre_state):
        area_name = (pre_state or {}).get("name")

        async def _restore() -> None:
            if area_name:
                try:
                    await ha_registry.create_area(hass, area_name)
                except Exception as err:
                    _LOGGER.warning("undo of area delete failed: %s", err)

        return _restore

    async def apply_change(self, hass, proposed, pre_state):
        area_id = (pre_state or {}).get("area_id")
        await ha_registry.delete_area(hass, area_id)
        return {"status": "applied", "area_id": area_id}

    def tool_warnings(self, proposed, pre_state):
        return [
            "Undoing an area delete re-creates the area with a new area_id; "
            "entity references to the old id may need to be re-linked."
        ]


# --- Label Tools ---


class ConfigLabelCreate(ConfigEditingTool):
    """Create a new label. Inverse = delete the created label."""

    name = "ConfigLabelCreate"
    description = (
        "Create a new Home Assistant label. "
        "Returns a pending_approval proposal; the user must confirm."
    )
    parameters = vol.Schema({
        vol.Required("name"): cv.string,
    })

    async def build_pre_state(self, hass, tool_input):
        return None

    async def build_proposed_payload(self, hass, tool_input):
        return {"name": tool_input.tool_args["name"]}

    async def validate(self, hass, proposed, pre_state):
        if not proposed or not proposed.get("name"):
            return ValidationResult.failure([
                ValidationError(code="missing_name", message="Label name is required")
            ])
        # Check for duplicate name
        labels = await ha_registry.list_labels(hass)
        for label in labels:
            if label["name"].lower() == proposed["name"].lower():
                return ValidationResult.failure([
                    ValidationError(
                        code="duplicate_label",
                        message=f"Label '{proposed['name']}' already exists",
                        path="name"
                    )
                ])
        return ValidationResult.success()

    def build_proposed_summary(self, proposed, pre_state):
        name = (proposed or {}).get("name", "new label")
        return render_spoken_summary("Would add", f"label {name!r}")

    def build_proposed_diff(self, proposed, pre_state):
        return render_unified_diff(None, proposed)

    async def build_restore_fn(self, hass, proposed, pre_state):
        # Pattern: shared dict to capture label_id at apply-time
        apply_result: dict[str, Any] = {}

        async def _restore() -> None:
            label_id = apply_result.get("label_id")
            if label_id:
                try:
                    await ha_registry.delete_label(hass, label_id)
                except Exception as err:
                    _LOGGER.warning("undo of label create failed: %s", err)

        self._apply_result = apply_result  # type: ignore[attr-defined]
        return _restore

    async def apply_change(self, hass, proposed, pre_state):
        name = (proposed or {}).get("name", "")
        label_id = await ha_registry.create_label(hass, name)
        self._apply_result["label_id"] = label_id  # type: ignore[attr-defined]
        return {"status": "applied", "label_id": label_id, "name": name}


class ConfigLabelRename(ConfigEditingTool):
    """Rename an existing label. Inverse = rename back."""

    name = "ConfigLabelRename"
    description = (
        "Rename an existing Home Assistant label. "
        "Returns a pending_approval proposal; the user must confirm."
    )
    parameters = vol.Schema({
        vol.Required("label_id"): cv.string,
        vol.Required("new_name"): cv.string,
    })

    async def build_pre_state(self, hass, tool_input):
        label_id = tool_input.tool_args["label_id"]
        labels = await ha_registry.list_labels(hass)
        for label in labels:
            if label["label_id"] == label_id:
                return label
        return None

    async def build_proposed_payload(self, hass, tool_input):
        return {
            "label_id": tool_input.tool_args["label_id"],
            "name": tool_input.tool_args["new_name"],
        }

    async def validate(self, hass, proposed, pre_state):
        if pre_state is None:
            return ValidationResult.failure([
                ValidationError(
                    code="unknown_label",
                    message="Label not found",
                    path="label_id"
                )
            ])
        new_name = (proposed or {}).get("name", "")
        if not new_name:
            return ValidationResult.failure([
                ValidationError(code="missing_name", message="New name is required")
            ])
        # Check for duplicate name (excluding current label)
        labels = await ha_registry.list_labels(hass)
        label_id = (proposed or {}).get("label_id")
        for label in labels:
            if label["label_id"] != label_id and label["name"].lower() == new_name.lower():
                return ValidationResult.failure([
                    ValidationError(
                        code="duplicate_label",
                        message=f"Label '{new_name}' already exists",
                        path="new_name"
                    )
                ])
        return ValidationResult.success()

    def build_proposed_summary(self, proposed, pre_state):
        old_name = (pre_state or {}).get("name", "label")
        new_name = (proposed or {}).get("name", "new name")
        return render_spoken_summary(
            "Would rename",
            f"label {old_name!r} to {new_name!r}"
        )

    def build_proposed_diff(self, proposed, pre_state):
        return render_unified_diff(pre_state, proposed)

    async def build_restore_fn(self, hass, proposed, pre_state):
        label_id = (proposed or {}).get("label_id")
        old_name = (pre_state or {}).get("name")

        async def _restore() -> None:
            if label_id and old_name:
                try:
                    await ha_registry.update_label(hass, label_id, name=old_name)
                except Exception as err:
                    _LOGGER.warning("undo of label rename failed: %s", err)

        return _restore

    async def apply_change(self, hass, proposed, pre_state):
        label_id = (proposed or {}).get("label_id")
        new_name = (proposed or {}).get("name")
        await ha_registry.update_label(hass, label_id, name=new_name)
        return {"status": "applied", "label_id": label_id, "name": new_name}


class ConfigLabelDelete(ConfigEditingTool):
    """Delete a label. Inverse = re-create with a new label_id (emits warning)."""

    name = "ConfigLabelDelete"
    description = (
        "Delete an existing Home Assistant label. "
        "Returns a pending_approval proposal; the user must confirm."
    )
    parameters = vol.Schema({
        vol.Required("label_id"): cv.string,
    })

    async def build_pre_state(self, hass, tool_input):
        label_id = tool_input.tool_args["label_id"]
        labels = await ha_registry.list_labels(hass)
        for label in labels:
            if label["label_id"] == label_id:
                return label
        return None

    async def build_proposed_payload(self, hass, tool_input):
        return None

    async def validate(self, hass, proposed, pre_state):
        if pre_state is None:
            return ValidationResult.failure([
                ValidationError(
                    code="unknown_label",
                    message="Label not found",
                    path="label_id"
                )
            ])
        return ValidationResult.success()

    def build_proposed_summary(self, proposed, pre_state):
        name = (pre_state or {}).get("name", "label")
        return render_spoken_summary(
            "Would delete",
            f"label {name!r} — NOTE: undoing this cannot automatically re-link references"
        )

    def build_proposed_diff(self, proposed, pre_state):
        return render_unified_diff(pre_state, None)

    async def build_restore_fn(self, hass, proposed, pre_state):
        label_name = (pre_state or {}).get("name")

        async def _restore() -> None:
            if label_name:
                try:
                    await ha_registry.create_label(hass, label_name)
                except Exception as err:
                    _LOGGER.warning("undo of label delete failed: %s", err)

        return _restore

    async def apply_change(self, hass, proposed, pre_state):
        label_id = (pre_state or {}).get("label_id")
        await ha_registry.delete_label(hass, label_id)
        return {"status": "applied", "label_id": label_id}

    def tool_warnings(self, proposed, pre_state):
        return [
            "Undoing a label delete will re-create the label but any entity/device "
            "references will need to be re-linked manually."
        ]


# --- Entity Registry Tools ---


class ConfigEntityRename(ConfigEditingTool):
    """Rename an entity's display name. Inverse = rename back."""

    name = "ConfigEntityRename"
    description = (
        "Rename an entity's display name in the Home Assistant entity registry. "
        "Returns a pending_approval proposal; the user must confirm."
    )
    parameters = vol.Schema({
        vol.Required("entity_id"): cv.string,
        vol.Required("new_name"): cv.string,
    })

    async def build_pre_state(self, hass, tool_input):
        entity_id = tool_input.tool_args["entity_id"]
        entry = await ha_registry.get_entity_registry_entry(hass, entity_id)
        return entry

    async def build_proposed_payload(self, hass, tool_input):
        return {
            "entity_id": tool_input.tool_args["entity_id"],
            "name": tool_input.tool_args["new_name"],
        }

    async def validate(self, hass, proposed, pre_state):
        if pre_state is None:
            return ValidationResult.failure([
                ValidationError(
                    code="unknown_entity",
                    message="Entity not found in registry",
                    path="entity_id"
                )
            ])
        new_name = (proposed or {}).get("name", "")
        if not new_name:
            return ValidationResult.failure([
                ValidationError(code="missing_name", message="New name is required")
            ])
        return ValidationResult.success()

    def build_proposed_summary(self, proposed, pre_state):
        entity_id = (proposed or {}).get("entity_id", "entity")
        old_name = (pre_state or {}).get("name") or (pre_state or {}).get("original_name", "entity")
        new_name = (proposed or {}).get("name", "new name")
        return render_spoken_summary(
            "Would rename",
            f"entity {entity_id!r} from {old_name!r} to {new_name!r}"
        )

    def build_proposed_diff(self, proposed, pre_state):
        return render_unified_diff(pre_state, proposed)

    async def build_restore_fn(self, hass, proposed, pre_state):
        entity_id = (proposed or {}).get("entity_id")
        old_name = (pre_state or {}).get("name")

        async def _restore() -> None:
            if entity_id:
                try:
                    await ha_registry.update_entity_registry(hass, entity_id, name=old_name)
                except Exception as err:
                    _LOGGER.warning("undo of entity rename failed: %s", err)

        return _restore

    async def apply_change(self, hass, proposed, pre_state):
        entity_id = (proposed or {}).get("entity_id")
        new_name = (proposed or {}).get("name")
        await ha_registry.update_entity_registry(hass, entity_id, name=new_name)
        return {"status": "applied", "entity_id": entity_id, "name": new_name}


class ConfigEntityAssignArea(ConfigEditingTool):
    """Assign an entity to an area. Inverse = restore old area_id."""

    name = "ConfigEntityAssignArea"
    description = (
        "Assign an entity to a Home Assistant area (or unassign by setting area_id to None). "
        "Returns a pending_approval proposal; the user must confirm."
    )
    parameters = vol.Schema({
        vol.Required("entity_id"): cv.string,
        vol.Optional("area_id"): vol.Any(cv.string, None),
    })

    async def build_pre_state(self, hass, tool_input):
        entity_id = tool_input.tool_args["entity_id"]
        entry = await ha_registry.get_entity_registry_entry(hass, entity_id)
        return entry

    async def build_proposed_payload(self, hass, tool_input):
        return {
            "entity_id": tool_input.tool_args["entity_id"],
            "area_id": tool_input.tool_args.get("area_id"),
        }

    async def validate(self, hass, proposed, pre_state):
        if pre_state is None:
            return ValidationResult.failure([
                ValidationError(
                    code="unknown_entity",
                    message="Entity not found in registry",
                    path="entity_id"
                )
            ])
        # Validate area_id exists if provided
        area_id = (proposed or {}).get("area_id")
        if area_id is not None:
            areas = await ha_registry.list_areas(hass)
            if not any(a["area_id"] == area_id for a in areas):
                return ValidationResult.failure([
                    ValidationError(
                        code="unknown_area",
                        message="Area not found",
                        path="area_id"
                    )
                ])
        return ValidationResult.success()

    def build_proposed_summary(self, proposed, pre_state):
        entity_id = (proposed or {}).get("entity_id", "entity")
        area_id = (proposed or {}).get("area_id")
        if area_id:
            return render_spoken_summary(
                "Would assign",
                f"entity {entity_id!r} to area {area_id!r}"
            )
        else:
            return render_spoken_summary(
                "Would unassign",
                f"entity {entity_id!r} from its area"
            )

    def build_proposed_diff(self, proposed, pre_state):
        return render_unified_diff(pre_state, proposed)

    async def build_restore_fn(self, hass, proposed, pre_state):
        entity_id = (proposed or {}).get("entity_id")
        old_area_id = (pre_state or {}).get("area_id")

        async def _restore() -> None:
            if entity_id is not None:
                try:
                    await ha_registry.update_entity_registry(hass, entity_id, area_id=old_area_id)
                except Exception as err:
                    _LOGGER.warning("undo of entity area assignment failed: %s", err)

        return _restore

    async def apply_change(self, hass, proposed, pre_state):
        entity_id = (proposed or {}).get("entity_id")
        area_id = (proposed or {}).get("area_id")
        await ha_registry.update_entity_registry(hass, entity_id, area_id=area_id)
        return {"status": "applied", "entity_id": entity_id, "area_id": area_id}


def get_tools(hass: "HomeAssistant", entry: "ConfigEntry") -> list:
    """Factory called by register_config_tools when the kill switch is on."""
    return [
        ConfigAreaCreate(),
        ConfigAreaRename(),
        ConfigAreaDelete(),
        ConfigLabelCreate(),
        ConfigLabelRename(),
        ConfigLabelDelete(),
        ConfigEntityRename(),
        ConfigEntityAssignArea(),
    ]
