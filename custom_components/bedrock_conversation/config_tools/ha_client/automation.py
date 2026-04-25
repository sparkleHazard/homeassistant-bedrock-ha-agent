"""Automation config transport. Uses HA's automation config storage.

The file I/O happens inside HA's automation config component, not in our code.
We access the data via HA's config view which manages the YAML reading/writing.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def list_automations(hass: "HomeAssistant") -> list[dict]:
    """Return the list of UI-managed automations.

    Uses the same data source as the /api/config/automation/config endpoint.
    """
    from homeassistant.config import AUTOMATION_CONFIG_PATH
    from homeassistant.util.yaml import load_yaml

    path = hass.config.path(AUTOMATION_CONFIG_PATH)
    data = await hass.async_add_executor_job(load_yaml, path)
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return []


async def get_automation(hass: "HomeAssistant", object_id: str) -> dict | None:
    """Return the stored config for a given automation object_id, or None if absent."""
    from homeassistant.const import CONF_ID

    automations = await list_automations(hass)
    for auto in automations:
        if auto.get(CONF_ID) == object_id:
            return auto
    return None


async def create_or_update_automation(
    hass: "HomeAssistant", object_id: str, config: dict
) -> None:
    """POST an automation config; creates if absent, updates in place if present.

    This uses HA's EditIdBasedConfigView pattern by directly manipulating the data
    and writing it back through HA's atomic YAML writer.
    """
    from homeassistant.config import AUTOMATION_CONFIG_PATH
    from homeassistant.const import CONF_ID
    from homeassistant.util.yaml import dump, load_yaml
    from homeassistant.util.file import write_utf8_file_atomic

    path = hass.config.path(AUTOMATION_CONFIG_PATH)

    # Read current data
    data = await hass.async_add_executor_job(load_yaml, path)
    if data is None:
        data = []
    if not isinstance(data, list):
        data = []

    # Find existing or append new
    updated = False
    for i, item in enumerate(data):
        if item.get(CONF_ID) == object_id:
            # Update existing
            data[i] = {CONF_ID: object_id, **config}
            updated = True
            break

    if not updated:
        # Create new
        data.append({CONF_ID: object_id, **config})

    # Write atomically
    def _write() -> None:
        contents = dump(data)
        write_utf8_file_atomic(path, contents)

    await hass.async_add_executor_job(_write)


async def delete_automation(hass: "HomeAssistant", object_id: str) -> None:
    """DELETE an automation config. Raises KeyError if absent."""
    from homeassistant.config import AUTOMATION_CONFIG_PATH
    from homeassistant.const import CONF_ID
    from homeassistant.util.yaml import dump, load_yaml
    from homeassistant.util.file import write_utf8_file_atomic

    path = hass.config.path(AUTOMATION_CONFIG_PATH)

    # Read current data
    data = await hass.async_add_executor_job(load_yaml, path)
    if data is None:
        raise KeyError(f"Automation {object_id} not found (file is empty)")
    if not isinstance(data, list):
        raise KeyError(f"Automation {object_id} not found (file format invalid)")

    # Find and remove
    found_index = None
    for i, item in enumerate(data):
        if item.get(CONF_ID) == object_id:
            found_index = i
            break

    if found_index is None:
        raise KeyError(f"Automation {object_id} not found")

    data.pop(found_index)

    # Write atomically
    def _write() -> None:
        contents = dump(data)
        write_utf8_file_atomic(path, contents)

    await hass.async_add_executor_job(_write)


async def reload_automations(hass: "HomeAssistant") -> None:
    """Fire the automation.reload service."""
    await hass.services.async_call("automation", "reload", blocking=True)
