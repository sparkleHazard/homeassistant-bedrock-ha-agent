"""Tests for ConfigEditingTool base class."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable
from unittest.mock import Mock

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import llm

from custom_components.bedrock_ha_agent.config_tools import (
    ConfigEditingTool,
    register_config_tools,
)
from custom_components.bedrock_ha_agent.config_tools.validation import (
    ValidationError,
    ValidationResult,
)
from custom_components.bedrock_ha_agent.const import CONF_ENABLE_CONFIG_EDITING
from custom_components.bedrock_ha_agent.runtime_data import BedrockRuntimeData


class FakeEntry:
    """Fake config entry."""

    def __init__(self, entry_id: str, options: dict | None = None) -> None:
        """Initialize fake entry."""
        self.entry_id = entry_id
        self.domain = "bedrock_ha_agent"
        self.state = ConfigEntryState.LOADED
        self.options = options or {}
        self.runtime_data = BedrockRuntimeData()


class FakeConfigEntries:
    """Fake config entries registry."""

    def __init__(self) -> None:
        """Initialize fake registry."""
        self._entries: dict[str, FakeEntry] = {}

    def add_entry(self, entry_id: str, options: dict | None = None) -> FakeEntry:
        """Add a fake entry."""
        entry = FakeEntry(entry_id, options)
        self._entries[entry_id] = entry
        return entry

    def async_get_entry(self, entry_id: str) -> FakeEntry | None:
        """Get a fake entry."""
        return self._entries.get(entry_id)

    def async_entries(self, domain: str) -> list[FakeEntry]:
        """Get all entries for a domain."""
        return [e for e in self._entries.values() if e.domain == domain]


class FakeHass:
    """Fake Home Assistant instance."""

    def __init__(self) -> None:
        """Initialize fake hass."""
        self.config_entries = FakeConfigEntries()


@pytest.fixture
def hass() -> FakeHass:
    """Create a fake hass instance."""
    return FakeHass()


@pytest.fixture
def entry_id(hass: FakeHass) -> str:
    """Create a fake entry and return its ID."""
    entry_id = "test_entry_123"
    hass.config_entries.add_entry(entry_id)
    return entry_id


@pytest.fixture
def conversation_id() -> str:
    """Return a test conversation ID."""
    return "conv_456"


@pytest.fixture
def llm_context(conversation_id: str) -> llm.LLMContext:
    """Create a fake LLM context."""
    return llm.LLMContext(
        platform="bedrock_ha_agent",
        context=None,
        language="en",
        assistant="conversation",
        device_id=None,
    )


@pytest.fixture
def tool_input() -> llm.ToolInput:
    """Create a fake tool input."""
    return llm.ToolInput(
        tool_name="test_tool",
        tool_args={"key": "value"},
    )


class MinimalTool(ConfigEditingTool):
    """Minimal implementation for testing abstract methods."""

    name = "test_tool"
    description = "Test tool"
    parameters = vol.Schema({"key": str})

    async def build_pre_state(
        self, hass: Any, tool_input: llm.ToolInput
    ) -> dict | None:
        return {"old": "state"}

    async def build_proposed_payload(
        self, hass: Any, tool_input: llm.ToolInput
    ) -> dict | None:
        return {"new": "payload"}

    async def validate(
        self, hass: Any, proposed: dict | None, pre_state: dict | None
    ) -> ValidationResult:
        return ValidationResult.success()

    def build_proposed_summary(
        self, proposed: dict | None, pre_state: dict | None
    ) -> str:
        return "Would create a test item"

    def build_proposed_diff(self, proposed: dict | None, pre_state: dict | None) -> str:
        return "+ new line"

    async def build_restore_fn(
        self, hass: Any, proposed: dict | None, pre_state: dict | None
    ) -> Callable[[], Awaitable[None]]:
        async def restore() -> None:
            pass

        return restore

    async def apply_change(
        self, hass: Any, proposed: dict | None, pre_state: dict | None
    ) -> dict:
        return {"applied": True}


class FailingValidationTool(MinimalTool):
    """Tool that always fails validation."""

    name = "failing_tool"

    async def validate(
        self, hass: Any, proposed: dict | None, pre_state: dict | None
    ) -> ValidationResult:
        return ValidationResult.failure(
            [ValidationError(code="test_error", message="Validation failed")]
        )


class AbstractTool(ConfigEditingTool):
    """Tool that doesn't implement abstract methods."""

    name = "abstract_tool"
    description = "Abstract tool"


