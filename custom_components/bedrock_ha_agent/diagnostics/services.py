"""ExtendedServiceCall — broader-allowlist service dispatch.

Services classified 'read_safe' execute immediately. Services classified 'mutating'
go through the existing PendingChange -> approve -> apply -> UndoStack pipeline.
Services not in DIAGNOSTICS_ALLOWED_SERVICES or in DIAGNOSTICS_DENIED_SERVICES are
refused at pre-validation.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from ..const import (
    CONF_CONFIG_APPROVAL_TTL_SECONDS,
    DEFAULT_CONFIG_APPROVAL_TTL_SECONDS,
    DIAGNOSTICS_ALLOWED_SERVICES,
    DIAGNOSTICS_DENIED_SERVICES,
)
from .base import check_and_consume_budget, redact_secrets

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class ExtendedServiceCall(llm.Tool):
    """Call a Home Assistant service from a broadened diagnostics allowlist.

    Read-safe services (persistent_notification.create, system_log.clear, etc.)
    execute immediately. State-mutating services (automation.trigger, script.turn_on, etc.)
    return a pending_approval proposal that the user must confirm before apply.
    """

    name = "ExtendedServiceCall"
    description = (
        "Call a Home Assistant service. Read-safe services execute immediately; "
        "mutating services return pending_approval requiring user confirmation."
    )
    parameters = vol.Schema(
        {
            vol.Required("service"): str,  # "domain.service" form
            vol.Optional("target", default=None): vol.Any(None, dict),
            vol.Optional("data", default=None): vol.Any(None, dict),
        }
    )

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the tool."""
        self.hass = hass
        self.entry = entry

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> Mapping[str, Any]:
        """Validate and dispatch service call (immediate or pending)."""
        # 0. budget
        budget_err = check_and_consume_budget(self.hass, self.entry, llm_context)
        if budget_err:
            return budget_err

        args = dict(tool_input.tool_args)
        service = args.get("service", "")
        if not isinstance(service, str) or "." not in service:
            return {
                "status": "validation_failed",
                "errors": [
                    {
                        "code": "bad_service_string",
                        "message": "service must be 'domain.service' form",
                    }
                ],
            }

        # 1. deny list backstop
        if service in DIAGNOSTICS_DENIED_SERVICES:
            return {
                "status": "validation_failed",
                "errors": [
                    {
                        "code": "service_denied",
                        "message": f"{service} is explicitly denied for diagnostics",
                    }
                ],
            }

        # 2. allowlist classification
        entry_data = DIAGNOSTICS_ALLOWED_SERVICES.get(service)
        if entry_data is None:
            return {
                "status": "validation_failed",
                "errors": [
                    {
                        "code": "service_not_allowed",
                        "message": f"{service} is not in the diagnostics allowlist",
                    }
                ],
            }

        classification = entry_data["class"]
        target = args.get("target") or {}
        data = args.get("data") or {}

        # 3. does the service exist?
        domain, svc = service.split(".", 1)
        if not hass.services.has_service(domain, svc):
            return {
                "status": "validation_failed",
                "errors": [
                    {
                        "code": "service_not_registered",
                        "message": f"{service} is in the allowlist but not registered with HA",
                    }
                ],
            }

        # 4. entity_id required-but-missing check (M6/AC D48).
        # We only know the service schema is "entity_id required" via the service registry's schema.
        # For v1, we hard-require entity_id for a known subset of services that would silently fail otherwise.
        ENTITY_ID_REQUIRED = {
            "automation.trigger",
            "automation.turn_on",
            "automation.turn_off",
            "automation.toggle",
            "script.turn_on",
            "script.turn_off",
            "scene.turn_on",
            "scene.apply",
            "input_boolean.toggle",
            "input_boolean.turn_on",
            "input_boolean.turn_off",
            "input_button.press",
            "timer.start",
            "timer.pause",
            "timer.cancel",
            "timer.finish",
            "counter.increment",
            "counter.decrement",
            "counter.reset",
            "homeassistant.update_entity",
        }
        if service in ENTITY_ID_REQUIRED:
            entity_ids = (
                target.get("entity_id")
                if isinstance(target, Mapping)
                else None
            )
            if not entity_ids:
                entity_ids = (
                    data.get("entity_id") if isinstance(data, Mapping) else None
                )
            if not entity_ids:
                return {
                    "status": "validation_failed",
                    "errors": [
                        {
                            "code": "entity_id_required",
                            "message": f"{service} requires entity_id in target or data",
                        }
                    ],
                }

        # 5. dispatch
        if classification == "read_safe":
            return await self._execute_immediate(service, target, data)
        if classification == "mutating":
            return await self._create_pending(service, target, data, llm_context)
        return {
            "status": "error",
            "error": f"unknown classification {classification!r} for {service}",
        }

    async def _execute_immediate(
        self,
        service: str,
        target: dict,
        data: dict,
    ) -> Mapping[str, Any]:
        """Execute a read_safe service immediately."""
        domain, svc = service.split(".", 1)
        try:
            redacted_called_with = redact_secrets(
                {"service": service, "target": target, "data": data}
            )
            resp = await self.hass.services.async_call(
                domain,
                svc,
                service_data=data,
                target=target or None,
                blocking=True,
                return_response=False,
            )
            return {
                "status": "ok",
                "service": service,
                "called_with": redacted_called_with,
                "service_response": redact_secrets(resp) if resp else None,
            }
        except Exception as err:  # noqa: BLE001
            return {
                "status": "error",
                "service": service,
                "error": str(err)[:200],
            }

    async def _create_pending(
        self,
        service: str,
        target: dict,
        data: dict,
        llm_context: llm.LLMContext,
    ) -> Mapping[str, Any]:
        """Create a PendingChange for a mutating service call."""
        from ..config_tools.pending import PendingChangeManager

        redacted_payload = redact_secrets(
            {"service": service, "target": target, "data": data}
        )
        conv_id = llm_context.conversation_id or "_global"
        proposed_summary = f"Would call {service}" + (
            f" with target={list(target.keys())}" if target else ""
        )
        proposed_diff = (
            f"service: {service}\ntarget: {target}\ndata: {list(data.keys())}"
        )

        # Build apply_fn that runs the service call when user approves.
        async def _apply_fn(
            hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
        ) -> dict:
            domain_inner, svc_inner = service.split(".", 1)
            await hass.services.async_call(
                domain_inner,
                svc_inner,
                service_data=data,
                target=target or None,
                blocking=True,
                return_response=False,
            )
            return {"applied": True, "service": service}

        # Build restore_fn (service calls have no generic undo)
        async def _restore_fn() -> None:
            _LOGGER.info(
                "ExtendedServiceCall apply has no native undo; leaving state as-is"
            )

        # Register PendingChange via manager
        approval_ttl_seconds = int(
            self.entry.options.get(
                CONF_CONFIG_APPROVAL_TTL_SECONDS, DEFAULT_CONFIG_APPROVAL_TTL_SECONDS
            )
        )
        manager = PendingChangeManager.for_entry_conv(
            self.hass, self.entry.entry_id, conv_id
        )

        pending = manager.create(
            tool_name=self.name,
            proposed_payload=redacted_payload,
            pre_state={"service": service},  # no pre-state we can read generically
            proposed_summary=proposed_summary,
            proposed_diff=proposed_diff,
            approval_ttl_seconds=approval_ttl_seconds,
        )

        # Attach closures the interceptor will call
        pending.apply_fn = _apply_fn  # type: ignore[attr-defined]
        pending.restore_fn = _restore_fn  # type: ignore[attr-defined]
        pending.warnings = []  # type: ignore[attr-defined]

        now = datetime.now(UTC)
        expires_at_iso = (now + timedelta(seconds=approval_ttl_seconds)).isoformat()

        _LOGGER.info(
            "ExtendedServiceCall: pending created proposal_id=%s service=%s conv=%s entry=%s",
            pending.proposal_id,
            service,
            conv_id,
            self.entry.entry_id,
        )

        return {
            "status": "pending_approval",
            "proposal_id": pending.proposal_id,
            "tool": self.name,
            "proposed_summary": proposed_summary,
            "proposed_diff": pending.proposed_diff,
            "expires_at_iso": expires_at_iso,
        }


def get_tools(hass: "HomeAssistant", entry: "ConfigEntry") -> list:
    """Return the diagnostic tools provided by this module."""
    return [ExtendedServiceCall(hass, entry)]
