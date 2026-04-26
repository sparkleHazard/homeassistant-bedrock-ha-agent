"""Base classes and shared helpers for diagnostics tools."""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from ..const import (
    CONF_DIAGNOSTICS_CALL_BUDGET_PER_TURN,
    DEFAULT_DIAGNOSTICS_CALL_BUDGET_PER_TURN,
    DIAGNOSTICS_REDACT_KEYS,
    DIAGNOSTICS_RESPONSE_BYTE_CAP,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# S2: Value-pattern regex redaction
_VALUE_PATTERNS = [
    re.compile(r"eyJ[A-Za-z0-9_\-\.]{20,}"),               # JWT
    re.compile(r"AKIA[A-Z0-9]{16}"),                      # AWS access key
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.=]+"),       # Bearer token
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                   # OpenAI / generic sk-
]


class DiagnosticsReadTool(llm.Tool):
    """Base class for read-only diagnostic tools.

    Subclasses override:
    - name: str  (class attribute; must be in DIAGNOSTICS_TOOL_NAMES)
    - description: str
    - parameters: vol.Schema
    - async def _fetch(self, hass, **kwargs) -> Any  (raw data from HA)

    The base handles: per-turn budget enforcement, redaction, size capping,
    and structured-error reporting.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> Mapping[str, Any]:
        # 1. budget check
        budget_err = check_and_consume_budget(
            self.hass, self.entry, llm_context,
        )
        if budget_err:
            return budget_err

        # 2. fetch
        try:
            raw = await self._fetch(hass, **dict(tool_input.tool_args))
        except vol.Invalid as err:
            return {"status": "validation_failed", "errors": [{"code": "bad_args", "message": str(err)}]}
        except Exception as err:  # noqa: BLE001 — tool boundary
            _LOGGER.exception("diagnostics tool %s failed", self.name)
            return {"status": "error", "error": str(err)[:200]}

        # 3. redact + cap
        redacted = redact_secrets(raw)
        payload, truncated = enforce_byte_cap(redacted, DIAGNOSTICS_RESPONSE_BYTE_CAP)
        if truncated:
            payload["truncated"] = True
        payload["status"] = "ok"
        return payload

    async def _fetch(self, hass: HomeAssistant, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError


def _conv_id_from_context(llm_context: llm.LLMContext) -> str:
    """Derive a stable per-turn key from LLMContext.

    LLMContext has no `conversation_id` attribute on real HA (2025.6+); it
    exposes `context: homeassistant.core.Context` whose `.id` is a per-turn
    ULID. Tests may attach `conversation_id` directly to a MagicMock — honor
    that first. Fall back to `_global` if neither is usable.
    """
    ctx_conv_id = getattr(llm_context, "conversation_id", None)
    if isinstance(ctx_conv_id, str) and ctx_conv_id:
        return ctx_conv_id
    ha_context = getattr(llm_context, "context", None)
    ha_ctx_id = getattr(ha_context, "id", None)
    if isinstance(ha_ctx_id, str) and ha_ctx_id:
        return ha_ctx_id
    return "_global"


def check_and_consume_budget(
    hass: HomeAssistant,
    entry: ConfigEntry,
    llm_context: llm.LLMContext,
) -> Mapping[str, Any] | None:
    """Return an error payload if this turn has exceeded the diagnostic call budget; else None (and increment)."""
    from ..runtime_data import _get_runtime_data
    rd = _get_runtime_data(hass, entry.entry_id)
    conv_id = _conv_id_from_context(llm_context)
    # Bedrock doesn't expose a stable turn_id in llm_context; key on (conv_id, context id object id)
    # For v1 we key on conv_id alone and rely on the conversation-loop resetting counters at turn start.
    key = (conv_id, "current")
    budget = entry.options.get(CONF_DIAGNOSTICS_CALL_BUDGET_PER_TURN, DEFAULT_DIAGNOSTICS_CALL_BUDGET_PER_TURN)
    used = rd.diagnostics_turn_counts.get(key, 0)
    if used >= budget:
        return {
            "status": "budget_exceeded",
            "reason": "diagnostic tool budget per turn reached",
            "budget": budget,
        }
    rd.diagnostics_turn_counts[key] = used + 1
    return None


def reset_turn_budget(
    hass: HomeAssistant, entry: ConfigEntry, conversation_id: str | None = None  # noqa: ARG001
) -> None:
    """Reset the diagnostics tool-call counter at the start of each async_process turn.

    Called once per user utterance. Clears all counters for this entry — we
    can't align exactly on `llm_context.context.id` here (we don't have it
    yet at async_process entry), so we clear everything. Since there's one
    user talking to one integration at a time for a given entry, this is
    safe: even if there are multiple parallel conversations, each new
    async_process call resets the budget for the whole entry.

    conversation_id is accepted for historical API symmetry but not used.
    """
    from ..runtime_data import _get_runtime_data
    rd = _get_runtime_data(hass, entry.entry_id)
    rd.diagnostics_turn_counts.clear()


def _redact_value_string(s: str) -> str:
    """S2: Redact value patterns (JWT, AWS keys, Bearer tokens)."""
    out = s
    for pat in _VALUE_PATTERNS:
        out = pat.sub("***REDACTED***", out)
    return out


def redact_secrets(obj: Any) -> Any:
    """Recursively redact known secret keys. Applies to dicts, lists, tuples.

    S2: Uses substring matching on keys + value-pattern regex on strings.
    """
    if isinstance(obj, Mapping):
        return {
            k: (
                "***REDACTED***"
                if isinstance(k, str) and any(rk in k.lower() for rk in DIAGNOSTICS_REDACT_KEYS)
                else redact_secrets(v)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [redact_secrets(x) for x in obj]
    if isinstance(obj, str):
        return _redact_value_string(obj)
    return obj


def enforce_byte_cap(payload: dict[str, Any], cap: int) -> tuple[dict[str, Any], bool]:
    """If json.dumps(payload) > cap bytes, truncate list fields until under cap.

    Returns (possibly-truncated-payload, truncated_flag). When truncated, metadata
    fields (rows_returned, rows_available_estimate, truncation_reason) are added.
    The metadata budget is reserved upfront so the final payload honors `cap`.
    """
    encoded = json.dumps(payload, default=str)
    if len(encoded.encode("utf-8")) <= cap:
        return payload, False

    list_fields = [(k, v) for k, v in payload.items() if isinstance(v, list) and len(v) > 1]
    if not list_fields:
        # Nothing to shrink — return payload with a truncation marker only.
        marker = {**payload, "truncation_reason": "response_byte_cap"}
        return marker, True

    list_fields.sort(key=lambda kv: len(json.dumps(kv[1], default=str)), reverse=True)

    # Seed the final-shape payload with zero-count metadata so binary search
    # accounts for its bytes. rows_returned is updated after search.
    biggest_key, biggest_val = list_fields[0]
    orig_count = len(biggest_val)
    truncated: dict[str, Any] = {
        **payload,
        biggest_key: [],
        "rows_returned": 0,
        "rows_available_estimate": orig_count,
        "truncation_reason": "response_byte_cap",
    }

    # Binary-search the largest prefix of biggest_val that fits (along with
    # the metadata fields already present).
    lo, hi = 0, orig_count
    while lo < hi:
        mid = (lo + hi + 1) // 2
        trial = {**truncated, biggest_key: biggest_val[:mid], "rows_returned": mid}
        size = len(json.dumps(trial, default=str).encode("utf-8"))
        if size <= cap:
            lo = mid
        else:
            hi = mid - 1

    truncated[biggest_key] = biggest_val[:lo]
    truncated["rows_returned"] = lo

    # Any OTHER list fields are dropped to empty — keep the cap honest.
    for key, _val in list_fields[1:]:
        truncated[key] = []

    return truncated, True
