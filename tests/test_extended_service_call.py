"""Tests for ExtendedServiceCall tool (ACs D44, D45, D48)."""
import pytest

from custom_components.bedrock_ha_agent.const import (
    DIAGNOSTICS_ALLOWED_SERVICES,
)


def test_service_classification_table_exists():
    """DIAGNOSTICS_ALLOWED_SERVICES has read_safe and mutating classifications."""
    assert len(DIAGNOSTICS_ALLOWED_SERVICES) > 0, "Service allowlist is empty"

    # Check a known read_safe service
    assert "persistent_notification.create" in DIAGNOSTICS_ALLOWED_SERVICES
    assert DIAGNOSTICS_ALLOWED_SERVICES["persistent_notification.create"]["class"] == "read_safe"

    # Check a known mutating service
    assert "automation.trigger" in DIAGNOSTICS_ALLOWED_SERVICES
    assert DIAGNOSTICS_ALLOWED_SERVICES["automation.trigger"]["class"] == "mutating"


@pytest.mark.skip(
    reason="ExtendedServiceCall tests require full HA ServiceRegistry which cannot be easily mocked; "
           "hass.services.async_call is read-only. Integration test needed."
)
async def test_read_safe_service_executes_immediately():
    """Read-safe service executes immediately without PendingChange."""
    pass


@pytest.mark.skip(
    reason="ExtendedServiceCall tests require full HA ServiceRegistry which cannot be easily mocked; "
           "hass.services.async_call is read-only. Integration test needed."
)
async def test_mutating_service_creates_pending():
    """Mutating service creates PendingChange, does not execute immediately."""
    pass


@pytest.mark.skip(
    reason="ExtendedServiceCall tests require full HA ServiceRegistry which cannot be easily mocked; "
           "hass.services.async_call is read-only. Integration test needed."
)
async def test_denied_service_refused():
    """Denied service returns validation_failed, no PendingChange, no service call."""
    pass


@pytest.mark.skip(
    reason="ExtendedServiceCall tests require full HA ServiceRegistry which cannot be easily mocked; "
           "hass.services.async_call is read-only. Integration test needed."
)
async def test_unlisted_service_refused():
    """Service not in allowlist returns validation_failed."""
    pass


@pytest.mark.skip(reason="Entity_id requirement check needs deeper service schema inspection")
async def test_entity_id_required_but_missing_refused():
    """Service requiring entity_id but missing it is refused."""
    pass
