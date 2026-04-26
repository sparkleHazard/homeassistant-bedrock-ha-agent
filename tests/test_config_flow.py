"Test the config flow for Bedrock Home Assistant Agent."
from unittest.mock import MagicMock, patch
from botocore.exceptions import NoCredentialsError

from homeassistant.core import HomeAssistant

from custom_components.bedrock_ha_agent.config_flow import validate_aws_credentials


async def test_validate_credentials_success(hass: HomeAssistant):
    """Test validation success."""
    with patch("boto3.Session") as mock_session:
        mock_boto_client = MagicMock()
        mock_boto_client.list_foundation_models.return_value = {"models": []}
        mock_session_instance = MagicMock()
        mock_session_instance.client.return_value = mock_boto_client
        mock_session.return_value = mock_session_instance
        
        result = await validate_aws_credentials(
            hass,
            "test_key",
            "test_secret"
        )
        
        assert result is None


async def test_validate_credentials_invalid(hass: HomeAssistant):
    """Test validation with invalid credentials."""
    # The key is to make hass.async_add_executor_job actually execute the function
    # so that the exception gets raised
    async def mock_executor_job(func, *args):
        """Mock executor that actually runs the function."""
        return func(*args)
    
    hass.async_add_executor_job = mock_executor_job
    
    with patch("boto3.Session") as mock_session:
        mock_boto_client = MagicMock()
        # Set the side_effect to raise NoCredentialsError when list_foundation_models is called
        mock_boto_client.list_foundation_models.side_effect = NoCredentialsError()
        mock_session_instance = MagicMock()
        mock_session_instance.client.return_value = mock_boto_client
        mock_session.return_value = mock_session_instance
        
        result = await validate_aws_credentials(
            hass,
            "invalid_key",
            "invalid_secret"
        )
        
        assert result == {"base": "invalid_credentials"}
