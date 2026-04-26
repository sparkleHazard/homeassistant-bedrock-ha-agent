"""Tests for the conversation-entity entity_id migration (v1.3.1)."""
from __future__ import annotations

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bedrock_ha_agent import _async_migrate_conversation_entity_id
from custom_components.bedrock_ha_agent.const import DOMAIN

pytest_plugins = ["pytest_homeassistant_custom_component"]


def _make_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="01kq3camwwtc8g76mp5kzy5apz",  # ULID-shaped entry id
        data={},
        options={},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.mark.asyncio
async def test_migration_renames_ulid_suffixed_entity(hass):
    """Pre-v1.3.1 conversation.bedrock_ha_agent_<ulid> -> conversation.bedrock_ha_agent."""
    entry = _make_entry(hass)
    ent_reg = er.async_get(hass)
    # Simulate an entity HA previously auto-created from the unique_id
    ent_reg.async_get_or_create(
        "conversation",
        DOMAIN,
        entry.entry_id,  # unique_id (ULID)
        suggested_object_id=f"bedrock_ha_agent_{entry.entry_id}",
        config_entry=entry,
    )
    original_id = ent_reg.async_get_entity_id("conversation", DOMAIN, entry.entry_id)
    assert original_id == f"conversation.bedrock_ha_agent_{entry.entry_id}"

    await _async_migrate_conversation_entity_id(hass, entry)

    new_id = ent_reg.async_get_entity_id("conversation", DOMAIN, entry.entry_id)
    assert new_id == "conversation.bedrock_ha_agent", f"got: {new_id}"


@pytest.mark.asyncio
async def test_migration_noop_when_already_clean(hass):
    """Running the migration against an already-clean id is a no-op."""
    entry = _make_entry(hass)
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "conversation",
        DOMAIN,
        entry.entry_id,
        suggested_object_id="bedrock_ha_agent",
        config_entry=entry,
    )
    pre = ent_reg.async_get_entity_id("conversation", DOMAIN, entry.entry_id)
    assert pre == "conversation.bedrock_ha_agent"

    await _async_migrate_conversation_entity_id(hass, entry)

    post = ent_reg.async_get_entity_id("conversation", DOMAIN, entry.entry_id)
    assert post == "conversation.bedrock_ha_agent"


@pytest.mark.asyncio
async def test_migration_noop_when_no_entity_registered(hass):
    """Fresh install (no entity registered yet) short-circuits without error."""
    entry = _make_entry(hass)
    # No entity registered — suggested_object_id will handle the fresh case.
    await _async_migrate_conversation_entity_id(hass, entry)  # must not raise


@pytest.mark.asyncio
async def test_migration_suffixes_on_collision(hass):
    """If conversation.bedrock_ha_agent is already taken by another entry,
    the migration falls back to conversation.bedrock_ha_agent_2.
    """
    entry1 = MockConfigEntry(
        domain=DOMAIN, entry_id="entry_1", data={}, options={}
    )
    entry1.add_to_hass(hass)

    entry2 = MockConfigEntry(
        domain=DOMAIN, entry_id="entry_2_ulid", data={}, options={}
    )
    entry2.add_to_hass(hass)

    ent_reg = er.async_get(hass)
    # Entry 1 already owns conversation.bedrock_ha_agent
    ent_reg.async_get_or_create(
        "conversation",
        DOMAIN,
        "entry_1",
        suggested_object_id="bedrock_ha_agent",
        config_entry=entry1,
    )
    # Entry 2 has the ULID-suffixed id
    ent_reg.async_get_or_create(
        "conversation",
        DOMAIN,
        "entry_2_ulid",
        suggested_object_id="bedrock_ha_agent_entry_2_ulid",
        config_entry=entry2,
    )

    await _async_migrate_conversation_entity_id(hass, entry2)

    new_id = ent_reg.async_get_entity_id("conversation", DOMAIN, "entry_2_ulid")
    assert new_id == "conversation.bedrock_ha_agent_2", f"got: {new_id}"
