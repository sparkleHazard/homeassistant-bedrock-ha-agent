"""Phase 5 Step 5.6: §3.j API entry resolution tests."""
from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bedrock_ha_agent.config_tools import ConfigEditingTool
from custom_components.bedrock_ha_agent.const import DOMAIN

pytest_plugins = ["pytest_homeassistant_custom_component"]


def test_resolve_via_device_registry_hit():
    """Test §3.j: device_id in llm_context resolves via device_registry."""

    # Create mock hass
    mock_hass = MagicMock(spec=HomeAssistant)
    mock_hass.config_entries = MagicMock()
    mock_hass.data = {}

    # Create mock device registry
    mock_dev_reg = MagicMock()
    mock_device = MagicMock()
    mock_device.config_entries = {"bedrock_entry_1", "other_entry"}

    mock_dev_reg.async_get.return_value = mock_device

    # Create bedrock entry
    bedrock_entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="bedrock_entry_1",
        state=ConfigEntryState.LOADED,
    )

    # Mock hass.config_entries
    mock_hass.config_entries.async_get_entry.return_value = bedrock_entry

    # Create llm_context with device_id
    llm_context = Mock(spec=llm.LLMContext)
    llm_context.device_id = "test_device_123"

    with patch(
        "homeassistant.helpers.device_registry.async_get", return_value=mock_dev_reg
    ):
        result = ConfigEditingTool._resolve_entry(mock_hass, llm_context)

    assert result == bedrock_entry
    mock_dev_reg.async_get.assert_called_once_with("test_device_123")


def test_resolve_fallback_single_entry():
    """Test §3.j: no device_id, single loaded entry resolves silently."""
    mock_hass = MagicMock(spec=HomeAssistant)
    mock_hass.config_entries = MagicMock()
    mock_hass.data = {}

    bedrock_entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="bedrock_entry_1",
        state=ConfigEntryState.LOADED,
    )

    mock_hass.config_entries.async_entries.return_value = [bedrock_entry]

    llm_context = Mock(spec=llm.LLMContext)
    llm_context.device_id = None

    result = ConfigEditingTool._resolve_entry(mock_hass, llm_context)

    assert result == bedrock_entry


def test_resolve_fallback_multi_entry_warns(caplog):
    """Test §3.j: multiple loaded entries, no device_id → returns first AND logs warning."""
    mock_hass = MagicMock(spec=HomeAssistant)
    mock_hass.config_entries = MagicMock()
    mock_hass.data = {}

    bedrock_entry_1 = MockConfigEntry(
        domain=DOMAIN,
        entry_id="bedrock_entry_1",
        state=ConfigEntryState.LOADED,
    )
    bedrock_entry_2 = MockConfigEntry(
        domain=DOMAIN,
        entry_id="bedrock_entry_2",
        state=ConfigEntryState.LOADED,
    )

    mock_hass.config_entries.async_entries.return_value = [
        bedrock_entry_1,
        bedrock_entry_2,
    ]

    llm_context = Mock(spec=llm.LLMContext)
    llm_context.device_id = None

    with caplog.at_level("WARNING"):
        result = ConfigEditingTool._resolve_entry(mock_hass, llm_context)

    # Returns first entry
    assert result == bedrock_entry_1

    # Logs warning mentioning fallback (check captured stderr shows the warning)
    assert any(
        record.levelname == "WARNING" and "falling back" in record.message
        for record in caplog.records
    )
    assert any(
        "bedrock_entry_1" in record.message
        for record in caplog.records
    )


def test_resolve_no_loaded_entries_returns_none():
    """Test: no loaded entries returns None."""
    mock_hass = MagicMock(spec=HomeAssistant)
    mock_hass.config_entries = MagicMock()
    mock_hass.data = {}

    mock_hass.config_entries.async_entries.return_value = []

    llm_context = Mock(spec=llm.LLMContext)
    llm_context.device_id = None

    result = ConfigEditingTool._resolve_entry(mock_hass, llm_context)

    assert result is None


def test_resolve_device_not_found_falls_back():
    """Test: device_id provided but not found in registry → falls back to single entry."""

    mock_hass = MagicMock(spec=HomeAssistant)
    mock_hass.config_entries = MagicMock()
    mock_hass.data = {}

    mock_dev_reg = MagicMock()
    mock_dev_reg.async_get.return_value = None  # Device not found

    bedrock_entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="bedrock_entry_1",
        state=ConfigEntryState.LOADED,
    )
    mock_hass.config_entries.async_entries.return_value = [bedrock_entry]

    llm_context = Mock(spec=llm.LLMContext)
    llm_context.device_id = "nonexistent_device"

    with patch(
        "homeassistant.helpers.device_registry.async_get", return_value=mock_dev_reg
    ):
        result = ConfigEditingTool._resolve_entry(mock_hass, llm_context)

    # Should fall back to single entry
    assert result == bedrock_entry
