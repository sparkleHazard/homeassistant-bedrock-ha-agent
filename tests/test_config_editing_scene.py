"""Tests for scene config-editing tools (AC7)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bedrock_ha_agent.config_tools.scene import (
    ConfigSceneCreate,
    ConfigSceneDelete,
    ConfigSceneEdit,
    get_tools,
)

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture
async def mock_entry(hass):
    """Create a real ConfigEntry for testing."""
    from homeassistant.config_entries import ConfigEntryState
    from custom_components.bedrock_ha_agent.const import DOMAIN
    from custom_components.bedrock_ha_agent.runtime_data import BedrockRuntimeData

    entry = hass.config_entries.async_entries(DOMAIN)
    if entry:
        return entry[0]

    # Create a real entry and mark it as loaded
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Entry",
        entry_id="test_entry",
        data={},
        options={"enable_config_editing": True},
        state=ConfigEntryState.LOADED,
    )
    entry.add_to_hass(hass)

    # Add runtime data
    entry.runtime_data = BedrockRuntimeData()

    return entry


@pytest.fixture
def mock_llm_context():
    """Mock LLM context."""
    ctx = MagicMock(spec=llm.LLMContext)
    ctx.device_id = None
    ctx.context = None
    return ctx


@pytest.fixture
def mock_scene_client():
    """Mock scene client functions."""
    with patch(
        "custom_components.bedrock_ha_agent.config_tools.scene.scene"
    ) as mock:
        mock.get_scene = AsyncMock(return_value=None)
        mock.create_or_update_scene = AsyncMock()
        mock.delete_scene = AsyncMock()
        mock.reload_scenes = AsyncMock()
        yield mock


@pytest.mark.asyncio
async def test_scene_create_golden_path(hass, mock_entry, mock_llm_context, mock_scene_client):
    """AC7: create → pending_approval → apply fires create_or_update_scene + reload; restore_fn calls delete."""

    # Mock entity registry
    from homeassistant.helpers import entity_registry as er

    reg = er.async_get(hass)
    reg.async_get_or_create("light", "test", "living_room", suggested_object_id="living_room")

    tool = ConfigSceneCreate()
    tool_input = llm.ToolInput(
        tool_name="ConfigSceneCreate",
        tool_args={
            "object_id": "evening",
            "config": {
                "name": "Evening Scene",
                "entities": {"light.living_room": "off"},
                "icon": "mdi:weather-night",
            },
        },
    )

    # Step 1: async_call returns pending_approval
    result = await tool.async_call(hass, tool_input, mock_llm_context)
    assert result["status"] == "pending_approval"
    assert "Evening Scene" in result["proposed_summary"]
    assert "Would add" in result["proposed_summary"]
    assert "proposal_id" in result

    # Step 2: Retrieve the pending change and apply it
    from custom_components.bedrock_ha_agent.config_tools.pending import (
        PendingChangeManager,
    )

    manager = PendingChangeManager.for_entry_conv(hass, mock_entry.entry_id, "_global")
    pending = manager.get_current()
    assert pending is not None

    # Apply the change
    proposed = pending.proposed_payload
    pre_state = pending.pre_state
    apply_result = await pending.apply_fn(hass, proposed, pre_state)
    assert apply_result["object_id"] == "evening"
    assert apply_result["entity_id"] == "scene.evening"
    mock_scene_client.create_or_update_scene.assert_called_once_with(
        hass, "evening", proposed
    )
    mock_scene_client.reload_scenes.assert_called()

    # Step 3: Test restore (undo)
    mock_scene_client.reset_mock()
    await pending.restore_fn()
    mock_scene_client.delete_scene.assert_called_once_with(hass, "evening")
    mock_scene_client.reload_scenes.assert_called()


@pytest.mark.asyncio
async def test_scene_with_unknown_entity_rejected(
    hass, mock_entry, mock_llm_context, mock_scene_client
):
    """Scene with unknown entity should fail validation."""

    tool = ConfigSceneCreate()
    tool_input = llm.ToolInput(
        tool_name="ConfigSceneCreate",
        tool_args={
            "object_id": "test_scene",
            "config": {
                "name": "Test Scene",
                "entities": {"light.notreal": "on"},
            },
        },
    )

    result = await tool.async_call(hass, tool_input, mock_llm_context)
    assert result["status"] == "validation_failed"
    assert any(e["code"] == "unknown_entity" for e in result["errors"])
    assert "light.notreal" in str(result["errors"])


@pytest.mark.asyncio
async def test_scene_edit_diff_shows_entity_state_change(
    hass, mock_entry, mock_llm_context, mock_scene_client
):
    """Scene edit should show entity state changes in diff."""

    # Mock entity registry
    from homeassistant.helpers import entity_registry as er

    reg = er.async_get(hass)
    reg.async_get_or_create("light", "test", "bedroom", suggested_object_id="bedroom")

    # Mock existing scene
    existing = {
        "name": "Bedtime",
        "entities": {"light.bedroom": "off"},
    }
    mock_scene_client.get_scene.return_value = existing

    tool = ConfigSceneEdit()
    tool_input = llm.ToolInput(
        tool_name="ConfigSceneEdit",
        tool_args={
            "object_id": "bedtime",
            "config": {
                "name": "Bedtime",
                "entities": {"light.bedroom": {"state": "on", "brightness": 50}},
            },
        },
    )

    result = await tool.async_call(hass, tool_input, mock_llm_context)
    assert result["status"] == "pending_approval"
    assert "Would update" in result["proposed_summary"]
    # Diff should show the entity state change
    diff = result["proposed_diff"]
    assert "light.bedroom" in diff
    assert "-" in diff  # removal line
    assert "+" in diff  # addition line


@pytest.mark.asyncio
async def test_scene_delete_unknown_object_id(
    hass, mock_entry, mock_llm_context, mock_scene_client
):
    """Delete non-existent scene should fail validation."""

    # Scene doesn't exist
    mock_scene_client.get_scene.return_value = None

    tool = ConfigSceneDelete()
    tool_input = llm.ToolInput(
        tool_name="ConfigSceneDelete",
        tool_args={
            "object_id": "nonexistent",
        },
    )

    result = await tool.async_call(hass, tool_input, mock_llm_context)
    assert result["status"] == "validation_failed"
    assert any(e["code"] == "unknown_scene" for e in result["errors"])


@pytest.mark.asyncio
async def test_get_tools_returns_three_instances(hass, mock_entry):
    """get_tools should return three scene tool instances."""
    tools = get_tools(hass, mock_entry)
    assert len(tools) == 3
    assert isinstance(tools[0], ConfigSceneCreate)
    assert isinstance(tools[1], ConfigSceneEdit)
    assert isinstance(tools[2], ConfigSceneDelete)
    assert tools[0].name == "ConfigSceneCreate"
    assert tools[1].name == "ConfigSceneEdit"
    assert tools[2].name == "ConfigSceneDelete"
