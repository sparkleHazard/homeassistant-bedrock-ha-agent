"""Script config transport.

Writes one YAML file per script to the user's scripts directory
(default ``/config/scripts/``). Matches the common HA convention

    script: !include_dir_merge_list scripts/

that directory-based HA installations use instead of a single
``scripts.yaml``. Each script lives at ``scripts/<object_id>.yaml``;
``script.reload`` picks the directory back up.

Mirrors the per-file-per-object pattern used by automation.py. See
that module's docstring for the motivation.
"""
from __future__ import annotations
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_SCRIPTS_DIR = "scripts"
_FILE_SUFFIX = ".yaml"


def _scripts_dir(hass: "HomeAssistant") -> str:
    return hass.config.path(_SCRIPTS_DIR)


def _file_for(hass: "HomeAssistant", object_id: str) -> str:
    return os.path.join(_scripts_dir(hass), f"{object_id}{_FILE_SUFFIX}")


async def list_scripts(hass: "HomeAssistant") -> list[dict]:
    """Return every script config present in the scripts directory."""
    from homeassistant.util.yaml import load_yaml

    directory = _scripts_dir(hass)

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
                _LOGGER.warning("list_scripts: failed to parse %s: %s", path, err)
                continue
            if data is None:
                continue
            if isinstance(data, list):
                results.extend(d for d in data if isinstance(d, dict))
            elif isinstance(data, dict):
                results.append(data)
        return results

    return await hass.async_add_executor_job(_walk)


async def get_script(hass: "HomeAssistant", object_id: str) -> dict | None:
    """Return the stored config for a given script object_id, or None if absent."""
    from homeassistant.util.yaml import load_yaml

    path = _file_for(hass, object_id)

    def _read() -> dict | None:
        if not os.path.isfile(path):
            return None
        try:
            data = load_yaml(path)
        except Exception as err:
            _LOGGER.warning("get_script: failed to parse %s: %s", path, err)
            return None
        if isinstance(data, dict):
            return data
        return None

    return await hass.async_add_executor_job(_read)


async def create_or_update_script(
    hass: "HomeAssistant", object_id: str, config: dict
) -> None:
    """Write ``<scripts_dir>/<object_id>.yaml`` atomically."""
    from homeassistant.util.file import write_utf8_file_atomic
    from homeassistant.util.yaml import dump

    directory = _scripts_dir(hass)
    path = _file_for(hass, object_id)

    # Scripts don't carry an `id` field — the object_id is the filename.
    # HA's script.reload identifies scripts by their dict key (mapping
    # layout) or by filename (merge-list layout). We use the latter.
    payload = dict(config)

    def _write() -> None:
        os.makedirs(directory, exist_ok=True)
        contents = dump(payload)
        write_utf8_file_atomic(path, contents)
        _LOGGER.info(
            "create_or_update_script: wrote %d bytes to %s",
            len(contents), path,
        )

    _LOGGER.info(
        "create_or_update_script: target path=%s object_id=%s", path, object_id
    )
    await hass.async_add_executor_job(_write)


async def delete_script(hass: "HomeAssistant", object_id: str) -> None:
    """Remove the per-object_id file. Raises KeyError if absent."""
    path = _file_for(hass, object_id)

    def _unlink() -> None:
        if not os.path.isfile(path):
            raise KeyError(f"Script {object_id} not found at {path}")
        os.unlink(path)
        _LOGGER.info("delete_script: removed %s", path)

    await hass.async_add_executor_job(_unlink)


async def reload_scripts(hass: "HomeAssistant") -> None:
    """Fire the script.reload service."""
    await hass.services.async_call("script", "reload", blocking=True)
