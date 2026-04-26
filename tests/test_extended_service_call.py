"""Tests for ExtendedServiceCall tool (ACs D44, D45, D48)."""
from unittest.mock import MagicMock

import pytest
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bedrock_ha_agent.const import (
    DIAGNOSTICS_ALLOWED_SERVICES,
    DOMAIN,
)
from custom_components.bedrock_ha_agent.diagnostics.services import (
    ExtendedServiceCall,
)
from custom_components.bedrock_ha_agent.runtime_data import BedrockRuntimeData

pytest_plugins = ["pytest_homeassistant_custom_component"]


def _make_entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry")
    entry.runtime_data = BedrockRuntimeData()
    entry.add_to_hass(hass)
    return entry


def _make_context(conv_id="test_conv"):
    ctx = MagicMock(spec=llm.LLMContext)
    ctx.device_id = None
    ctx.conversation_id = conv_id
    return ctx


def test_service_classification_table_exists():
    """DIAGNOSTICS_ALLOWED_SERVICES has read_safe and mutating classifications."""
    assert len(DIAGNOSTICS_ALLOWED_SERVICES) > 0, "Service allowlist is empty"
    assert "persistent_notification.create" in DIAGNOSTICS_ALLOWED_SERVICES
    assert (
        DIAGNOSTICS_ALLOWED_SERVICES["persistent_notification.create"]["class"]
        == "read_safe"
    )
    assert "automation.trigger" in DIAGNOSTICS_ALLOWED_SERVICES
    assert (
        DIAGNOSTICS_ALLOWED_SERVICES["automation.trigger"]["class"] == "mutating"
    )


@pytest.mark.asyncio
async def test_read_safe_service_executes_immediately(hass):
    """AC D45: read_safe service executes immediately; no PendingChange is created."""
    # Register a recording handler for system_log.clear (read_safe per the classification
    # table) and assert the tool dispatches it immediately without approval gating.
    calls: list = []

    async def _record(call):  # noqa: ARG001
        calls.append(call)

    hass.services.async_register("system_log", "clear", _record)
    await hass.async_block_till_done()

    entry = _make_entry(hass)
    tool = ExtendedServiceCall(hass, entry)
    tool_input = llm.ToolInput(
        tool_name="ExtendedServiceCall",
        tool_args={"service": "system_log.clear"},
    )

    result = await tool.async_call(hass, tool_input, _make_context())

    assert result["status"] == "ok", result
    assert result["service"] == "system_log.clear"
    # The service was actually invoked — no approval gate for read_safe.
    assert len(calls) == 1, f"read_safe should fire the service immediately, calls: {calls}"
    # And no PendingChange was created
    assert entry.runtime_data.pending == {}, (
        f"read_safe must not create PendingChange, got {entry.runtime_data.pending!r}"
    )


@pytest.mark.asyncio
async def test_mutating_service_creates_pending(hass):
    """AC D44: mutating service returns pending_approval and does NOT call the service."""
    # Register a recording handler. If ExtendedServiceCall has the approval gate
    # wired correctly, this handler MUST NOT fire — mutation should be deferred.
    calls: list = []

    async def _record(call):  # noqa: ARG001
        calls.append(call)

    hass.services.async_register("automation", "trigger", _record)
    await hass.async_block_till_done()

    entry = _make_entry(hass)
    tool = ExtendedServiceCall(hass, entry)
    tool_input = llm.ToolInput(
        tool_name="ExtendedServiceCall",
        tool_args={
            "service": "automation.trigger",
            "target": {"entity_id": "automation.test"},
        },
    )

    result = await tool.async_call(hass, tool_input, _make_context())

    assert result["status"] == "pending_approval", result
    assert result["tool"] == "ExtendedServiceCall"
    assert "proposal_id" in result
    assert result["proposed_summary"].startswith("Would call"), result
    # Crucial invariant: no real service call yet.
    assert calls == [], f"mutating service must not fire before approval, fired: {calls!r}"
    # Runtime data now holds the pending change for this conversation
    assert "test_conv" in entry.runtime_data.pending
    assert entry.runtime_data.pending["test_conv"] is not None


@pytest.mark.asyncio
async def test_denied_service_refused(hass):
    """Denied service returns validation_failed with code `service_denied`."""
    entry = _make_entry(hass)
    tool = ExtendedServiceCall(hass, entry)
    tool_input = llm.ToolInput(
        tool_name="ExtendedServiceCall",
        tool_args={"service": "homeassistant.restart"},
    )

    result = await tool.async_call(hass, tool_input, _make_context())

    assert result["status"] == "validation_failed", result
    codes = {e["code"] for e in result.get("errors", [])}
    assert "service_denied" in codes, f"expected service_denied, got {codes}"
    # No PendingChange was created
    assert entry.runtime_data.pending == {}


@pytest.mark.asyncio
async def test_unlisted_service_refused(hass):
    """Service not in allowlist returns validation_failed with code `service_not_allowed`."""
    entry = _make_entry(hass)
    tool = ExtendedServiceCall(hass, entry)
    tool_input = llm.ToolInput(
        tool_name="ExtendedServiceCall",
        tool_args={"service": "fake_domain.fake_service"},
    )

    result = await tool.async_call(hass, tool_input, _make_context())

    assert result["status"] == "validation_failed", result
    codes = {e["code"] for e in result.get("errors", [])}
    assert "service_not_allowed" in codes, f"expected service_not_allowed, got {codes}"


@pytest.mark.asyncio
async def test_entity_id_required_but_missing_refused(hass):
    """AC D48: entity_id-required service with no target/data is refused with code `entity_id_required`."""
    # Register automation.trigger so it passes the hass.services.has_service check
    # and reaches the entity_id-required gate.
    hass.services.async_register(
        "automation", "trigger", lambda call: None  # noqa: ARG005
    )
    await hass.async_block_till_done()

    entry = _make_entry(hass)
    tool = ExtendedServiceCall(hass, entry)
    tool_input = llm.ToolInput(
        tool_name="ExtendedServiceCall",
        tool_args={"service": "automation.trigger"},  # no target, no data
    )

    result = await tool.async_call(hass, tool_input, _make_context())

    assert result["status"] == "validation_failed", result
    codes = {e["code"] for e in result.get("errors", [])}
    assert "entity_id_required" in codes, f"expected entity_id_required, got {codes}"
    # No PendingChange was created
    assert entry.runtime_data.pending == {}
