"""Lovelace dashboard and card editing tools."""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.helpers import config_validation as cv, llm

from custom_components.bedrock_ha_agent.config_tools import ConfigEditingTool, RestoreFn
from custom_components.bedrock_ha_agent.config_tools.diff import (
    render_spoken_summary,
    render_unified_diff,
)
from custom_components.bedrock_ha_agent.config_tools.validation import (
    ValidationError,
    ValidationResult,
    validate_lovelace_card,
)
from custom_components.bedrock_ha_agent.config_tools.ha_client import lovelace

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class ConfigLovelaceCardAdd(ConfigEditingTool):
    """Add a card to a specific view on an existing Lovelace dashboard."""

    name = "ConfigLovelaceCardAdd"
    description = "Add a card to a specific view on a Lovelace dashboard"
    parameters = vol.Schema(
        {
            vol.Optional("url_path"): vol.Any(None, cv.string),
            vol.Required("view_path"): cv.string,
            vol.Required("card"): dict[str, Any],
        }
    )

    async def build_pre_state(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict[str, Any] | None:
        """Load the full dashboard config before the change."""
        url_path = tool_input.tool_args.get("url_path")
        dashboard_config = await lovelace.load_dashboard(hass, url_path)
        return dashboard_config

    async def build_proposed_payload(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict[str, Any] | None:
        """Build the proposed dashboard config with the new card added."""
        url_path = tool_input.tool_args.get("url_path")
        view_path = tool_input.tool_args["view_path"]
        card = tool_input.tool_args["card"]

        # Load current dashboard
        dashboard_config = await lovelace.load_dashboard(hass, url_path)

        # Deep copy to avoid mutating the original
        proposed = copy.deepcopy(dashboard_config)

        # Find the target view
        views = proposed.get("views", [])
        target_view_idx = None
        for i, view in enumerate(views):
            # Match by path or title
            if view.get("path") == view_path or view.get("title") == view_path:
                target_view_idx = i
                break

        if target_view_idx is None:
            # Store error marker for validation
            proposed["_error"] = f"view_not_found:{view_path}"
            proposed["_url_path"] = url_path
            proposed["_view_path"] = view_path
            proposed["_card"] = card
            return proposed

        # Add the card to the view
        target_view = views[target_view_idx]
        if "cards" not in target_view:
            target_view["cards"] = []
        target_view["cards"].append(card)

        # Store metadata for apply/restore
        proposed["_url_path"] = url_path
        proposed["_view_path"] = view_path
        proposed["_card"] = card

        return proposed

    async def validate(
        self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None
    ) -> ValidationResult:
        """Validate the card addition."""
        if proposed is None:
            return ValidationResult.failure(
                [ValidationError(code="build_failed", message="Failed to build proposed state")]
            )

        # Check for view not found error
        if "_error" in proposed:
            error_msg = proposed["_error"]
            if error_msg.startswith("view_not_found:"):
                view_path = error_msg.split(":", 1)[1]
                return ValidationResult.failure(
                    [
                        ValidationError(
                            code="unknown_view",
                            message=f"View '{view_path}' not found in dashboard",
                        )
                    ]
                )

        # Extract url_path and check YAML mode (AC18)
        url_path = proposed.get("_url_path")
        mode = await lovelace.get_dashboard_mode(hass, url_path)
        if mode == "yaml":
            dashboard_label = url_path if url_path else "Overview"
            return ValidationResult.failure(
                [
                    ValidationError(
                        code="lovelace_yaml_mode",
                        message=f"Dashboard {dashboard_label} is managed via configuration.yaml; "
                        "I can't edit it. Ask a human to edit the file manually.",
                    )
                ]
            )

        # Validate the card structure
        card = proposed.get("_card")
        if card:
            card_result = validate_lovelace_card(card)
            if not card_result.ok:
                return card_result

        return ValidationResult.success()

    def build_proposed_summary(
        self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None
    ) -> str:
        """Build the spoken summary."""
        if proposed is None:
            return "Would add a card"

        # Extract card type and view info
        card = proposed.get("_card", {})
        card_type = card.get("type", "unknown")
        view_path = proposed.get("_view_path", "a view")
        url_path = proposed.get("_url_path")
        dashboard_label = url_path if url_path else "Overview"

        return render_spoken_summary(
            "Would add",
            f"a {card_type} card to {dashboard_label} / {view_path}",
        )

    def build_proposed_diff(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        """Build the unified diff."""
        # Remove metadata before diffing
        clean_proposed = None
        if proposed:
            clean_proposed = {k: v for k, v in proposed.items() if not k.startswith("_")}
        return render_unified_diff(pre_state, clean_proposed)

    async def build_restore_fn(
        self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None
    ) -> RestoreFn:
        """Build the undo function."""
        url_path = proposed.get("_url_path") if proposed else None
        pre_state_safe: dict[str, Any] = pre_state if pre_state is not None else {}

        async def restore() -> None:
            await lovelace.save_dashboard(hass, url_path, pre_state_safe)

        return restore

    async def apply_change(
        self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Apply the card addition."""
        assert proposed is not None, "apply_change called with no proposed payload"
        url_path = proposed.get("_url_path")
        # Remove metadata before saving
        clean_proposed = {k: v for k, v in proposed.items() if not k.startswith("_")}
        await lovelace.save_dashboard(hass, url_path, clean_proposed)
        return {"status": "success", "url_path": url_path}


class ConfigLovelaceCardRemove(ConfigEditingTool):
    """Remove a card from a Lovelace dashboard view."""

    name = "ConfigLovelaceCardRemove"
    description = "Remove a card from a Lovelace dashboard view"
    parameters = vol.Schema(
        {
            vol.Optional("url_path"): vol.Any(None, cv.string),
            vol.Required("view_path"): cv.string,
            vol.Required("card_index"): int,
        }
    )

    async def build_pre_state(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict[str, Any] | None:
        """Load the full dashboard config."""
        url_path = tool_input.tool_args.get("url_path")
        return await lovelace.load_dashboard(hass, url_path)

    async def build_proposed_payload(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict[str, Any] | None:
        """Build the dashboard config with the card removed."""
        url_path = tool_input.tool_args.get("url_path")
        view_path = tool_input.tool_args["view_path"]
        card_index = tool_input.tool_args["card_index"]

        dashboard_config = await lovelace.load_dashboard(hass, url_path)
        proposed = copy.deepcopy(dashboard_config)

        # Find the target view
        views = proposed.get("views", [])
        target_view = None
        for view in views:
            if view.get("path") == view_path or view.get("title") == view_path:
                target_view = view
                break

        if target_view is None:
            proposed["_error"] = f"view_not_found:{view_path}"
            proposed["_url_path"] = url_path
            return proposed

        # Check card index bounds
        cards = target_view.get("cards", [])
        if card_index < 0 or card_index >= len(cards):
            proposed["_error"] = f"card_index_out_of_range:{card_index}:{len(cards)}"
            proposed["_url_path"] = url_path
            return proposed

        # Remove the card
        cards.pop(card_index)

        # Store metadata
        proposed["_url_path"] = url_path
        proposed["_view_path"] = view_path
        proposed["_card_index"] = card_index

        return proposed

    async def validate(
        self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None
    ) -> ValidationResult:
        """Validate the card removal."""
        if proposed is None:
            return ValidationResult.failure(
                [ValidationError(code="build_failed", message="Failed to build proposed state")]
            )

        # Check for errors
        if "_error" in proposed:
            error_msg = proposed["_error"]
            if error_msg.startswith("view_not_found:"):
                view_path = error_msg.split(":", 1)[1]
                return ValidationResult.failure(
                    [
                        ValidationError(
                            code="unknown_view",
                            message=f"View '{view_path}' not found in dashboard",
                        )
                    ]
                )
            elif error_msg.startswith("card_index_out_of_range:"):
                parts = error_msg.split(":")
                card_index = parts[1]
                num_cards = parts[2]
                return ValidationResult.failure(
                    [
                        ValidationError(
                            code="card_index_out_of_range",
                            message=f"Card index {card_index} is out of range (view has {num_cards} cards)",
                        )
                    ]
                )

        # YAML-mode check
        url_path = proposed.get("_url_path")
        mode = await lovelace.get_dashboard_mode(hass, url_path)
        if mode == "yaml":
            dashboard_label = url_path if url_path else "Overview"
            return ValidationResult.failure(
                [
                    ValidationError(
                        code="lovelace_yaml_mode",
                        message=f"Dashboard {dashboard_label} is managed via configuration.yaml; "
                        "I can't edit it. Ask a human to edit the file manually.",
                    )
                ]
            )

        return ValidationResult.success()

    def build_proposed_summary(
        self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None
    ) -> str:
        """Build the spoken summary."""
        view_path = proposed.get("_view_path", "a view") if proposed else "a view"
        card_index = proposed.get("_card_index", 0) if proposed else 0
        return render_spoken_summary(
            "Would remove",
            f"card at index {card_index} from {view_path}",
        )

    def build_proposed_diff(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        """Build the unified diff."""
        clean_proposed = None
        if proposed:
            clean_proposed = {k: v for k, v in proposed.items() if not k.startswith("_")}
        return render_unified_diff(pre_state, clean_proposed)

    async def build_restore_fn(
        self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None
    ) -> RestoreFn:
        """Build the undo function."""
        url_path = proposed.get("_url_path") if proposed else None
        pre_state_safe: dict[str, Any] = pre_state if pre_state is not None else {}

        async def restore() -> None:
            await lovelace.save_dashboard(hass, url_path, pre_state_safe)

        return restore

    async def apply_change(
        self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Apply the card removal."""
        assert proposed is not None, "apply_change called with no proposed payload"
        url_path = proposed.get("_url_path")
        clean_proposed = {k: v for k, v in proposed.items() if not k.startswith("_")}
        await lovelace.save_dashboard(hass, url_path, clean_proposed)
        return {"status": "success", "url_path": url_path}


class ConfigLovelaceDashboardCreate(ConfigEditingTool):
    """Create a new Lovelace dashboard."""

    name = "ConfigLovelaceDashboardCreate"
    description = "Create a new Lovelace dashboard"
    parameters = vol.Schema(
        {
            vol.Required("url_path"): cv.string,
            vol.Required("title"): cv.string,
            vol.Optional("icon"): cv.string,
            vol.Optional("show_in_sidebar", default=True): bool,
            vol.Optional("require_admin", default=False): bool,
        }
    )

    async def build_pre_state(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict[str, Any] | None:
        """No pre-state for creation."""
        return None

    async def build_proposed_payload(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict[str, Any] | None:
        """Build the dashboard creation payload."""
        payload = {
            "url_path": tool_input.tool_args["url_path"],
            "title": tool_input.tool_args["title"],
            "show_in_sidebar": tool_input.tool_args.get("show_in_sidebar", True),
            "require_admin": tool_input.tool_args.get("require_admin", False),
        }
        icon = tool_input.tool_args.get("icon")
        if icon:
            payload["icon"] = icon
        return payload

    async def validate(
        self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None
    ) -> ValidationResult:
        """Validate the dashboard creation."""
        if proposed is None:
            return ValidationResult.failure(
                [ValidationError(code="build_failed", message="Failed to build proposed state")]
            )

        # Check if url_path already exists
        dashboards = await lovelace.list_dashboards(hass)
        url_path = proposed.get("url_path")
        for dash in dashboards:
            if dash.get("url_path") == url_path:
                return ValidationResult.failure(
                    [
                        ValidationError(
                            code="url_path_exists",
                            message=f"Dashboard with url_path '{url_path}' already exists",
                        )
                    ]
                )

        return ValidationResult.success()

    def build_proposed_summary(
        self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None
    ) -> str:
        """Build the spoken summary."""
        title = (proposed or {}).get("title", "a dashboard")
        return render_spoken_summary("Would create", f"the dashboard '{title}'")

    def build_proposed_diff(self, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None) -> str:
        """Build the unified diff."""
        return render_unified_diff(pre_state, proposed)

    async def build_restore_fn(
        self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None
    ) -> RestoreFn:
        """Build the undo function."""
        url_path = (proposed or {}).get("url_path")

        async def restore() -> None:
            if url_path:
                await lovelace.delete_dashboard(hass, url_path)

        return restore

    async def apply_change(
        self, hass: HomeAssistant, proposed: dict[str, Any] | None, pre_state: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Apply the dashboard creation."""
        assert proposed is not None, "apply_change called with no proposed payload"
        url_path = await lovelace.create_dashboard(hass, proposed)
        return {"url_path": url_path, "status": "success"}


def get_tools(hass: HomeAssistant, entry: ConfigEntry) -> list[llm.Tool]:
    """Return the list of Lovelace config-editing tools."""
    return [
        ConfigLovelaceCardAdd(),
        ConfigLovelaceCardRemove(),
        ConfigLovelaceDashboardCreate(),
    ]
