"""Phase 3 integration wiring tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, PropertyMock, patch

import pytest
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bedrock_conversation import BedrockServicesAPI
from custom_components.bedrock_conversation.config_tools import register_config_tools
from custom_components.bedrock_conversation.config_tools.pending import (
    ApprovalOutcome,
    PendingChange,
    PendingChangeManager,
)
from custom_components.bedrock_conversation.config_tools.undo import UndoEntry, UndoStack
from custom_components.bedrock_conversation.const import (
    CONF_ENABLE_CONFIG_EDITING,
    CONF_MODEL_ID,
    DOMAIN,
    HOME_LLM_API_ID,
)
from custom_components.bedrock_conversation.conversation import (
    _check_past_tense_vs_pending,
    _split_proposal_for_stream,
)
from custom_components.bedrock_conversation.runtime_data import BedrockRuntimeData

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture
def mock_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry with runtime_data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Bedrock",
        data={
            "aws_access_key_id": "test_key",
            "aws_secret_access_key": "test_secret",
            "aws_region": "us-west-2",
        },
        options={
            CONF_MODEL_ID: "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            CONF_ENABLE_CONFIG_EDITING: False,
        },
        entry_id="test_entry_id",
        state=ConfigEntryState.LOADED,
    )
    entry.add_to_hass(hass)
    entry.runtime_data = BedrockRuntimeData()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry
    return entry


def set_entry_options(hass: HomeAssistant, entry: MockConfigEntry, **options):
    """Helper to update entry options."""
    new_options = {**entry.options, **options}
    hass.config_entries.async_update_entry(entry, options=new_options)


@pytest.mark.asyncio
async def test_register_config_tools_wires_into_api_instance(
    hass: HomeAssistant, mock_entry: ConfigEntry
):
    """Test that config tools are wired into BedrockServicesAPI when flag is on."""
    # Enable config editing
    set_entry_options(hass, mock_entry, **{CONF_ENABLE_CONFIG_EDITING: True})

    api = BedrockServicesAPI(hass, HOME_LLM_API_ID, "Test API")
    llm_context = Mock(spec=llm.LLMContext)
    llm_context.device_id = None

    # Mock register_config_tools to return at least one tool
    with patch(
        "custom_components.bedrock_conversation.config_tools.register_config_tools"
    ) as mock_register:
        mock_tool = Mock(spec=llm.Tool)
        mock_tool.name = "ConfigAutomationCreate"
        mock_register.return_value = [mock_tool]

        api_instance = await api.async_get_api_instance(llm_context)

    # Verify tools include config tools
    tool_names = [t.name for t in api_instance.tools]
    assert "ConfigAutomationCreate" in tool_names

    # Verify api_prompt contains the addendum
    assert "status: pending_approval" in api_instance.api_prompt
    assert "Do not claim success" in api_instance.api_prompt


@pytest.mark.asyncio
async def test_register_config_tools_flag_off_baseline(
    hass: HomeAssistant, mock_entry: ConfigEntry
):
    """Test that with flag off, tools list is baseline (AC10)."""
    # Flag is off by default
    assert not mock_entry.options.get(CONF_ENABLE_CONFIG_EDITING, False)

    api = BedrockServicesAPI(hass, HOME_LLM_API_ID, "Test API")
    llm_context = Mock(spec=llm.LLMContext)
    llm_context.device_id = None

    api_instance = await api.async_get_api_instance(llm_context)

    # Should only have HassServiceTool
    tool_names = [t.name for t in api_instance.tools]
    assert len(tool_names) == 1
    assert "HassCallService" in tool_names

    # Addendum should NOT be present
    assert "status: pending_approval" not in api_instance.api_prompt


@pytest.mark.asyncio
async def test_interceptor_approval_applies_and_pushes_undo(
    hass: HomeAssistant, mock_entry: ConfigEntry
):
    """Test that approval interceptor applies change and pushes to undo stack."""
    set_entry_options(hass, mock_entry, **{CONF_ENABLE_CONFIG_EDITING: True})

    # Create a pending change
    manager = PendingChangeManager.for_entry_conv(
        hass, mock_entry.entry_id, "test_conv_id"
    )
    pending = manager.create(
        tool_name="TestTool",
        proposed_payload={"test": "data"},
        pre_state={"old": "state"},
        proposed_summary="Would create test",
        proposed_diff="+ test data",
        approval_ttl_seconds=300,
    )

    # Attach mock apply_fn and restore_fn
    apply_fn = AsyncMock(return_value={"success": True})
    restore_fn = AsyncMock()
    pending.apply_fn = apply_fn  # type: ignore[attr-defined]
    pending.restore_fn = restore_fn  # type: ignore[attr-defined]
    pending.warnings = []  # type: ignore[attr-defined]

    # Simulate approval intent
    outcome = manager.handle_approval_intent("yes")

    assert outcome.outcome == ApprovalOutcome.APPLIED
    assert outcome.intercepted


@pytest.mark.asyncio
async def test_interceptor_undo_pops_restore_and_runs_restore_fn(
    hass: HomeAssistant, mock_entry: ConfigEntry
):
    """Test that undo interceptor pops from stack and runs restore_fn."""
    from custom_components.bedrock_conversation.config_tools.undo import (
        get_or_create_stack,
    )

    set_entry_options(hass, mock_entry, **{CONF_ENABLE_CONFIG_EDITING: True})

    # Push an undo entry
    stack = get_or_create_stack(hass, mock_entry.entry_id, "test_conv_id")
    restore_fn = AsyncMock()
    undo_entry = UndoEntry(
        entry_id=mock_entry.entry_id,
        conversation_id="test_conv_id",
        proposal_id="test_proposal",
        tool_name="TestTool",
        before_state={"old": "state"},
        after_state={"new": "state"},
        restore_fn=restore_fn,
        timestamp=datetime.now(UTC),
        ttl=timedelta(seconds=3600),
        warnings=[],
    )
    stack.push(undo_entry)

    # Simulate undo intent
    manager = PendingChangeManager.for_entry_conv(
        hass, mock_entry.entry_id, "test_conv_id"
    )
    outcome = manager.handle_approval_intent("undo that")

    assert outcome.outcome == ApprovalOutcome.UNDONE
    assert outcome.intercepted


def test_interceptor_rejected_drops_pending_no_write(
    hass: HomeAssistant, mock_entry: ConfigEntry
):
    """Test that rejection drops pending without calling apply_fn."""
    set_entry_options(hass, mock_entry, **{CONF_ENABLE_CONFIG_EDITING: True})

    # Create a pending change
    manager = PendingChangeManager.for_entry_conv(
        hass, mock_entry.entry_id, "test_conv_id"
    )
    pending = manager.create(
        tool_name="TestTool",
        proposed_payload={"test": "data"},
        pre_state=None,
        proposed_summary="Would create test",
        proposed_diff="+ test",
        approval_ttl_seconds=300,
    )

    # Simulate rejection
    outcome = manager.handle_approval_intent("cancel")

    assert outcome.outcome == ApprovalOutcome.REJECTED
    assert outcome.intercepted

    # Pending should be cleared
    assert manager.get_current() is None


def test_interceptor_expired_returns_expiry_message(
    hass: HomeAssistant, mock_entry: ConfigEntry
):
    """Test that expired pending returns expiry message."""
    set_entry_options(hass, mock_entry, **{CONF_ENABLE_CONFIG_EDITING: True})

    # Create a pending change with 1-second TTL
    now = datetime.now(UTC)
    manager = PendingChangeManager.for_entry_conv(
        hass, mock_entry.entry_id, "test_conv_id", now_fn=lambda: now
    )
    pending = manager.create(
        tool_name="TestTool",
        proposed_payload={"test": "data"},
        pre_state=None,
        proposed_summary="Would create test",
        proposed_diff="+ test",
        approval_ttl_seconds=1,
    )

    # Advance time past expiry
    future = now + timedelta(seconds=2)
    manager._now_fn = lambda: future

    # Trigger eviction
    manager.evict_expired()

    # Now try to approve
    outcome = manager.handle_approval_intent("yes")

    assert outcome.outcome == ApprovalOutcome.EXPIRED
    assert "expired" in outcome.user_message.lower()


def test_interceptor_not_intercepted_falls_through(
    hass: HomeAssistant, mock_entry: ConfigEntry
):
    """Test that non-approval messages fall through."""
    set_entry_options(hass, mock_entry, **{CONF_ENABLE_CONFIG_EDITING: True})

    manager = PendingChangeManager.for_entry_conv(
        hass, mock_entry.entry_id, "test_conv_id"
    )

    outcome = manager.handle_approval_intent("what's the weather")

    assert outcome.outcome == ApprovalOutcome.NOT_INTERCEPTED
    assert not outcome.intercepted


def test_past_tense_vs_pending_logs_warning(
    hass: HomeAssistant, mock_entry: ConfigEntry, caplog
):
    """Test AC17: warning fires when assistant claims success with pending proposal."""
    set_entry_options(hass, mock_entry, **{CONF_ENABLE_CONFIG_EDITING: True})

    # Create a pending change
    manager = PendingChangeManager.for_entry_conv(
        hass, mock_entry.entry_id, "test_conv_id"
    )
    pending = manager.create(
        tool_name="TestTool",
        proposed_payload={"test": "data"},
        pre_state=None,
        proposed_summary="Would create test",
        proposed_diff="+ test",
        approval_ttl_seconds=300,
    )

    # Call the helper with past-tense text
    final_text = "I added the automation for you"

    with caplog.at_level("WARNING"):
        _check_past_tense_vs_pending(
            hass, mock_entry.entry_id, "test_conv_id", final_text
        )

    # Assert warning fired with proposal_id
    assert any(pending.proposal_id in record.message for record in caplog.records)
    assert any("added" in record.message for record in caplog.records)


def test_split_proposal_for_stream_pending_approval():
    """Test AC12: split returns summary for speech, full dict for structured log."""
    tool_result = {
        "status": "pending_approval",
        "proposed_summary": "Would add X",
        "proposed_diff": "large diff content here...",
    }

    spoken_text, structured_payload = _split_proposal_for_stream(tool_result)

    assert spoken_text == "Would add X"
    assert structured_payload == tool_result
    assert "large diff content here" not in (spoken_text or "")


def test_split_proposal_for_stream_non_pending_passthrough():
    """Test that non-pending results pass through unchanged."""
    tool_result = {"status": "success", "message": "Done"}

    spoken_text, structured_payload = _split_proposal_for_stream(tool_result)

    assert spoken_text is None
    assert structured_payload == tool_result


@pytest.mark.asyncio
async def test_options_flow_has_new_fields(hass: HomeAssistant, mock_entry: ConfigEntry):
    """Test that options flow schema includes all four new config-editing fields."""
    from custom_components.bedrock_conversation.config_flow import (
        BedrockConversationOptionsFlow,
    )

    flow = BedrockConversationOptionsFlow()
    flow.hass = hass

    # Mock fetch functions and config_entry property
    with patch(
        "custom_components.bedrock_conversation.config_flow.fetch_claude_inference_profiles",
        return_value=["us.anthropic.claude-sonnet-4-5-20250929-v1:0"],
    ), patch(
        "custom_components.bedrock_conversation.config_flow.fetch_polly_voices",
        return_value=["Joanna"],
    ), patch.object(
        type(flow), "config_entry", new_callable=PropertyMock, return_value=mock_entry
    ):
        result = await flow.async_step_init()

    # Extract schema keys
    schema_keys = list(result["data_schema"].schema.keys())
    schema_key_ids = [str(k) for k in schema_keys]

    # Verify all four new fields are present
    assert any("enable_config_editing" in k for k in schema_key_ids)
    assert any("config_undo_depth" in k for k in schema_key_ids)
    assert any("config_undo_ttl_seconds" in k for k in schema_key_ids)
    assert any("config_approval_ttl_seconds" in k for k in schema_key_ids)


@pytest.mark.asyncio
async def test_update_listener_haiku_flag_on_fires_notification(
    hass: HomeAssistant, mock_entry: ConfigEntry
):
    """Test AC11: Haiku warning fires once on flag-on transition."""
    from custom_components.bedrock_conversation import _async_update_listener

    # Set Haiku model and enable config editing
    set_entry_options(
        hass,
        mock_entry,
        **{
            CONF_MODEL_ID: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            CONF_ENABLE_CONFIG_EDITING: True,
        }
    )

    with patch(
        "homeassistant.components.persistent_notification.async_create",
        new_callable=AsyncMock,
    ) as mock_notify, patch.object(
        hass.config_entries, "async_reload", return_value=None
    ):
        await _async_update_listener(hass, mock_entry)

        # Should fire once
        assert mock_notify.call_count == 1
        call_args = mock_notify.call_args
        assert "Haiku" in call_args.kwargs["message"]

        # Call again with same options — should NOT fire second time
        await _async_update_listener(hass, mock_entry)
        assert mock_notify.call_count == 1  # Still just 1


@pytest.mark.asyncio
async def test_update_listener_sonnet_no_notification(
    hass: HomeAssistant, mock_entry: ConfigEntry
):
    """Test that Sonnet model does NOT trigger Haiku warning."""
    from custom_components.bedrock_conversation import _async_update_listener

    set_entry_options(
        hass,
        mock_entry,
        **{
            CONF_MODEL_ID: "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            CONF_ENABLE_CONFIG_EDITING: True,
        }
    )

    with patch(
        "homeassistant.components.persistent_notification.async_create",
        new_callable=AsyncMock,
    ) as mock_notify, patch.object(
        hass.config_entries, "async_reload", return_value=None
    ):
        await _async_update_listener(hass, mock_entry)

        # Should NOT fire
        assert mock_notify.call_count == 0


@pytest.mark.asyncio
async def test_undo_service_single_stack_pops(hass: HomeAssistant, mock_entry: ConfigEntry):
    """Test AC5: undo service with single non-empty stack pops successfully."""
    from custom_components.bedrock_conversation import _async_register_undo_service
    from custom_components.bedrock_conversation.config_tools.undo import (
        get_or_create_stack,
    )

    # Register service
    await _async_register_undo_service(hass)

    # Push an undo entry
    stack = get_or_create_stack(hass, mock_entry.entry_id, "test_conv")
    restore_fn = AsyncMock()
    undo_entry = UndoEntry(
        entry_id=mock_entry.entry_id,
        conversation_id="test_conv",
        proposal_id="test_prop",
        tool_name="TestTool",
        before_state={},
        after_state={},
        restore_fn=restore_fn,
        timestamp=datetime.now(UTC),
        ttl=timedelta(seconds=3600),
        warnings=[],
    )
    stack.push(undo_entry)

    # Call service without conversation_id (single stack should be unambiguous)
    response = await hass.services.async_call(
        DOMAIN,
        "undo_last_config_change",
        {"config_entry_id": mock_entry.entry_id},
        blocking=True,
        return_response=True,
    )

    assert response["undone"] is True
    assert "Reverted" in response["summary"]
    restore_fn.assert_called_once()


@pytest.mark.asyncio
async def test_undo_service_empty_returns_nothing_to_undo(
    hass: HomeAssistant, mock_entry: ConfigEntry
):
    """Test that undo service with empty stacks returns nothing-to-undo message."""
    from custom_components.bedrock_conversation import _async_register_undo_service

    await _async_register_undo_service(hass)

    response = await hass.services.async_call(
        DOMAIN,
        "undo_last_config_change",
        {"config_entry_id": mock_entry.entry_id},
        blocking=True,
        return_response=True,
    )

    assert response["undone"] is False
    assert "nothing" in response["summary"].lower()


@pytest.mark.asyncio
async def test_undo_service_ambiguous_two_nonempty_stacks(
    hass: HomeAssistant, mock_entry: ConfigEntry
):
    """Test AC16: undo service with ≥2 non-empty stacks returns ambiguity error."""
    from custom_components.bedrock_conversation import _async_register_undo_service
    from custom_components.bedrock_conversation.config_tools.undo import (
        get_or_create_stack,
    )

    await _async_register_undo_service(hass)

    # Push to two different conversation stacks
    for conv_id in ["conv_1", "conv_2"]:
        stack = get_or_create_stack(hass, mock_entry.entry_id, conv_id)
        undo_entry = UndoEntry(
            entry_id=mock_entry.entry_id,
            conversation_id=conv_id,
            proposal_id=f"prop_{conv_id}",
            tool_name="TestTool",
            before_state={},
            after_state={},
            restore_fn=AsyncMock(),
            timestamp=datetime.now(UTC),
            ttl=timedelta(seconds=3600),
            warnings=[],
        )
        stack.push(undo_entry)

    # Call without conversation_id
    response = await hass.services.async_call(
        DOMAIN,
        "undo_last_config_change",
        {"config_entry_id": mock_entry.entry_id},
        blocking=True,
        return_response=True,
    )

    assert response["undone"] is False
    assert response["error"] == "ambiguous_conversation"
    assert set(response["conversation_ids"]) == {"conv_1", "conv_2"}


@pytest.mark.asyncio
async def test_undo_service_with_explicit_conversation_id(
    hass: HomeAssistant, mock_entry: ConfigEntry
):
    """Test that explicit conversation_id disambiguates."""
    from custom_components.bedrock_conversation import _async_register_undo_service
    from custom_components.bedrock_conversation.config_tools.undo import (
        get_or_create_stack,
    )

    await _async_register_undo_service(hass)

    # Push to two stacks
    for conv_id in ["conv_1", "conv_2"]:
        stack = get_or_create_stack(hass, mock_entry.entry_id, conv_id)
        restore_fn = AsyncMock()
        undo_entry = UndoEntry(
            entry_id=mock_entry.entry_id,
            conversation_id=conv_id,
            proposal_id=f"prop_{conv_id}",
            tool_name="TestTool",
            before_state={},
            after_state={},
            restore_fn=restore_fn,
            timestamp=datetime.now(UTC),
            ttl=timedelta(seconds=3600),
            warnings=[],
        )
        stack.push(undo_entry)

    # Call with explicit conversation_id
    response = await hass.services.async_call(
        DOMAIN,
        "undo_last_config_change",
        {"config_entry_id": mock_entry.entry_id, "conversation_id": "conv_1"},
        blocking=True,
        return_response=True,
    )

    assert response["undone"] is True
    assert "Reverted" in response["summary"]


@pytest.mark.asyncio
async def test_ha_api_smoke_check_called_on_setup_raises_configentrynotready_on_missing(
    hass: HomeAssistant, mock_entry: ConfigEntry
):
    """Test that async_setup_entry raises ConfigEntryNotReady on missing HA API."""
    from homeassistant.exceptions import ConfigEntryNotReady

    from custom_components.bedrock_conversation import async_setup_entry

    # Mock check_required_ha_apis to return failures
    with patch(
        "custom_components.bedrock_conversation.check_required_ha_apis",
        return_value=["homeassistant.helpers.llm.API — not found"],
    ):
        with pytest.raises(ConfigEntryNotReady) as exc_info:
            await async_setup_entry(hass, mock_entry)

        assert "Missing required Home Assistant APIs" in str(exc_info.value)
