"""Integration tests for lovelace.py (requires hass fixture)."""
import pytest
from unittest.mock import MagicMock

from custom_components.bedrock_ha_agent.config_tools.ha_client import lovelace

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.mark.asyncio
async def test_get_dashboard_mode_default_returns_global_mode(hass):
    """Setup lovelace in storage mode, get_dashboard_mode for default returns 'storage'."""
    # Mock the lovelace component data structure
    from homeassistant.components.lovelace import DOMAIN as LOVELACE_DOMAIN

    # Create a mock data object with storage mode
    mock_data = MagicMock()
    mock_data.mode = "storage"
    mock_data.dashboards = {}

    hass.data[LOVELACE_DOMAIN] = mock_data

    mode = await lovelace.get_dashboard_mode(hass, None)
    assert mode == "storage"


@pytest.mark.asyncio
async def test_list_dashboards_empty_before_setup(hass):
    """Before lovelace setup, list_dashboards returns []."""
    # Don't set up lovelace data
    dashboards = await lovelace.list_dashboards(hass)
    assert dashboards == []


@pytest.mark.asyncio
async def test_list_dashboards_returns_registered_dashboards(hass):
    """Test listing dashboards when some are registered."""
    from homeassistant.components.lovelace import DOMAIN as LOVELACE_DOMAIN

    # Mock dashboard
    mock_dashboard = MagicMock()
    mock_dashboard.mode = "storage"
    mock_dashboard.config = {"title": "Test Dashboard"}

    mock_data = MagicMock()
    mock_data.dashboards = {"test-dash": mock_dashboard}

    hass.data[LOVELACE_DOMAIN] = mock_data

    dashboards = await lovelace.list_dashboards(hass)
    assert len(dashboards) == 1
    assert dashboards[0]["url_path"] == "test-dash"
    assert dashboards[0]["mode"] == "storage"
    assert dashboards[0]["title"] == "Test Dashboard"
