"""Test system prompt generation with device context."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from homeassistant.core import HomeAssistant
from custom_components.bedrock_ha_agent.bedrock_client import BedrockClient
from custom_components.bedrock_ha_agent.const import (
    DEFAULT_PROMPT,
    CONF_AWS_ACCESS_KEY_ID,
    CONF_AWS_SECRET_ACCESS_KEY,
    CONF_AWS_REGION,
)


@pytest.mark.asyncio
async def test_system_prompt_includes_device_info(hass: HomeAssistant):
    """Test that the system prompt includes device information."""
    # Create a mock config entry
    mock_entry = Mock()
    mock_entry.data = {
        CONF_AWS_ACCESS_KEY_ID: "test_key",
        CONF_AWS_SECRET_ACCESS_KEY: "test_secret",
        CONF_AWS_REGION: "us-west-2",
    }
    mock_entry.options = {}
    
    # Mock boto3 session and client
    with patch("custom_components.bedrock_ha_agent.bedrock_client.boto3.Session") as mock_session:
        mock_bedrock = MagicMock()
        mock_session.return_value.client.return_value = mock_bedrock
        
        # Create the client
        client = BedrockClient(hass, mock_entry)
        
        # Mock exposed entities
        with patch.object(client, "_get_exposed_entities") as mock_get_entities:
            from custom_components.bedrock_ha_agent.bedrock_client import DeviceInfo
            
            mock_get_entities.return_value = [
                DeviceInfo(
                    entity_id="light.living_room",
                    name="Living Room Light",
                    state="on",
                    attributes=["brightness:50%"],
                    area_name="Living Room",
                ),
                DeviceInfo(
                    entity_id="climate.bedroom",
                    name="Bedroom Thermostat",
                    state="heat",
                    attributes=["temp:72°F"],
                    area_name="Bedroom",
                ),
            ]
            
            # Generate system prompt
            system_prompt = await client._generate_system_prompt(
                DEFAULT_PROMPT,
                None,
                {}
            )
            
            # Verify the prompt includes key information
            assert "Home Assistant" in system_prompt
            assert "device" in system_prompt.lower()
            assert "Living Room Light" in system_prompt
            assert "light.living_room" in system_prompt
            assert "Bedroom Thermostat" in system_prompt
            assert "climate.bedroom" in system_prompt
            
            # Verify it doesn't have unreplaced placeholders
            assert "<persona>" not in system_prompt
            assert "<devices>" not in system_prompt
            assert "<current_date>" not in system_prompt
            
            print("✓ System prompt includes device context")
            print("\nGenerated prompt preview:")
            print(system_prompt[:500] + "...")
