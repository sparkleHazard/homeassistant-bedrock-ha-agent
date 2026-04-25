"""Tests for registry config-editing tools."""
import pytest
from homeassistant.helpers import llm

pytest_plugins = ["pytest_homeassistant_custom_component"]

from custom_components.bedrock_conversation.config_tools.registry import (
    ConfigAreaCreate,
    ConfigAreaRename,
    ConfigAreaDelete,
    ConfigLabelCreate,
    ConfigLabelRename,
    ConfigLabelDelete,
    ConfigEntityRename,
    ConfigEntityAssignArea,
    get_tools,
)
from custom_components.bedrock_conversation.runtime_data import BedrockRuntimeData
from custom_components.bedrock_conversation.const import DOMAIN


@pytest.fixture
async def mock_entry(hass):
    """Create a mock config entry with runtime_data."""
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={"enable_config_editing": True},
        entry_id="test_entry_id",
        state=ConfigEntryState.LOADED,
    )
    entry.runtime_data = BedrockRuntimeData()
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def llm_context(mock_entry):
    """Create a mock LLM context."""
    from unittest.mock import MagicMock
    context = MagicMock(spec=llm.LLMContext)
    context.device_id = None
    return context


# --- Area Tests ---


@pytest.mark.asyncio
async def test_area_create_golden_path(hass, mock_entry, llm_context):
    """AC1: Create area — pending approval, apply creates the area, restore deletes it."""
    from homeassistant.helpers import area_registry as ar

    tool = ConfigAreaCreate()
    tool_input = llm.ToolInput(
        tool_name="ConfigAreaCreate",
        tool_args={"name": "Test Area"},
    )

    result = await tool.async_call(hass, tool_input, llm_context)

    # Should return pending_approval
    assert result["status"] == "pending_approval"
    assert "proposed_summary" in result
    assert "Would add" in result["proposed_summary"]
    assert "Test Area" in result["proposed_summary"]
    assert "proposal_id" in result

    # Should have stored a PendingChange
    pending = mock_entry.runtime_data.pending.get("_global")
    assert pending is not None
    assert pending.tool_name == "ConfigAreaCreate"

    # Now simulate approval by calling apply_fn
    apply_result = await pending.apply_fn(hass, pending.proposed_payload, pending.pre_state)

    # Check that area was created
    registry = ar.async_get(hass)
    areas = list(registry.async_list_areas())
    created_area = next((a for a in areas if a.name == "Test Area"), None)
    assert created_area is not None
    assert apply_result["area_id"] == created_area.id

    # Now test restore_fn (undo)
    await pending.restore_fn()

    # Area should be deleted
    areas = list(registry.async_list_areas())
    deleted_area = next((a for a in areas if a.name == "Test Area"), None)
    assert deleted_area is None


@pytest.mark.asyncio
async def test_area_rename_golden_path(hass, mock_entry, llm_context):
    """AC9: Area rename — changes name, undo restores old name."""
    from homeassistant.helpers import area_registry as ar

    # Create an area first
    registry = ar.async_get(hass)
    area = registry.async_create("Old Name")
    area_id = area.id

    tool = ConfigAreaRename()
    tool_input = llm.ToolInput(
        tool_name="ConfigAreaRename",
        tool_args={"area_id": area_id, "new_name": "New Name"},
    )

    result = await tool.async_call(hass, tool_input, llm_context)

    assert result["status"] == "pending_approval"
    assert "Would rename" in result["proposed_summary"]
    assert "Old Name" in result["proposed_summary"]
    assert "New Name" in result["proposed_summary"]

    # Apply the change
    pending = mock_entry.runtime_data.pending.get("_global")
    await pending.apply_fn(hass, pending.proposed_payload, pending.pre_state)

    # Check that area was renamed
    updated_area = registry.async_get_area(area_id)
    assert updated_area.name == "New Name"

    # Test restore_fn (undo)
    await pending.restore_fn()

    # Should be back to old name
    restored_area = registry.async_get_area(area_id)
    assert restored_area.name == "Old Name"


@pytest.mark.asyncio
async def test_area_delete_emits_id_regen_warning(hass, mock_entry, llm_context):
    """Area delete emits the id-regen caveat."""
    from homeassistant.helpers import area_registry as ar

    # Create an area
    registry = ar.async_get(hass)
    area = registry.async_create("Doomed Area")

    tool = ConfigAreaDelete()
    tool_input = llm.ToolInput(
        tool_name="ConfigAreaDelete",
        tool_args={"area_id": area.id},
    )

    result = await tool.async_call(hass, tool_input, llm_context)

    assert result["status"] == "pending_approval"
    assert "Would delete" in result["proposed_summary"]

    # Check warnings
    pending = mock_entry.runtime_data.pending.get("_global")
    assert len(pending.warnings) > 0
    warning_text = " ".join(pending.warnings)
    assert "new area_id" in warning_text or "re-create" in warning_text


