"""Test fixtures for bedrock_ha_agent."""
import pytest
from unittest.mock import AsyncMock


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
# via pytest_plugins declaration in individual test files.
