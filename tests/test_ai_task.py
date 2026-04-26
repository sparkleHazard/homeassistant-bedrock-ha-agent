"""Tests for AI Task entity (v1.4.0)."""
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components import ai_task
from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers.restore_state import RestoreEntity

from custom_components.bedrock_ha_agent.ai_task import BedrockAITaskEntity
from custom_components.bedrock_ha_agent.config_flow import BedrockConversationConfigFlow
from custom_components.bedrock_ha_agent.const import DOMAIN

pytest_plugins = ["pytest_homeassistant_custom_component"]


# ============================================================
# Priority tests (all must pass deterministically)
# ============================================================


def test_ai_task_entity_feature_flags():
    """Verify BedrockAITaskEntity declares GENERATE_DATA | SUPPORT_ATTACHMENTS.

    Assert that GENERATE_IMAGE is NOT set (intentionally excluded since
    Bedrock Claude doesn't image-generate).
    """
    # Instantiate an entity to access the feature flags
    entry = MagicMock()
    entry.entry_id = "test_id"
    subentry = SimpleNamespace(subentry_id="sub_id")

    entity = BedrockAITaskEntity(entry, subentry)
    supported = entity.supported_features

    # Check both bits are set
    assert (supported & ai_task.AITaskEntityFeature.GENERATE_DATA) != 0, (
        "GENERATE_DATA feature flag missing"
    )
    assert (supported & ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS) != 0, (
        "SUPPORT_ATTACHMENTS feature flag missing"
    )

    # Verify the value equals the bitwise OR
    expected = (
        ai_task.AITaskEntityFeature.GENERATE_DATA
        | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
    )
    assert supported == expected, (
        f"Expected {expected} (GENERATE_DATA | SUPPORT_ATTACHMENTS), got {supported}"
    )

    # Guard: GENERATE_IMAGE should NOT be set
    assert (supported & ai_task.AITaskEntityFeature.GENERATE_IMAGE) == 0, (
        "GENERATE_IMAGE should not be set (Bedrock Claude doesn't image-generate)"
    )


def test_ai_task_entity_inherits_correct_bases():
    """Verify BedrockAITaskEntity inherits AITaskEntity and RestoreEntity."""
    assert issubclass(BedrockAITaskEntity, ai_task.AITaskEntity), (
        "BedrockAITaskEntity must inherit from homeassistant.components.ai_task.AITaskEntity"
    )
    assert issubclass(BedrockAITaskEntity, RestoreEntity), (
        "BedrockAITaskEntity must inherit from RestoreEntity"
    )