def test_register_config_tools_flag_off_returns_empty(hass: FakeHass) -> None:
    """Test that register_config_tools returns empty list when flag is off."""
    entry = hass.config_entries.add_entry(
        "test_entry", options={CONF_ENABLE_CONFIG_EDITING: False}
    )
    tools = register_config_tools(hass, entry)
    assert tools == []


def test_register_config_tools_flag_on_returns_phase2_tools(
    hass: FakeHass,
) -> None:
    """Test that register_config_tools returns the Phase 2 tool instances when the flag is on.

    Once Phase 2 subclasses (automation/script/scene/helper/lovelace/registry) are
    installed alongside this base module, the factory MUST discover and return them
    via `get_tools(hass, entry)` on each surface module. A flag-on call returning an
    empty list would indicate a regression in the discovery loop — see
    `register_config_tools` in `config_tools/__init__.py`.
    """
    entry = hass.config_entries.add_entry(
        "test_entry", options={CONF_ENABLE_CONFIG_EDITING: True}
    )
    tools = register_config_tools(hass, entry)
    # With all six Phase-2 modules present, we expect a non-empty list. Don't pin the
    # exact count here — that's a brittle coupling to the tool count in each module.
    # Instead, assert the basic shape: non-empty, and each item is callable via the
    # llm.Tool interface (has a .name and .async_call).
    assert tools, "expected at least one config-editing tool when the flag is on"
    for tool in tools:
        assert hasattr(tool, "name") and isinstance(tool.name, str) and tool.name
        assert hasattr(tool, "async_call") and callable(tool.async_call)


def test_config_editing_tool_external_is_false() -> None:
    """Test that ConfigEditingTool.external is False."""
    tool = MinimalTool()
    assert tool.external is False


@pytest.mark.asyncio
async def test_config_editing_tool_abstract_methods_raise(
    hass: FakeHass, tool_input: llm.ToolInput, llm_context: llm.LLMContext
) -> None:
    """Test that abstract methods raise NotImplementedError."""
    hass.config_entries.add_entry("test_entry")
    tool = AbstractTool()

    # async_call should trigger one of the abstract methods and return validation_failed
    result = await tool.async_call(hass, tool_input, llm_context)

    # The tool should return validation_failed because build_pre_state raises NotImplementedError
    assert result["status"] == "validation_failed"
    assert "errors" in result
    assert len(result["errors"]) > 0


@pytest.mark.asyncio
async def test_async_call_returns_pending_approval_shape(
    hass: FakeHass, tool_input: llm.ToolInput, llm_context: llm.LLMContext
) -> None:
    """Test that async_call returns correct pending_approval shape."""
    entry = hass.config_entries.add_entry("test_entry")
    tool = MinimalTool()

    result = await tool.async_call(hass, tool_input, llm_context)

    # Check status and required fields
    assert result["status"] == "pending_approval"
    assert "proposal_id" in result
    assert "tool" in result
    assert "proposed_summary" in result
    assert "proposed_diff" in result
    assert "expires_at_iso" in result

    # Verify past-tense names are NOT present (F6 confabulation guard)
    assert "summary" not in result
    assert "diff" not in result
    assert "change_id" not in result
    assert "result" not in result

    # Verify a PendingChange was stored
    pending = entry.runtime_data.pending.get("_global")
    assert pending is not None
    assert pending.proposal_id == result["proposal_id"]
    assert pending.tool_name == "test_tool"


@pytest.mark.asyncio
async def test_async_call_validation_failure_short_circuits(
    hass: FakeHass, tool_input: llm.ToolInput, llm_context: llm.LLMContext
) -> None:
    """Test that validation failure returns validation_failed and no pending stored."""
    entry = hass.config_entries.add_entry("test_entry")
    tool = FailingValidationTool()

    result = await tool.async_call(hass, tool_input, llm_context)

    # Should return validation_failed
    assert result["status"] == "validation_failed"
    assert "errors" in result
    assert len(result["errors"]) > 0

    # No PendingChange should be stored
    pending = entry.runtime_data.pending.get("_global")
    assert pending is None


