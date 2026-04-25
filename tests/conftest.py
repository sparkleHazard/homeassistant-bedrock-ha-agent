"""Test fixtures for bedrock_ha_agent."""
import pytest
from unittest.mock import AsyncMock, MagicMock


# Register custom markers used by new tests.
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "no_file_io: marks tests enforcing the no-file-I/O-under-/config invariant",
    )


@pytest.fixture
def mock_setup_entry():
    """Mock setting up a config entry."""
    return AsyncMock(return_value=True)


@pytest.fixture
def mock_unload_entry():
    """Mock unloading a config entry."""
    return AsyncMock(return_value=True)


# The real `hass` fixture is provided by pytest-homeassistant-custom-component
# (declared as pytest_plugins in tests that need it). Tests that only need a
# lightweight mock should request `mock_hass` instead of `hass`.
@pytest.fixture
def mock_hass():
    """Lightweight synchronous MagicMock stand-in for HA.

    Prefer the real `hass` fixture from pytest-homeassistant-custom-component for
    anything that exercises HA internals (entity_registry, area_registry, storage,
    lovelace, etc.). Use this mock for narrowly-scoped tests that only need to
    stub `hass.data` / `hass.services` / `hass.states`.
    """
    mock = MagicMock()
    mock.data = {}
    mock.services = MagicMock()
    mock.states = MagicMock()
    mock.config = MagicMock()
    mock.config.config_dir = "/tmp/ha-test"
    mock.loop = None
    mock.async_add_executor_job = AsyncMock()
    mock.async_create_task = AsyncMock()
    return mock
