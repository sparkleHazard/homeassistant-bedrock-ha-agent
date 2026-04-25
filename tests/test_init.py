"""Test the Bedrock Home Assistant Agent initialization."""
import pytest
from unittest.mock import MagicMock

from custom_components.bedrock_ha_agent import HassServiceTool
from custom_components.bedrock_ha_agent.const import (
    DOMAIN,
    SERVICE_TOOL_NAME,
    DEFAULT_MODEL_ID,
)


def test_domain_constant():
    """Test domain constant."""
    assert DOMAIN == "bedrock_ha_agent"


def test_default_model():
    """Test default model."""
    assert "claude" in DEFAULT_MODEL_ID


def test_hass_service_tool_definition():
    """Test HassServiceTool definition."""
    # Create a mock hass object
    mock_hass = MagicMock()
    
    tool = HassServiceTool(mock_hass)
    assert tool.name == SERVICE_TOOL_NAME
    assert tool.description
    assert hasattr(tool, "parameters")
