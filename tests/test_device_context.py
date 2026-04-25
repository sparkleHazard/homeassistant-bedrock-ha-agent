"""Test device context is properly included in conversation."""
import pytest
from unittest.mock import Mock, patch, MagicMock
import json
from homeassistant.core import HomeAssistant
from homeassistant.components import conversation
from custom_components.bedrock_ha_agent.bedrock_client import (
    BedrockClient, 
    DeviceInfo
)
from custom_components.bedrock_ha_agent.const import (
    DEFAULT_PROMPT,
    CONF_AWS_ACCESS_KEY_ID,
    CONF_AWS_SECRET_ACCESS_KEY,
    CONF_AWS_REGION,
    CONF_EXTRA_ATTRIBUTES_TO_EXPOSE,
    DEFAULT_EXTRA_ATTRIBUTES,
)


@pytest.mark.asyncio
async def test_conversation_includes_device_list_in_system_prompt(hass: HomeAssistant):
    """Test that device list is included in system prompt."""
    mock_entry = Mock()
    mock_entry.data = {
        CONF_AWS_ACCESS_KEY_ID: "test_key",
        CONF_AWS_SECRET_ACCESS_KEY: "test_secret",
        CONF_AWS_REGION: "us-west-2",
    }
    mock_entry.options = {
        CONF_EXTRA_ATTRIBUTES_TO_EXPOSE: DEFAULT_EXTRA_ATTRIBUTES
    }
    
    with patch("custom_components.bedrock_ha_agent.bedrock_client.boto3.Session"):
        client = BedrockClient(hass, mock_entry)
        
        with patch.object(client, "_get_exposed_entities") as mock_get_entities:
            mock_get_entities.return_value = [
                DeviceInfo(
                    entity_id="light.living_room",
                    name="Living Room Light",
                    state="on",
                    attributes=["brightness:200"],
                    area_name="Living Room",
                ),
                DeviceInfo(
                    entity_id="climate.bedroom",
                    name="Bedroom Climate",
                    state="heat",
                    attributes=["temp:72"],
                    area_name="Bedroom",
                ),
            ]
            
            system_prompt = await client._generate_system_prompt(
                DEFAULT_PROMPT,
                None,
                {}
            )
            
            assert "light.living_room" in system_prompt
            assert "Living Room Light" in system_prompt
            assert "climate.bedroom" in system_prompt
            assert "Bedroom Climate" in system_prompt
            assert "Living Room" in system_prompt
            assert "Bedroom" in system_prompt