@pytest.mark.asyncio
async def test_area_delete_undo_recreates_area(hass, mock_entry, llm_context):
    """Area delete undo recreates the area (HA generates deterministic IDs from names)."""
    from homeassistant.helpers import area_registry as ar

    # Create an area
    registry = ar.async_get(hass)
    area = registry.async_create("Area to Delete")
    original_area_id = area.id

    tool = ConfigAreaDelete()
    tool_input = llm.ToolInput(
        tool_name="ConfigAreaDelete",
        tool_args={"area_id": original_area_id},
    )

    result = await tool.async_call(hass, tool_input, llm_context)
    pending = mock_entry.runtime_data.pending.get("_global")

    # Apply delete
    await pending.apply_fn(hass, pending.proposed_payload, pending.pre_state)

    # Area should be gone
    areas = list(registry.async_list_areas())
    assert not any(a.id == original_area_id for a in areas)

    # Restore (undo)
    await pending.restore_fn()

    # Area should exist again with the same name
    # Note: HA generates deterministic IDs from area names, so same name = same ID
    # The warning is still valid for areas with entity references
    areas = list(registry.async_list_areas())
    restored_area = next((a for a in areas if a.name == "Area to Delete"), None)
    assert restored_area is not None


@pytest.mark.asyncio
async def test_area_create_validation_duplicate_name(hass, mock_entry, llm_context):
    """Area create validation fails for duplicate names."""
    from homeassistant.helpers import area_registry as ar

    # Create an existing area
    registry = ar.async_get(hass)
    registry.async_create("Existing Area")

    tool = ConfigAreaCreate()
    tool_input = llm.ToolInput(
        tool_name="ConfigAreaCreate",
        tool_args={"name": "Existing Area"},
    )

    result = await tool.async_call(hass, tool_input, llm_context)

    assert result["status"] == "validation_failed"
    assert "errors" in result
    assert any("duplicate" in str(e).lower() for e in result["errors"])


# --- Label Tests ---


@pytest.mark.asyncio
async def test_label_create_golden_path(hass, mock_entry, llm_context):
    """Label create — pending approval, apply creates the label, restore deletes it."""
    from homeassistant.helpers import label_registry as lr

    tool = ConfigLabelCreate()
    tool_input = llm.ToolInput(
        tool_name="ConfigLabelCreate",
        tool_args={"name": "Test Label"},
    )

    result = await tool.async_call(hass, tool_input, llm_context)

    assert result["status"] == "pending_approval"
    assert "Would add" in result["proposed_summary"]
    assert "Test Label" in result["proposed_summary"]

    pending = mock_entry.runtime_data.pending.get("_global")
    apply_result = await pending.apply_fn(hass, pending.proposed_payload, pending.pre_state)

    # Check that label was created
    registry = lr.async_get(hass)
    labels = list(registry.async_list_labels())
    created_label = next((lbl for lbl in labels if lbl.name == "Test Label"), None)
    assert created_label is not None
    assert apply_result["label_id"] == created_label.label_id

    # Test restore_fn (undo)
    await pending.restore_fn()

    # Label should be deleted
    labels = list(registry.async_list_labels())
    deleted_label = next((lbl for lbl in labels if lbl.name == "Test Label"), None)
    assert deleted_label is None


@pytest.mark.asyncio
async def test_label_rename_golden_path(hass, mock_entry, llm_context):
    """Label rename — changes name, undo restores old name."""
    from homeassistant.helpers import label_registry as lr

    # Create a label first
    registry = lr.async_get(hass)
    label = registry.async_create("Old Label")
    label_id = label.label_id

    tool = ConfigLabelRename()
    tool_input = llm.ToolInput(
        tool_name="ConfigLabelRename",
        tool_args={"label_id": label_id, "new_name": "New Label"},
    )

    result = await tool.async_call(hass, tool_input, llm_context)

    assert result["status"] == "pending_approval"
    assert "Would rename" in result["proposed_summary"]

    pending = mock_entry.runtime_data.pending.get("_global")
    await pending.apply_fn(hass, pending.proposed_payload, pending.pre_state)

    # Check that label was renamed
    updated_label = registry.async_get_label(label_id)
    assert updated_label.name == "New Label"

    # Test restore_fn (undo)
    await pending.restore_fn()

    # Should be back to old name
    restored_label = registry.async_get_label(label_id)
    assert restored_label.name == "Old Label"


