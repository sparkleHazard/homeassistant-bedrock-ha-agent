"""Pre-validation (no side-effects) for proposed config changes.

Runs BEFORE the diff is shown to the user. Failures are returned as structured
`ValidationError`s; the tool then emits `{"status": "validation_failed", ...}`
to the model.

Spec §3.d — we explicitly do NOT call `check_config` (reload side-effects risk).
Schema validation + entity-existence lookup is the full gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@dataclass
class ValidationError:
    """Single validation failure."""

    code: str  # slug like "unknown_entity", "schema_invalid", "missing_field"
    message: str  # human-readable
    path: str | None = None  # dotted path into the payload, when applicable


@dataclass
class ValidationResult:
    """Aggregated validation outcome."""

    ok: bool
    errors: list[ValidationError] = field(default_factory=list)

    @classmethod
    def success(cls) -> ValidationResult:
        """Create a successful validation result."""
        return cls(ok=True)

    @classmethod
    def failure(cls, errors: list[ValidationError]) -> ValidationResult:
        """Create a failed validation result."""
        return cls(ok=False, errors=errors)

    def to_tool_result_dict(self) -> dict[str, object]:
        """Serialize into the tool_result shape the model sees."""
        return {
            "status": "validation_failed",
            "errors": [
                {
                    "code": e.code,
                    "message": e.message,
                    **({"path": e.path} if e.path else {}),
                }
                for e in self.errors
            ],
        }


# ---------------------------------------------------------------------------
# Public validators — one per surface. Each returns ValidationResult.
# ---------------------------------------------------------------------------


def validate_automation(payload: dict[str, object]) -> ValidationResult:
    """Schema-validate an automation payload using HA's own validator.

    Uses `homeassistant.components.automation.config.PLATFORM_SCHEMA`.
    """
    try:
        from homeassistant.components.automation.config import PLATFORM_SCHEMA
        import voluptuous as vol
    except ImportError as err:
        return ValidationResult.failure(
            [
                ValidationError(
                    code="import_error",
                    message=f"Failed to import automation schema: {err}",
                )
            ]
        )

    try:
        PLATFORM_SCHEMA(payload)
    except Exception as err:  # voluptuous.Invalid or other exceptions
        import voluptuous as vol

        if isinstance(err, vol.Invalid):
            return ValidationResult.failure(
                [
                    ValidationError(
                        code="schema_invalid",
                        message=str(err),
                        path=".".join(str(p) for p in err.path) if err.path else None,
                    )
                ]
            )
        return ValidationResult.failure(
            [ValidationError(code="schema_invalid", message=str(err))]
        )
    return ValidationResult.success()


def validate_script(payload: dict[str, object]) -> ValidationResult:
    """Schema-validate a script sequence payload."""
    try:
        from homeassistant.components.script.config import SCRIPT_ENTITY_SCHEMA
        import voluptuous as vol
    except ImportError as err:
        return ValidationResult.failure(
            [
                ValidationError(
                    code="import_error",
                    message=f"Failed to import script schema: {err}",
                )
            ]
        )

    try:
        SCRIPT_ENTITY_SCHEMA(payload)
    except Exception as err:
        import voluptuous as vol

        if isinstance(err, vol.Invalid):
            return ValidationResult.failure(
                [
                    ValidationError(
                        code="schema_invalid",
                        message=str(err),
                        path=".".join(str(p) for p in err.path) if err.path else None,
                    )
                ]
            )
        return ValidationResult.failure(
            [ValidationError(code="schema_invalid", message=str(err))]
        )
    return ValidationResult.success()


def validate_scene(payload: dict[str, object]) -> ValidationResult:
    """Schema-validate a scene payload.

    Scenes accept `name` + `entities: {entity_id: state_or_attributes}`.
    """
    if not isinstance(payload, dict):
        return ValidationResult.failure(
            [ValidationError(code="schema_invalid", message="Scene payload must be a dict")]
        )
    if "name" not in payload or not isinstance(payload.get("name"), str):
        return ValidationResult.failure(
            [
                ValidationError(
                    code="missing_field",
                    message="Scene requires a 'name' field",
                    path="name",
                )
            ]
        )
    entities = payload.get("entities")
    if not isinstance(entities, dict):
        return ValidationResult.failure(
            [
                ValidationError(
                    code="missing_field",
                    message="Scene requires an 'entities' dict mapping entity_id → state/attrs",
                    path="entities",
                )
            ]
        )
    return ValidationResult.success()


def validate_helper(helper_type: str, payload: dict[str, object]) -> ValidationResult:
    """Light structural check for helper create/update payloads.

    Supported helper_types: input_boolean, input_number, input_select, input_text,
    input_datetime, input_button, timer, counter.
    """
    supported = {
        "input_boolean",
        "input_number",
        "input_select",
        "input_text",
        "input_datetime",
        "input_button",
        "timer",
        "counter",
    }
    if helper_type not in supported:
        return ValidationResult.failure(
            [
                ValidationError(
                    code="unsupported_helper_type",
                    message=f"Helper type '{helper_type}' not supported (allowed: {sorted(supported)})",
                    path="helper_type",
                )
            ]
        )
    if not isinstance(payload, dict):
        return ValidationResult.failure(
            [ValidationError(code="schema_invalid", message="Payload must be a dict")]
        )
    if (
        "name" not in payload
        or not isinstance(payload.get("name"), str)
        or not str(payload["name"]).strip()
    ):
        return ValidationResult.failure(
            [
                ValidationError(
                    code="missing_field", message="'name' is required", path="name"
                )
            ]
        )
    # Type-specific light checks
    if helper_type == "input_number":
        for key in ("min", "max"):
            if key not in payload:
                return ValidationResult.failure(
                    [
                        ValidationError(
                            code="missing_field",
                            message=f"'{key}' is required for input_number",
                            path=key,
                        )
                    ]
                )
    if helper_type == "input_select":
        opts = payload.get("options")
        if not isinstance(opts, list) or not opts:
            return ValidationResult.failure(
                [
                    ValidationError(
                        code="missing_field",
                        message="'options' must be a non-empty list",
                        path="options",
                    )
                ]
            )
    return ValidationResult.success()


def validate_lovelace_card(card: dict[str, object]) -> ValidationResult:
    """Minimal Lovelace card schema check — ensures `type` is present and is a string.

    Lovelace cards are strategy-validated at render time; there's no general card schema.
    We do a structural minimum; the apply step re-reads the dashboard to verify the card
    was accepted.
    """
    if not isinstance(card, dict):
        return ValidationResult.failure(
            [ValidationError(code="schema_invalid", message="Card must be a dict")]
        )
    card_type = card.get("type")
    if not isinstance(card_type, str) or not card_type.strip():
        return ValidationResult.failure(
            [
                ValidationError(
                    code="missing_field", message="Card 'type' is required", path="type"
                )
            ]
        )
    return ValidationResult.success()


# ---------------------------------------------------------------------------
# Entity-existence helpers — require hass.
# ---------------------------------------------------------------------------


def validate_entity_exists(hass: HomeAssistant, entity_id: str) -> ValidationResult:
    """Confirm the entity exists in states OR the entity registry.

    States alone is insufficient (entities may be disabled / unavailable but still
    registered). We check the registry first, then states.
    """
    from homeassistant.helpers import entity_registry as er

    if not isinstance(entity_id, str) or "." not in entity_id:
        return ValidationResult.failure(
            [
                ValidationError(
                    code="invalid_entity_id",
                    message=f"Malformed entity_id: {entity_id!r}",
                )
            ]
        )
    registry = er.async_get(hass)
    if registry.async_get(entity_id) is not None:
        return ValidationResult.success()
    if hass.states.get(entity_id) is not None:
        return ValidationResult.success()
    return ValidationResult.failure(
        [
            ValidationError(
                code="unknown_entity",
                message=f"Entity {entity_id} does not exist",
            )
        ]
    )


def validate_entities_exist(hass: HomeAssistant, entity_ids: list[str]) -> ValidationResult:
    """Bulk entity existence. Returns all failures in one pass."""
    errors: list[ValidationError] = []
    for eid in entity_ids:
        r = validate_entity_exists(hass, eid)
        if not r.ok:
            errors.extend(r.errors)
    return ValidationResult.success() if not errors else ValidationResult.failure(errors)


def extract_entity_ids_from_automation(payload: dict[str, Any]) -> list[str]:
    """Walk an automation payload and return referenced entity_ids.

    Best-effort extraction from triggers, conditions, and actions. Does NOT resolve
    templates; template-referenced entities are skipped (validation will let them
    through and the apply step catches issues).
    """
    found: set[str] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("entity_id", "device_id", "target"):
                val = node.get(key)
                if isinstance(val, str) and "." in val:
                    found.add(val)
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, str) and "." in item:
                            found.add(item)
                elif isinstance(val, dict):
                    # e.g. target: {entity_id: [...]}
                    _walk(val)
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    # Filter out obviously-non-entity strings (device_id uuids, etc.)
    return sorted(e for e in found if "." in e and not e.startswith("device."))


def unknown_entry_error(
    hass: "HomeAssistant",
    domain: str,
    object_id: str,
) -> ValidationError:
    """Build a not-found-but-maybe-exists ValidationError for edit/delete paths.

    Called when the tool's own transport (automations.yaml / scripts/... /
    scenes/...) has no entry for ``object_id``. If HA's state registry DOES
    show the entity, the config is almost certainly sourced from somewhere
    this integration can't touch (a package, .storage, a different include).
    The returned error makes that distinction clear to the model so it can
    tell the user instead of treating the operation as "didn't exist at all."
    """
    entity_id = f"{domain}.{object_id}"
    if hass.states.get(entity_id) is not None:
        return ValidationError(
            code=f"{domain}_not_editable_by_agent",
            message=(
                f"{domain.capitalize()} '{object_id}' exists in Home Assistant "
                f"but is not in the file this integration manages "
                f"(/config/{domain}s.yaml for automations/scripts/scenes; "
                "other YAML includes, packages, and .storage entries are not "
                "editable through the agent)."
            ),
            path="object_id",
        )
    return ValidationError(
        code=f"unknown_{domain}",
        message=f"No {domain} found with object_id '{object_id}'.",
        path="object_id",
    )