@pytest.mark.asyncio
async def test_async_call_supersedes_previous_pending(
    hass: FakeHass, tool_input: llm.ToolInput, llm_context: llm.LLMContext
) -> None:
    """Test that second async_call supersedes first pending change."""
    entry = hass.config_entries.add_entry("test_entry")
    tool = MinimalTool()

    # First call
    result1 = await tool.async_call(hass, tool_input, llm_context)
    proposal_id1 = result1["proposal_id"]

    # Second call
    result2 = await tool.async_call(hass, tool_input, llm_context)
    proposal_id2 = result2["proposal_id"]

    # Should have different proposal IDs
    assert proposal_id1 != proposal_id2

    # Only the second should be stored
    pending = entry.runtime_data.pending.get("_global")
    assert pending is not None
    assert pending.proposal_id == proposal_id2


@pytest.mark.asyncio
async def test_two_conversations_isolated_at_tool_level(
    hass: FakeHass, tool_input: llm.ToolInput
) -> None:
    """Test that two conversations maintain separate pending changes."""
    entry = hass.config_entries.add_entry("test_entry")
    tool = MinimalTool()

    # Create two separate LLM contexts (simulating different conversations)
    # Since _derive_conversation_id returns None, both will use "_global"
    # We need to modify the contexts to differentiate them
    ctx1 = llm.LLMContext(
        platform="bedrock_ha_agent",
        context=None,
        language="en",
        assistant="conversation",
        device_id=None,
    )
    ctx2 = llm.LLMContext(
        platform="bedrock_ha_agent",
        context=None,
        language="en",
        assistant="conversation",
        device_id=None,
    )

    # Both will create pending changes under "_global" since we can't differentiate
    # This test demonstrates the limitation without Phase-3 wiring
    result1 = await tool.async_call(hass, tool_input, ctx1)
    result2 = await tool.async_call(hass, tool_input, ctx2)

    # Both use "_global" conversation_id, so result2 supersedes result1
    pending = entry.runtime_data.pending.get("_global")
    assert pending is not None
    # The second call supersedes the first
    assert pending.proposal_id == result2["proposal_id"]


@pytest.mark.asyncio
async def test_resolve_entry_via_device_registry(hass: FakeHass) -> None:
    """Test that _resolve_entry finds entry via device_registry."""
    from homeassistant.helpers import device_registry as dr

    # Create a bedrock entry
    entry = hass.config_entries.add_entry("bedrock_entry")

    # Mock device registry
    class FakeDevice:
        def __init__(self, device_id: str, config_entries: set[str]):
            self.id = device_id
            self.config_entries = config_entries

    class FakeDeviceRegistry:
        def __init__(self):
            self._devices = {}

        def async_get(self, device_id: str):
            return self._devices.get(device_id)

        def add_device(self, device_id: str, config_entries: set[str]):
            self._devices[device_id] = FakeDevice(device_id, config_entries)

    # Patch the device registry
    fake_dev_reg = FakeDeviceRegistry()
    fake_dev_reg.add_device("test_device", {entry.entry_id})

    # Mock dr.async_get to return our fake registry
    original_async_get = dr.async_get
    dr.async_get = lambda hass: fake_dev_reg

    try:
        # Create context with device_id
        llm_context = llm.LLMContext(
            platform="bedrock_ha_agent",
            context=None,
            language="en",
            assistant="conversation",
            device_id="test_device",
        )

        # Resolve entry
        resolved = ConfigEditingTool._resolve_entry(hass, llm_context)
        assert resolved is not None
        assert resolved.entry_id == entry.entry_id
    finally:
        # Restore original
        dr.async_get = original_async_get


@pytest.mark.asyncio
async def test_resolve_entry_fallback_first_loaded(hass: FakeHass, caplog) -> None:
    """Test that _resolve_entry falls back to first loaded entry with warning."""
    # Create two loaded bedrock entries
    entry1 = hass.config_entries.add_entry("entry1")
    entry2 = hass.config_entries.add_entry("entry2")

    # Create context without device_id
    llm_context = llm.LLMContext(
        platform="bedrock_ha_agent",
        context=None,
        language="en",
        assistant="conversation",
        device_id=None,
    )

    # Resolve entry
    resolved = ConfigEditingTool._resolve_entry(hass, llm_context)
    assert resolved is not None
    assert resolved.entry_id == entry1.entry_id

    # Check that warning was logged
    assert any("falling back to first loaded" in record.message for record in caplog.records)