def test_ai_task_unique_id_scoped_to_entry_plus_subentry():
    """Verify unique_id format: {entry_id}_{subentry_id}_ai_task.

    This locks in the multi-subentry naming invariant.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={},
        entry_id="test_entry_abc123",
    )

    subentry = SimpleNamespace(subentry_id="sub_xyz789")

    entity = BedrockAITaskEntity(entry, subentry)

    expected_unique_id = "test_entry_abc123_sub_xyz789_ai_task"
    assert entity.unique_id == expected_unique_id, (
        f"Expected unique_id '{expected_unique_id}', got '{entity.unique_id}'"
    )


async def test_subentry_auto_created_on_setup(hass):
    """Verify _async_ensure_ai_task_subentry creates exactly one subentry.

    Re-calling the function is a no-op (idempotent).
    """
    from custom_components.bedrock_ha_agent import _async_ensure_ai_task_subentry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={},
        entry_id="test_idempotent_setup",
    )
    entry.add_to_hass(hass)

    # Precondition: no subentries
    assert len(entry.subentries) == 0, "Entry should start with no subentries"

    # First call: creates the subentry
    await _async_ensure_ai_task_subentry(hass, entry)

    assert len(entry.subentries) == 1, "Expected exactly one subentry after first call"
    subentry_list = list(entry.subentries.values())
    assert subentry_list[0].subentry_type == "ai_task_data", (
        "Subentry should have type 'ai_task_data'"
    )

    # Second call: no-op (idempotent)
    await _async_ensure_ai_task_subentry(hass, entry)

    assert len(entry.subentries) == 1, (
        "Expected still exactly one subentry after second call (idempotent)"
    )
    assert subentry_list[0].subentry_type == "ai_task_data", (
        "Subentry type should remain 'ai_task_data'"
    )


async def test_platform_setup_adds_entity_per_subentry(hass):
    """Verify async_setup_entry filters by subentry_type and adds entities.

    Seed the entry with TWO subentries: one of type 'ai_task_data', one
    of an unrelated type. Assert ONLY the ai_task subentry produces an entity.
    """
    from custom_components.bedrock_ha_agent.ai_task import async_setup_entry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={},
        entry_id="test_platform_filter",
    )
    entry.add_to_hass(hass)

    # Manually add two subentries: one matching, one not
    ai_task_subentry = ConfigSubentry(
        data={},
        subentry_type="ai_task_data",
        title="AI Task",
        unique_id=None,
    )
    other_subentry = ConfigSubentry(
        data={},
        subentry_type="some_other_type",
        title="Other",
        unique_id=None,
    )

    hass.config_entries.async_add_subentry(entry, ai_task_subentry)
    hass.config_entries.async_add_subentry(entry, other_subentry)

    assert len(entry.subentries) == 2, "Entry should have two subentries"

    # Mock async_add_entities to capture calls
    mock_add = MagicMock()

    await async_setup_entry(hass, entry, mock_add)

    # Assert async_add_entities was called exactly once
    assert mock_add.call_count == 1, (
        f"Expected async_add_entities called once, got {mock_add.call_count}"
    )

    # Inspect the call: first positional arg is the entity list
    call_args = mock_add.call_args
    entities = call_args[0][0]

    assert len(entities) == 1, "Expected exactly one entity added"
    assert isinstance(entities[0], BedrockAITaskEntity), (
        "Entity should be a BedrockAITaskEntity"
    )

    # Verify config_subentry_id keyword arg was passed
    kwargs = call_args[1]
    assert "config_subentry_id" in kwargs, (
        "Expected config_subentry_id keyword argument"
    )
    assert kwargs["config_subentry_id"] == ai_task_subentry.subentry_id, (
        "config_subentry_id should match the ai_task subentry"
    )


async def test_config_flow_exposes_ai_task_subentry_type(hass):
    """Verify async_get_supported_subentry_types returns ai_task_data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={},
        entry_id="test_config_flow_subentry",
    )
    entry.add_to_hass(hass)

    supported = BedrockConversationConfigFlow.async_get_supported_subentry_types(entry)

    assert "ai_task_data" in supported, (
        "Expected 'ai_task_data' in supported subentry types"
    )

    # Verify the value is a ConfigSubentryFlow subclass
    from homeassistant.config_entries import ConfigSubentryFlow
    flow_class = supported["ai_task_data"]
    assert issubclass(flow_class, ConfigSubentryFlow), (
        "ai_task_data should map to a ConfigSubentryFlow subclass"
    )


async def test_platform_registered_in_PLATFORMS(hass):
    """Verify Platform.AI_TASK is in the PLATFORMS list."""
    from homeassistant.const import Platform
    from custom_components.bedrock_ha_agent import PLATFORMS

    assert Platform.AI_TASK in PLATFORMS, (
        "Platform.AI_TASK must be in PLATFORMS to register the platform"
    )


# ============================================================
# Skippable tests (infrastructure-heavy, require real runtime)
# ============================================================


@pytest.mark.skip(
    reason=(
        "Infrastructure-heavy: requires real Bedrock client, chat_log, and turn loop. "
        "Next uplift: mock the Bedrock client and chat_log.async_add_delta_content_stream "
        "to drive _async_generate_data with synthetic responses."
    )
)
async def test_generate_data_returns_plaintext_result(hass):
    """Drive _async_generate_data with mocked Bedrock yielding plaintext.

    Assert the GenDataTaskResult.data == "hello world" and
    conversation_id == chat_log.conversation_id.
    """
    # Placeholder for future implementation when we have mock infrastructure.
    pass


@pytest.mark.skip(
    reason=(
        "Infrastructure-heavy: requires mocking task.structure (vol.Schema), "
        "chat_log, and Bedrock client. Next uplift: add fixture for structured tasks."
    )
)
async def test_generate_data_parses_structured_json(hass):
    """Drive _async_generate_data with task.structure and JSON response.

    Assert GenDataTaskResult.data == {"foo": 42}.
    """
    # Placeholder for future implementation.
    pass


@pytest.mark.skip(
    reason=(
        "Infrastructure-heavy: requires task.structure non-None and invalid JSON. "
        "Next uplift: add fixture for structured tasks and mock Bedrock with bad JSON."
    )
)
async def test_generate_data_raises_on_bad_json(hass):
    """Verify _async_generate_data raises HomeAssistantError on invalid JSON.

    When task.structure is non-None and Bedrock returns invalid JSON, the
    method should raise HomeAssistantError.
    """
    # Placeholder for future implementation.
    pass
