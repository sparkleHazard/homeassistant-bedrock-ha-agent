"""Integration tests for registry.py (requires hass fixture)."""
import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.bedrock_conversation.config_tools.ha_client import registry

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.mark.asyncio
async def test_create_area_then_list(hass):
    """Create an area, list areas, assert it's present."""
    area_id = await registry.create_area(hass, "Test Area")
    assert area_id is not None

    areas = await registry.list_areas(hass)
    area_ids = [a["area_id"] for a in areas]
    assert area_id in area_ids

    # Find the created area
    created_area = next(a for a in areas if a["area_id"] == area_id)
    assert created_area["name"] == "Test Area"


@pytest.mark.asyncio
async def test_update_area_rename(hass):
    """Rename an area, re-list, assert new name."""
    area_id = await registry.create_area(hass, "Original Name")

    await registry.update_area(hass, area_id, name="Updated Name")

    areas = await registry.list_areas(hass)
    updated_area = next(a for a in areas if a["area_id"] == area_id)
    assert updated_area["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_delete_area_removes_it(hass):
    """Delete an area and verify it's removed."""
    area_id = await registry.create_area(hass, "To Be Deleted")

    await registry.delete_area(hass, area_id)

    areas = await registry.list_areas(hass)
    area_ids = [a["area_id"] for a in areas]
    assert area_id not in area_ids


@pytest.mark.asyncio
async def test_create_label(hass):
    """Create a label and verify it appears in the list."""
    label_id = await registry.create_label(hass, "Test Label")
    assert label_id is not None

    labels = await registry.list_labels(hass)
    label_ids = [lbl["label_id"] for lbl in labels]
    assert label_id in label_ids


@pytest.mark.asyncio
async def test_delete_label(hass):
    """Delete a label and verify it's removed."""
    label_id = await registry.create_label(hass, "Delete Me")

    await registry.delete_label(hass, label_id)

    labels = await registry.list_labels(hass)
    label_ids = [lbl["label_id"] for lbl in labels]
    assert label_id not in label_ids


@pytest.mark.asyncio
async def test_get_entity_registry_entry_existing(hass):
    """Register an entity, then call get_entity_registry_entry, assert fields match."""
    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get_or_create(
        domain="sensor",
        platform="test",
        unique_id="test_sensor_123",
        suggested_object_id="test_sensor",
    )

    result = await registry.get_entity_registry_entry(hass, entry.entity_id)
    assert result is not None
    assert result["entity_id"] == entry.entity_id
    assert result["original_name"] == entry.original_name


@pytest.mark.asyncio
async def test_get_entity_registry_entry_missing_returns_none(hass):
    """Call get_entity_registry_entry for a non-existent entity."""
    result = await registry.get_entity_registry_entry(hass, "sensor.does_not_exist")
    assert result is None


@pytest.mark.asyncio
async def test_can_toggle_disabled_by_user_integration_origin_false(hass):
    """Create an entity with disabled_by=INTEGRATION, assert can_toggle returns False."""
    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get_or_create(
        domain="sensor",
        platform="test",
        unique_id="test_integration_disabled",
        suggested_object_id="test_integration_disabled",
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )

    allowed, reason = await registry.can_toggle_disabled_by_user(hass, entry.entity_id)
    assert not allowed
    assert "integration" in reason.lower()


@pytest.mark.asyncio
async def test_can_toggle_disabled_by_user_user_origin_true(hass):
    """Create with disabled_by=USER, assert can_toggle returns True."""
    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get_or_create(
        domain="sensor",
        platform="test",
        unique_id="test_user_disabled",
        suggested_object_id="test_user_disabled",
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    allowed, reason = await registry.can_toggle_disabled_by_user(hass, entry.entity_id)
    assert allowed
    assert reason is None


@pytest.mark.asyncio
async def test_can_toggle_disabled_by_user_not_disabled_true(hass):
    """Create an enabled entity, assert can_toggle returns True."""
    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get_or_create(
        domain="sensor",
        platform="test",
        unique_id="test_enabled",
        suggested_object_id="test_enabled",
    )

    allowed, reason = await registry.can_toggle_disabled_by_user(hass, entry.entity_id)
    assert allowed
    assert reason is None