@pytest.mark.asyncio
async def test_label_delete_warning_mentions_reference_relinking(hass, mock_entry, llm_context):
    """Label delete emits the harsher caveat about manual relinking."""
    from homeassistant.helpers import label_registry as lr

    # Create a label
    registry = lr.async_get(hass)
    label = registry.async_create("Label to Delete")

    tool = ConfigLabelDelete()
    tool_input = llm.ToolInput(
        tool_name="ConfigLabelDelete",
        tool_args={"label_id": label.label_id},
    )

    result = await tool.async_call(hass, tool_input, llm_context)

    assert result["status"] == "pending_approval"

    # Check warnings mention manual relinking
    pending = mock_entry.runtime_data.pending.get("_global")
    assert len(pending.warnings) > 0
    warning_text = " ".join(pending.warnings)
    assert "manually" in warning_text.lower() or "re-link" in warning_text.lower()


# --- Entity Registry Tests ---


@pytest.mark.asyncio
async def test_entity_rename_golden_path(hass, mock_entry, llm_context):
    """Entity rename — changes display name, undo restores old name."""
    from homeassistant.helpers import entity_registry as er

    # Register an entity
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "light",
        "test",
        "1234",
        suggested_object_id="bedroom",
    )
    registry.async_update_entity(entry.entity_id, name="Old Name")

    tool = ConfigEntityRename()
    tool_input = llm.ToolInput(
        tool_name="ConfigEntityRename",
        tool_args={"entity_id": entry.entity_id, "new_name": "New Name"},
    )

    result = await tool.async_call(hass, tool_input, llm_context)

    assert result["status"] == "pending_approval"
    assert "Would rename" in result["proposed_summary"]

    pending = mock_entry.runtime_data.pending.get("_global")
    await pending.apply_fn(hass, pending.proposed_payload, pending.pre_state)

    # Check that entity was renamed
    updated_entry = registry.async_get(entry.entity_id)
    assert updated_entry.name == "New Name"

    # Test restore_fn (undo)
    await pending.restore_fn()

    # Should be back to old name
    restored_entry = registry.async_get(entry.entity_id)
    assert restored_entry.name == "Old Name"


@pytest.mark.asyncio
async def test_entity_assign_area_golden_path(hass, mock_entry, llm_context):
    """Entity assign area — sets area_id, undo restores previous area_id."""
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import entity_registry as er

    # Create an area
    area_registry = ar.async_get(hass)
    area = area_registry.async_create("Bedroom")

    # Register an entity
    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get_or_create(
        "light",
        "test",
        "5678",
        suggested_object_id="lamp",
    )

    tool = ConfigEntityAssignArea()
    tool_input = llm.ToolInput(
        tool_name="ConfigEntityAssignArea",
        tool_args={"entity_id": entry.entity_id, "area_id": area.id},
    )

    result = await tool.async_call(hass, tool_input, llm_context)

    assert result["status"] == "pending_approval"
    assert "Would assign" in result["proposed_summary"]

    pending = mock_entry.runtime_data.pending.get("_global")
    await pending.apply_fn(hass, pending.proposed_payload, pending.pre_state)

    # Check that entity was assigned to area
    updated_entry = entity_registry.async_get(entry.entity_id)
    assert updated_entry.area_id == area.id

    # Test restore_fn (undo)
    await pending.restore_fn()

    # Should be back to no area
    restored_entry = entity_registry.async_get(entry.entity_id)
    assert restored_entry.area_id is None


@pytest.mark.asyncio
async def test_entity_assign_area_validation_unknown_area(hass, mock_entry, llm_context):
    """Entity assign area validation fails for unknown area_id."""
    from homeassistant.helpers import entity_registry as er

    # Register an entity
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "light",
        "test",
        "9999",
        suggested_object_id="test",
    )

    tool = ConfigEntityAssignArea()
    tool_input = llm.ToolInput(
        tool_name="ConfigEntityAssignArea",
        tool_args={"entity_id": entry.entity_id, "area_id": "nonexistent_area"},
    )

    result = await tool.async_call(hass, tool_input, llm_context)

    assert result["status"] == "validation_failed"
    assert "errors" in result
    assert any("unknown_area" in str(e).lower() for e in result["errors"])


@pytest.mark.asyncio
async def test_get_tools_returns_expected_count(hass, mock_entry):
    """get_tools returns 8 tool instances."""
    tools = get_tools(hass, mock_entry)

    assert len(tools) == 8
    names = {tool.name for tool in tools}
    assert names == {
        "ConfigAreaCreate",
        "ConfigAreaRename",
        "ConfigAreaDelete",
        "ConfigLabelCreate",
        "ConfigLabelRename",
        "ConfigLabelDelete",
        "ConfigEntityRename",
        "ConfigEntityAssignArea",
    }
