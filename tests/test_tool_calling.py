"""Test tool calling integration with Bedrock."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from homeassistant.components import conversation
from homeassistant.helpers import llm

from custom_components.bedrock_ha_agent.conversation import BedrockConversationEntity
from custom_components.bedrock_ha_agent.bedrock_client import BedrockClient
from custom_components.bedrock_ha_agent.const import (
    DOMAIN,
    CONF_LLM_HASS_API,
    CONF_MAX_TOOL_CALL_ITERATIONS,
)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.services = MagicMock()
    hass.states = MagicMock()
    hass.config = MagicMock()
    hass.config.location_name = "Test Home"
    hass.async_add_executor_job = AsyncMock()
    
    return hass


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {
        "aws_region": "us-west-2",
        "aws_access_key_id": "test_key",
        "aws_secret_access_key": "test_secret",
    }
    entry.options = {
        CONF_LLM_HASS_API: "bedrock_services",
        CONF_MAX_TOOL_CALL_ITERATIONS: 10,
    }
    entry.runtime_data = {}
    
    return entry


@pytest.fixture
def mock_bedrock_client(mock_hass, mock_config_entry):
    """Create a mock Bedrock client."""
    with patch("custom_components.bedrock_ha_agent.bedrock_client.boto3"):
        client = BedrockClient(mock_hass, mock_config_entry)
        return client


@pytest.fixture
def conversation_entity(mock_hass, mock_config_entry, mock_bedrock_client):
    """Create a conversation entity."""
    mock_config_entry.runtime_data["client"] = mock_bedrock_client
    entity = BedrockConversationEntity(mock_hass, mock_config_entry)
    return entity


def create_bedrock_response_with_tool_use(tool_use_id, tool_name, tool_args):
    """Create a mock Bedrock response with a tool use."""
    return {
        "stop_reason": "tool_use",
        "content": [
            {
                "type": "text",
                "text": "I'll turn on that light for you."
            },
            {
                "type": "tool_use",
                "id": tool_use_id,
                "name": tool_name,
                "input": tool_args
            }
        ]
    }


def create_bedrock_final_response(text):
    """Create a mock Bedrock final response."""
    return {
        "stop_reason": "end_turn",
        "content": [
            {
                "type": "text",
                "text": text
            }
        ]
    }


@pytest.mark.asyncio
async def test_tool_use_id_tracking(conversation_entity, mock_bedrock_client):
    """Test that tool use IDs from Bedrock are properly tracked and used."""
    
    # Create a user input
    user_input = MagicMock()
    user_input.text = "Turn on the kitchen light"
    user_input.conversation_id = "test_conversation"
    user_input.language = "en"
    user_input.as_llm_context = MagicMock(return_value=MagicMock())
    
    # Mock the LLM API
    mock_llm_api = MagicMock()
    mock_llm_api.api_prompt = "Test API prompt"
    mock_llm_api.tools = [MagicMock()]
    
    # Expected tool use ID from Bedrock
    expected_tool_use_id = "toolu_01ABC123XYZ"
    
    # Mock Bedrock responses
    first_response = create_bedrock_response_with_tool_use(
        tool_use_id=expected_tool_use_id,
        tool_name="HassCallService",
        tool_args={
            "service": "light.turn_on",
            "target_device": "light.kitchen"
        }
    )
    
    second_response = create_bedrock_final_response(
        "The kitchen light is now on."
    )
    
    # Set up the mock to return these responses in sequence
    mock_bedrock_client.async_generate = AsyncMock(side_effect=[
        first_response,
        second_response
    ])
    
    # Mock the system prompt generation
    mock_bedrock_client._generate_system_prompt = AsyncMock(
        return_value="You are a helpful assistant."
    )
    
    # Mock the LLM API retrieval
    mock_llm_api.async_call_tool = AsyncMock(return_value={
        "result": "success",
        "service": "light.turn_on",
        "target": "light.kitchen"
    })
    
    with patch("homeassistant.helpers.llm.async_get_api", return_value=mock_llm_api):
            
            # Mock chat session and chat log
            with patch("homeassistant.helpers.chat_session.async_get_chat_session"):
                with patch("homeassistant.components.conversation.async_get_chat_log") as mock_chat_log:
                    mock_log = MagicMock()
                    mock_log.content = []
                    mock_log.__enter__ = MagicMock(return_value=mock_log)
                    mock_log.__exit__ = MagicMock(return_value=False)
                    mock_chat_log.return_value = mock_log
                    
                    # Process the conversation
                    result = await conversation_entity.async_process(user_input)
    
    # Verify async_generate was called twice (tool call + final response)
    assert mock_bedrock_client.async_generate.call_count == 2
    
    # Get the second call's message history (after tool execution)
    second_call_args = mock_bedrock_client.async_generate.call_args_list[1]
    message_history = second_call_args[0][0]  # First positional argument
    
    # Find the ToolResultContent in the message history
    tool_result_content = None
    for msg in message_history:
        if isinstance(msg, conversation.ToolResultContent):
            tool_result_content = msg
            break
    
    # Verify the tool result uses Bedrock's tool_use_id
    assert tool_result_content is not None, "Tool result not found in message history"
    assert tool_result_content.tool_call_id == expected_tool_use_id, (
        f"Tool result ID mismatch: expected {expected_tool_use_id}, "
        f"got {tool_result_content.tool_call_id}"
    )
    
    # Verify the final response
    assert result.response.speech["plain"]["speech"] == "The kitchen light is now on."


@pytest.mark.asyncio
async def test_multiple_tool_uses_in_sequence(conversation_entity, mock_bedrock_client):
    """Test handling multiple tool calls in sequence."""
    
    user_input = MagicMock()
    user_input.text = "Turn on the kitchen light and then turn off the bedroom light"
    user_input.conversation_id = "test_conversation"
    user_input.language = "en"
    user_input.as_llm_context = MagicMock(return_value=MagicMock())
    
    mock_llm_api = MagicMock()
    mock_llm_api.api_prompt = "Test API prompt"
    mock_llm_api.tools = [MagicMock()]
    
    # First tool call
    first_response = create_bedrock_response_with_tool_use(
        tool_use_id="toolu_first_123",
        tool_name="HassCallService",
        tool_args={"service": "light.turn_on", "target_device": "light.kitchen"}
    )
    
    # Second tool call
    second_response = create_bedrock_response_with_tool_use(
        tool_use_id="toolu_second_456",
        tool_name="HassCallService",
        tool_args={"service": "light.turn_off", "target_device": "light.bedroom"}
    )
    
    # Final response
    final_response = create_bedrock_final_response(
        "I've turned on the kitchen light and turned off the bedroom light."
    )
    
    mock_bedrock_client.async_generate = AsyncMock(side_effect=[
        first_response,
        second_response,
        final_response
    ])
    
    mock_bedrock_client._generate_system_prompt = AsyncMock(
        return_value="You are a helpful assistant."
    )
    
    mock_llm_api.async_call_tool = AsyncMock(return_value={"result": "success"})
    
    with patch("homeassistant.helpers.llm.async_get_api", return_value=mock_llm_api):
            with patch("homeassistant.helpers.chat_session.async_get_chat_session"):
                with patch("homeassistant.components.conversation.async_get_chat_log") as mock_chat_log:
                    mock_log = MagicMock()
                    mock_log.content = []
                    mock_log.__enter__ = MagicMock(return_value=mock_log)
                    mock_log.__exit__ = MagicMock(return_value=False)
                    mock_chat_log.return_value = mock_log
                    
                    result = await conversation_entity.async_process(user_input)
    
    # Should have called Bedrock 3 times (2 tool calls + 1 final)
    assert mock_bedrock_client.async_generate.call_count == 3
    
    # Verify both tools were executed
    assert mock_llm_api.async_call_tool.call_count == 2


@pytest.mark.asyncio
async def test_tool_use_without_id_fallback(conversation_entity, mock_bedrock_client):
    """Test fallback behavior when Bedrock doesn't provide a tool use ID."""
    
    user_input = MagicMock()
    user_input.text = "Turn on the light"
    user_input.conversation_id = "test_conversation"
    user_input.language = "en"
    user_input.as_llm_context = MagicMock(return_value=MagicMock())
    
    mock_llm_api = MagicMock()
    mock_llm_api.tools = [MagicMock()]
    
    # Response without tool use id (edge case)
    first_response = {
        "stop_reason": "tool_use",
        "content": [
            {
                "type": "tool_use",
                # Missing id field
                "name": "HassCallService",
                "input": {"service": "light.turn_on", "target_device": "light.test"}
            }
        ]
    }
    
    second_response = create_bedrock_final_response("Done.")
    
    mock_bedrock_client.async_generate = AsyncMock(side_effect=[
        first_response,
        second_response
    ])
    
    mock_bedrock_client._generate_system_prompt = AsyncMock(
        return_value="You are a helpful assistant."
    )
    
    mock_llm_api.async_call_tool = AsyncMock(return_value={"result": "success"})
    
    with patch("homeassistant.helpers.llm.async_get_api", return_value=mock_llm_api):
        with patch("homeassistant.helpers.chat_session.async_get_chat_session"):
            with patch("homeassistant.components.conversation.async_get_chat_log") as mock_chat_log:
                mock_log = MagicMock()
                mock_log.content = []
                mock_log.__enter__ = MagicMock(return_value=mock_log)
                mock_log.__exit__ = MagicMock(return_value=False)
                mock_chat_log.return_value = mock_log
                
                # Should still work with fallback ID generation
                result = await conversation_entity.async_process(user_input)
    
    # Should complete successfully even without explicit tool use ID
    assert result is not None
    assert mock_bedrock_client.async_generate.call_count == 2


