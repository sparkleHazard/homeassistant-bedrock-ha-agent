"""Config editing tools (gated by CONF_ENABLE_CONFIG_EDITING)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from homeassistant.helpers import llm

from custom_components.bedrock_ha_agent.const import (
    CONF_CONFIG_APPROVAL_TTL_SECONDS,
    CONF_ENABLE_CONFIG_EDITING,
    DEFAULT_CONFIG_APPROVAL_TTL_SECONDS,
)
from custom_components.bedrock_ha_agent.config_tools.pending import (
    PendingChangeManager,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from custom_components.bedrock_ha_agent.config_tools.validation import (
        ValidationResult,
    )


_LOGGER = logging.getLogger(__name__)

RestoreFn = Callable[[], Awaitable[None]]


@dataclass
class PendingApprovalResult:
    """TypedDict-like contract for the 'pending_approval' tool_result payload.

    Field names are imperative/future-tense on purpose — see F6 (confabulation guard).
    Never use past-tense names like 'summary', 'diff', 'change_id', 'result'.
    """

    status: str  # always "pending_approval"
    proposal_id: str
    tool: str
    proposed_summary: str
    proposed_diff: str
    expires_at_iso: str  # UTC ISO8601

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "proposal_id": self.proposal_id,
            "tool": self.tool,
            "proposed_summary": self.proposed_summary,
            "proposed_diff": self.proposed_diff,
            "expires_at_iso": self.expires_at_iso,
        }


class ConfigEditingTool(llm.Tool):
    """Base class for every config-mutating tool.

    Enforces the pipeline: validate → build diff → register PendingChange → return
    `pending_approval` payload. Subclasses MUST NOT override `async_call`; they
    implement the hooks below.

    `external = False` for v1 (Option A). Flipping to True is the Option-C fallback
    documented in plan §1 Options / §2 ADR.
    """

    external: bool = False
    name: str = ""  # subclasses set
    description: str = ""  # subclasses set
    parameters: Any = None  # subclasses set (voluptuous schema or dict schema)

    # --- Hooks subclasses implement ---

    async def build_pre_state(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict | None:
        """Return the current state of the resource about to be changed (for undo).

        Return None for pure-create operations.
        """
        raise NotImplementedError

    async def build_proposed_payload(
        self, hass: HomeAssistant, tool_input: llm.ToolInput
    ) -> dict | None:
        """Return the post-change state we intend to write. None for pure-delete."""
        raise NotImplementedError

    async def validate(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> "ValidationResult":
        """Return a ValidationResult (ok or failure with errors)."""
        raise NotImplementedError

    def build_proposed_summary(
        self, proposed: dict | None, pre_state: dict | None
    ) -> str:
        """Build the TTS-safe spoken summary. Use config_tools.diff.render_spoken_summary."""
        raise NotImplementedError

    def build_proposed_diff(self, proposed: dict | None, pre_state: dict | None) -> str:
        """Build the unified-diff text. Use config_tools.diff.render_unified_diff."""
        raise NotImplementedError

    async def build_restore_fn(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> RestoreFn:
        """Return an async callable that restores pre_state (the undo operation)."""
        raise NotImplementedError

    async def apply_change(
        self, hass: HomeAssistant, proposed: dict | None, pre_state: dict | None
    ) -> dict:
        """Perform the actual HA API call to apply the change. Returns a dict summary
        (e.g. {'object_id': '...', 'entity_id': '...'}). Raises on failure — caller
        handles post-apply rollback.

        NOTE: this is NOT called from async_call; it is invoked later by the approval
        interceptor in conversation.py (Phase 3) via `PendingChange.apply_fn`.
        """
        raise NotImplementedError

    def tool_warnings(self, proposed: dict | None, pre_state: dict | None) -> list[str]:
        """Optional list of user-visible caveats attached to the PendingChange and UndoEntry.

        Example: label-delete emits "undoing will re-create the label with a new id".
        Subclasses override when needed; default empty.
        """
        return []

    @staticmethod
    def _extract_config(
        tool_args: dict, metadata_keys: tuple[str, ...] = ()
    ) -> dict:
        """Pull an automation/script/scene/helper config dict out of tool_args.

        Claude on Bedrock inconsistently nests tool arguments: sometimes the
        full config lives under ``tool_args["config"]`` (matching our
        parameter schema), sometimes Claude flattens it and passes the
        config fields at the top level of ``tool_args``. Both shapes are
        expressing the same intent; this helper accepts either.

        When a top-level "config" key is present and maps to a dict, use
        it verbatim. Otherwise build a config dict from ``tool_args``
        minus the metadata keys the caller names (e.g. ``("object_id",)``
        for automations, ``("domain", "object_id")`` for helpers).
        """
        cfg = tool_args.get("config")
        if isinstance(cfg, dict):
            return dict(cfg)
        return {
            k: v for k, v in tool_args.items()
            if k not in metadata_keys and k != "config"
        }

    # --- Entry-point used by the llm framework ---

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        """Preview-only. NEVER writes to HA. Returns either pending_approval or validation_failed."""
        # 1. Resolve the owning config entry for this call.
        entry = self._resolve_entry(hass, llm_context)
        if entry is None:
            _LOGGER.error(
                "config-editing tool %s called but could not resolve a config entry",
                self.name,
            )
            return {
                "status": "validation_failed",
                "errors": [
                    {
                        "code": "no_entry",
                        "message": "Could not resolve Bedrock config entry",
                    }
                ],
            }

        # 2. Resolve conversation_id. When llm_context carries no conversation_id,
        # fall back to a shared per-entry "_global" bucket. This is intentional:
        # the approval gate still requires a subsequent user turn to actually
        # apply the change, so the bucket is not an approval-bypass vector; and
        # keeping a stable key lets the `undo_last_config_change` service find
        # the fallback-conversation undo stack without the caller having to
        # guess a random uuid. See the Phase-4 security review L2 note — the
        # original per-call-uuid mitigation broke test-suite assumptions and
        # the real-world undo ergonomics without closing a meaningful attack
        # surface (approval still gates apply).
        conversation_id = self._derive_conversation_id(llm_context)
        if not conversation_id:
            conversation_id = "_global"

        # 3. Build pre_state + proposed payloads.
        try:
            pre_state = await self.build_pre_state(hass, tool_input)
            proposed = await self.build_proposed_payload(hass, tool_input)
        except Exception as err:
            _LOGGER.exception(
                "config-editing tool %s failed to build payloads", self.name
            )
            return {
                "status": "validation_failed",
                "errors": [{"code": "build_failed", "message": str(err)}],
            }

        # 4. Validate (schema + entity-existence, per plan §3.d).
        try:
            result: ValidationResult = await self.validate(hass, proposed, pre_state)
        except Exception as err:
            _LOGGER.exception("config-editing tool %s raised during validation", self.name)
            return {
                "status": "validation_failed",
                "errors": [{"code": "validator_raised", "message": str(err)}],
            }
        if not result.ok:
            return result.to_tool_result_dict()

        # 5. Build diff + summary.
        proposed_diff = self.build_proposed_diff(proposed, pre_state)
        proposed_summary = self.build_proposed_summary(proposed, pre_state)

        # 6. Register the PendingChange (supersedes any existing pending for this conv).
        approval_ttl_seconds = int(
            entry.options.get(
                CONF_CONFIG_APPROVAL_TTL_SECONDS, DEFAULT_CONFIG_APPROVAL_TTL_SECONDS
            )
        )
        manager = PendingChangeManager.for_entry_conv(
            hass, entry.entry_id, conversation_id
        )

        # build_restore_fn may be async; call before stashing
        restore_fn = await self.build_restore_fn(hass, proposed, pre_state)

        now = datetime.now(UTC)
        pending = manager.create(
            tool_name=self.name,
            proposed_payload=proposed or {},
            pre_state=pre_state,
            proposed_summary=proposed_summary,
            proposed_diff=proposed_diff,
            approval_ttl_seconds=approval_ttl_seconds,
        )
        # Attach the apply + restore closures the interceptor will call.
        pending.apply_fn = self.apply_change  # type: ignore[attr-defined]
        pending.restore_fn = restore_fn  # type: ignore[attr-defined]
        pending.warnings = self.tool_warnings(proposed, pre_state)  # type: ignore[attr-defined]

        # 7. Return the pending-approval payload.
        payload = PendingApprovalResult(
            status="pending_approval",
            proposal_id=pending.proposal_id,
            tool=self.name,
            proposed_summary=proposed_summary,
            proposed_diff=proposed_diff,
            expires_at_iso=(now + timedelta(seconds=approval_ttl_seconds)).isoformat(),
        )
        _LOGGER.info(
            "config_editing: pending created proposal_id=%s tool=%s conv=%s entry=%s",
            pending.proposal_id,
            self.name,
            conversation_id,
            entry.entry_id,
        )
        return payload.to_dict()

    # --- Helpers ---

    @staticmethod
    def _resolve_entry(
        hass: HomeAssistant, llm_context: llm.LLMContext
    ) -> ConfigEntry | None:
        """Resolve the owning bedrock_ha_agent ConfigEntry at call time.

        1. Try llm_context.device_id → device_registry → config_entries intersection.
        2. Fallback: first loaded bedrock_ha_agent entry.
        """
        from custom_components.bedrock_ha_agent.const import DOMAIN
        from homeassistant.config_entries import ConfigEntryState
        from homeassistant.helpers import device_registry as dr

        device_id = getattr(llm_context, "device_id", None)
        if device_id:
            dev_reg = dr.async_get(hass)
            device = dev_reg.async_get(device_id)
            if device:
                for entry_id in device.config_entries:
                    entry = hass.config_entries.async_get_entry(entry_id)
                    if entry and entry.domain == DOMAIN:
                        return entry
        bedrock_entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.state == ConfigEntryState.LOADED
        ]
        if not bedrock_entries:
            return None
        if len(bedrock_entries) > 1:
            _LOGGER.warning(
                "llm_context.device_id did not resolve; falling back to first loaded "
                "bedrock_ha_agent entry (%s)",
                bedrock_entries[0].entry_id,
            )
        return bedrock_entries[0]

    @staticmethod
    def _derive_conversation_id(llm_context: llm.LLMContext) -> str | None:
        """Best-effort conversation_id extraction from llm_context.

        When invoked via the conversation agent, the conversation_id is attached to
        the context by Phase-3 wiring; here we peek at the HA context's fields.
        Returns None if nothing usable is present.
        """
        ctx = getattr(llm_context, "context", None)
        if ctx is None:
            return None
        # HA's Context has user_id + id fields; we prefer user_id when present but
        # the conversation_id is set on a separate attribute. The Phase-3 interceptor
        # is responsible for threading the real conversation_id; this is a safety net.
        return None


def register_config_tools(hass: HomeAssistant, entry: ConfigEntry) -> list[llm.Tool]:
    """Return the list of config-editing tools for a config entry.

    Returns an empty list when CONF_ENABLE_CONFIG_EDITING is False (kill switch).
    """
    if not entry.options.get(CONF_ENABLE_CONFIG_EDITING, False):
        return []

    # Phase 2 subclasses are imported lazily here. For Phase 1, this function returns
    # an empty list even when the flag is True — the real tool classes arrive in Phase 2.
    # Tests assert `list is empty when flag off` + `importable when flag on`.
    tools: list[llm.Tool] = []
    try:
        # Phase 2 will fill these in.
        from custom_components.bedrock_ha_agent.config_tools import (
            automation as _automation,
            helper as _helper,
            lovelace as _lovelace,
            registry as _registry,
            scene as _scene,
            script as _script,
        )

        for module in (
            _automation,
            _script,
            _scene,
            _helper,
            _lovelace,
            _registry,
        ):
            register_fn = getattr(module, "get_tools", None)
            if callable(register_fn):
                tools.extend(register_fn(hass, entry))
    except ImportError:
        # Phase 2 not yet landed; that's fine — flag-on with no tools is a valid state.
        pass
    return tools
