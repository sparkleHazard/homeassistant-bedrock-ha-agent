"""Automation config transport.

Writes one YAML file per automation into the user's automation-directory
(default ``/config/automations/``). Matches the common HA convention

    automation: !include_dir_merge_list automations/

which is used by installations that have outgrown the single-file
``automations.yaml`` layout. Each automation goes to
``automations/<object_id>.yaml`` and HA's ``automation.reload`` service
picks the directory back up.

Why not just append to ``automations.yaml``? Modern HA setups frequently
don't include that file at all (the directory-merge-list form is more
popular); writes there land in a file HA never loads. The per-file
layout is also cleaner for concurrent editors: creates, updates, and
deletes don't race on the same file.

The configured directory is ``<config_dir>/automations`` by default.
Advanced layouts that point ``!include_dir_merge_list`` at a different
path are not yet auto-detected — a follow-up could scan
configuration.yaml and adapt.
"""
from __future__ import annotations
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Each automation gets its own file under this subdirectory of config_dir.
# Matches `automation: !include_dir_merge_list automations/`.
_AUTOMATIONS_DIR = "automations"
# Filename is always `<object_id>.yaml`; no namespacing prefix so files
# drop into the same naming convention as hand-authored ones.
_FILE_SUFFIX = ".yaml"


def _automations_dir(hass: "HomeAssistant") -> str:
    return hass.config.path(_AUTOMATIONS_DIR)


def _file_for(hass: "HomeAssistant", object_id: str) -> str:
    return os.path.join(_automations_dir(hass), f"{object_id}{_FILE_SUFFIX}")


async def list_automations(hass: "HomeAssistant") -> list[dict]:
    """Return every automation config present in the automations directory.

    Each ``<object_id>.yaml`` in the directory contributes one dict. If a
    file contains a YAML list (legacy single-file layout), its entries are
    flattened. Files that fail to parse are logged and skipped.
    """
    from homeassistant.util.yaml import load_yaml

    directory = _automations_dir(hass)

    def _walk() -> list[dict]:
        if not os.path.isdir(directory):
            return []
        results: list[dict] = []
        for name in sorted(os.listdir(directory)):
            if not name.endswith(_FILE_SUFFIX):
                continue
            path = os.path.join(directory, name)
            try:
                data = load_yaml(path)
            except Exception as err:
                _LOGGER.warning(
                    "list_automations: failed to parse %s: %s", path, err
                )
                continue
            if data is None:
                continue
            if isinstance(data, list):
                results.extend(d for d in data if isinstance(d, dict))
            elif isinstance(data, dict):
                results.append(data)
        return results

    return await hass.async_add_executor_job(_walk)


async def get_automation(hass: "HomeAssistant", object_id: str) -> dict | None:
    """Return the stored config for a given automation object_id, or None.

    Looks up ``<automations_dir>/<object_id>.yaml`` directly. Does NOT
    scan the whole directory — object_id uniquely identifies the file.
    """
    from homeassistant.util.yaml import load_yaml

    path = _file_for(hass, object_id)

    def _read() -> dict | None:
        if not os.path.isfile(path):
            return None
        try:
            data = load_yaml(path)
        except Exception as err:
            _LOGGER.warning("get_automation: failed to parse %s: %s", path, err)
            return None
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data:
            # Legacy single-file layouts may shove multiple entries in; pick
            # the one whose id matches (if any).
            from homeassistant.const import CONF_ID

            for item in data:
                if isinstance(item, dict) and item.get(CONF_ID) == object_id:
                    return item
        return None

    return await hass.async_add_executor_job(_read)


async def create_or_update_automation(
    hass: "HomeAssistant", object_id: str, config: dict
) -> None:
    """Write ``<automations_dir>/<object_id>.yaml`` atomically.

    Creates the directory if missing (matches what HA's
    !include_dir_merge_list tolerates on empty dirs). The file contains a
    single YAML dict — the id is set from the argument, not inferred from
    config.
    """
    from homeassistant.const import CONF_ID
    from homeassistant.util.file import write_utf8_file_atomic
    from homeassistant.util.yaml import dump

    directory = _automations_dir(hass)
    path = _file_for(hass, object_id)

    # id is canonical: overwrite whatever caller passed in config.
    # IMPORTANT: `!include_dir_merge_list` only merges files containing a
    # YAML list. A bare dict is silently skipped with no warning, which is
    # how v1.1.7 shipped broken. Wrap the single automation in a 1-element
    # list so it matches the merge_list expectation.
    # See annotatedyaml/loader.py::_include_dir_merge_list_yaml.
    payload = [{CONF_ID: object_id, **{k: v for k, v in config.items() if k != CONF_ID}}]

    def _write() -> None:
        os.makedirs(directory, exist_ok=True)
        contents = dump(payload)
        write_utf8_file_atomic(path, contents)
        _LOGGER.info(
            "create_or_update_automation: wrote %d bytes to %s",
            len(contents), path,
        )

    _LOGGER.info(
        "create_or_update_automation: target path=%s object_id=%s",
        path, object_id,
    )
    await hass.async_add_executor_job(_write)


async def delete_automation(hass: "HomeAssistant", object_id: str) -> None:
    """Remove the per-object_id file. Raises KeyError if absent."""
    path = _file_for(hass, object_id)

    def _unlink() -> None:
        if not os.path.isfile(path):
            raise KeyError(f"Automation {object_id} not found at {path}")
        os.unlink(path)
        _LOGGER.info("delete_automation: removed %s", path)

    await hass.async_add_executor_job(_unlink)


async def reload_automations(hass: "HomeAssistant") -> None:
    """Fire the automation.reload service."""
    await hass.services.async_call("automation", "reload", blocking=True)