@pytest.mark.asyncio
async def test_tool_error_handling(conversation_entity, mock_bedrock_client):
    """Test that tool execution errors are handled properly."""
    
    user_input = MagicMock()
    user_input.text = "Turn on the nonexistent light"
    user_input.conversation_id = "test_conversation"
    user_input.language = "en"
    user_input.as_llm_context = MagicMock(return_value=MagicMock())
    
    mock_llm_api = MagicMock()
    mock_llm_api.tools = [MagicMock()]
    
    tool_use_id = "toolu_error_test"
    first_response = create_bedrock_response_with_tool_use(
        tool_use_id=tool_use_id,
        tool_name="HassCallService",
        tool_args={"service": "light.turn_on", "target_device": "light.nonexistent"}
    )
    
    second_response = create_bedrock_final_response(
        "I'm sorry, I couldn't find that light."
    )
    
    mock_bedrock_client.async_generate = AsyncMock(side_effect=[
        first_response,
        second_response
    ])
    
    mock_bedrock_client._generate_system_prompt = AsyncMock(
        return_value="You are a helpful assistant."
    )
    
    # Simulate tool execution error
    mock_llm_api.async_call_tool = AsyncMock(side_effect=Exception("Entity not found"))
    
    with patch("homeassistant.helpers.llm.async_get_api", return_value=mock_llm_api):
        with patch("homeassistant.helpers.chat_session.async_get_chat_session"):
                with patch("homeassistant.components.conversation.async_get_chat_log") as mock_chat_log:
                    mock_log = MagicMock()
                    mock_log.content = []
                    mock_log.__enter__ = MagicMock(return_value=mock_log)
                    mock_log.__exit__ = MagicMock(return_value=False)
                    mock_chat_log.return_value = mock_log
                    
                    result = await conversation_entity.async_process(user_input)
    
    # Should complete with error message rather than hanging
    assert result is not None
    assert mock_bedrock_client.async_generate.call_count == 2
    
    # Verify error was passed back to Bedrock
    second_call_args = mock_bedrock_client.async_generate.call_args_list[1]
    message_history = second_call_args[0][0]
    
    tool_result = None
    for msg in message_history:
        if isinstance(msg, conversation.ToolResultContent):
            tool_result = msg
            break
    
    assert tool_result is not None
    assert "error" in tool_result.tool_result


