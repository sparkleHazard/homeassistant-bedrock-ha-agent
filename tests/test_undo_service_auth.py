"""Tests for H2: undo service admin authorization check."""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock
import pytest

from homeassistant.exceptions import Unauthorized


@pytest.mark.asyncio
async def test_undo_service_non_admin_user_rejected():
    """Test that non-admin user is rejected (H2 fix)."""
    from custom_components.bedrock_ha_agent import _async_register_undo_service

    # Create minimal mock hass
    mock_hass = Mock()
    mock_hass.auth = Mock()
    mock_hass.services = Mock()
    mock_hass.config_entries = Mock()
    mock_hass.config_entries.async_entries = Mock(return_value=[])

    # Mock non-admin user
    non_admin_user = Mock()
    non_admin_user.is_admin = False
    mock_hass.auth.async_get_user = AsyncMock(return_value=non_admin_user)

    # Capture the service handler
    service_handler = None

    def capture_handler(domain, service, handler, **kwargs):
        nonlocal service_handler
        service_handler = handler

    mock_hass.services.async_register = capture_handler

    # Register the service
    await _async_register_undo_service(mock_hass)

    assert service_handler is not None

    # Create a service call with a non-admin user context
    call = Mock()
    call.context = Mock()
    call.context.user_id = "non_admin_123"
    call.data = {}

    # Should raise Unauthorized
    with pytest.raises(Unauthorized):
        await service_handler(call)


@pytest.mark.asyncio
async def test_undo_service_admin_user_allowed():
    """Test that admin user is allowed (H2 fix)."""
    from custom_components.bedrock_ha_agent import _async_register_undo_service
    from custom_components.bedrock_ha_agent.runtime_data import BedrockRuntimeData
    from homeassistant.config_entries import ConfigEntryState

    # Create minimal mock hass
    mock_hass = Mock()
    mock_hass.auth = Mock()
    mock_hass.services = Mock()
    mock_hass.config_entries = Mock()

    # Mock admin user
    admin_user = Mock()
    admin_user.is_admin = True
    mock_hass.auth.async_get_user = AsyncMock(return_value=admin_user)

    # Mock config entry with proper runtime_data
    entry = Mock()
    entry.entry_id = "test_entry"
    entry.state = ConfigEntryState.LOADED
    entry.options = {}
    entry.runtime_data = BedrockRuntimeData()

    mock_hass.config_entries.async_entries = Mock(return_value=[entry])
    mock_hass.config_entries.async_get_entry = Mock(return_value=entry)

    # Capture the service handler
    service_handler = None

    def capture_handler(domain, service, handler, **kwargs):
        nonlocal service_handler
        service_handler = handler

    mock_hass.services.async_register = capture_handler

    # Register the service
    await _async_register_undo_service(mock_hass)

    assert service_handler is not None

    # Create a service call with an admin user context
    call = Mock()
    call.context = Mock()
    call.context.user_id = "admin_456"
    call.data = {}

    # Should succeed (no undo history, but no auth error)
    result = await service_handler(call)
    assert result["undone"] is False
    assert "Nothing to undo" in result["summary"]


@pytest.mark.asyncio
async def test_undo_service_no_user_context_allowed():
    """Test that calls without user context (automation/script) are allowed (H2 fix)."""
    from custom_components.bedrock_ha_agent import _async_register_undo_service
    from custom_components.bedrock_ha_agent.runtime_data import BedrockRuntimeData
    from homeassistant.config_entries import ConfigEntryState

    # Create minimal mock hass
    mock_hass = Mock()
    mock_hass.auth = Mock()
    mock_hass.services = Mock()
    mock_hass.config_entries = Mock()

    # Mock config entry with proper runtime_data
    entry = Mock()
    entry.entry_id = "test_entry"
    entry.state = ConfigEntryState.LOADED
    entry.options = {}
    entry.runtime_data = BedrockRuntimeData()

    mock_hass.config_entries.async_entries = Mock(return_value=[entry])
    mock_hass.config_entries.async_get_entry = Mock(return_value=entry)

    # Capture the service handler
    service_handler = None

    def capture_handler(domain, service, handler, **kwargs):
        nonlocal service_handler
        service_handler = handler

    mock_hass.services.async_register = capture_handler

    # Register the service
    await _async_register_undo_service(mock_hass)

    assert service_handler is not None

    # Create a service call with NO user context (automation/script)
    call = Mock()
    call.context = Mock()
    call.context.user_id = None
    call.data = {}

    # Should succeed without checking auth
    result = await service_handler(call)
    assert result["undone"] is False
    assert "Nothing to undo" in result["summary"]