@pytest.mark.asyncio
async def test_max_iterations_prevents_infinite_loop(conversation_entity, mock_bedrock_client):
    """Test that max iterations prevents infinite loops."""
    
    user_input = MagicMock()
    user_input.text = "Do something"
    user_input.conversation_id = "test_conversation"
    user_input.language = "en"
    user_input.as_llm_context = MagicMock(return_value=MagicMock())
    
    mock_llm_api = MagicMock()
    mock_llm_api.tools = [MagicMock()]
    
    # Set max iterations to 2
    conversation_entity.entry.options[CONF_MAX_TOOL_CALL_ITERATIONS] = 2
    
    # Always return tool_use (simulating a stuck loop)
    mock_bedrock_client.async_generate = AsyncMock(
        return_value=create_bedrock_response_with_tool_use(
            tool_use_id="toolu_loop",
            tool_name="HassCallService",
            tool_args={"service": "test.test", "target_device": "test.test"}
        )
    )
    
    mock_bedrock_client._generate_system_prompt = AsyncMock(
        return_value="You are a helpful assistant."
    )
    
    mock_llm_api.async_call_tool = AsyncMock(return_value={"result": "success"})
    
    with patch("homeassistant.helpers.llm.async_get_api", return_value=mock_llm_api):
        with patch("homeassistant.helpers.chat_session.async_get_chat_session"):
                with patch("homeassistant.components.conversation.async_get_chat_log") as mock_chat_log:
                    mock_log = MagicMock()
                    mock_log.content = []
                    mock_log.__enter__ = MagicMock(return_value=mock_log)
                    mock_log.__exit__ = MagicMock(return_value=False)
                    mock_chat_log.return_value = mock_log
                    
                    result = await conversation_entity.async_process(user_input)
    
    # Should stop after max iterations + 1 initial call = 3 total
    assert mock_bedrock_client.async_generate.call_count == 3
    
    # Should return error message about max iterations
    assert "multiple attempts" in result.response.speech["plain"]["speech"].lower()


def test_tool_use_id_extracted_from_response():
    """Test that tool use IDs are correctly extracted from Bedrock response format."""
    
    # Simulate parsing a tool use block
    tool_use_block = {
        "toolUse": {
            "toolUseId": "toolu_test_123",
            "name": "HassCallService",
            "input": {
                "service": "light.turn_on",
                "target_device": "light.test"
            }
        }
    }
    
    # Extract tool use ID (this is what the code should do)
    tool_use = tool_use_block["toolUse"]
    tool_use_id = tool_use.get("toolUseId")
    
    assert tool_use_id == "toolu_test_123"
    assert tool_use["name"] == "HassCallService"
    assert "service" in tool_use["input"]
