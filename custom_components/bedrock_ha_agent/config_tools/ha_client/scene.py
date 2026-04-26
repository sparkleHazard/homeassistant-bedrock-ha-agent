"""Scene config transport.

Writes one YAML file per scene to the user's scenes directory
(default ``/config/scenes/``). Matches the common HA convention

    scene: !include_dir_merge_list scenes/

Each scene lives at ``scenes/<object_id>.yaml``; ``scene.reload`` picks
the directory back up.

Mirrors automation.py. See that module's docstring for the motivation.
"""
from __future__ import annotations
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_SCENES_DIR = "scenes"
_FILE_SUFFIX = ".yaml"


def _scenes_dir(hass: "HomeAssistant") -> str:
    return hass.config.path(_SCENES_DIR)


def _file_for(hass: "HomeAssistant", object_id: str) -> str:
    return os.path.join(_scenes_dir(hass), f"{object_id}{_FILE_SUFFIX}")


async def list_scenes(hass: "HomeAssistant") -> list[dict]:
    """Return every scene config present in the scenes directory."""
    from homeassistant.util.yaml import load_yaml

    directory = _scenes_dir(hass)

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
                _LOGGER.warning("list_scenes: failed to parse %s: %s", path, err)
                continue
            if data is None:
                continue
            if isinstance(data, list):
                results.extend(d for d in data if isinstance(d, dict))
            elif isinstance(data, dict):
                results.append(data)
        return results

    return await hass.async_add_executor_job(_walk)


async def get_scene(hass: "HomeAssistant", object_id: str) -> dict | None:
    """Return the stored config for a given scene object_id, or None if absent."""
    from homeassistant.util.yaml import load_yaml

    path = _file_for(hass, object_id)

    def _read() -> dict | None:
        if not os.path.isfile(path):
            return None
        try:
            data = load_yaml(path)
        except Exception as err:
            _LOGGER.warning("get_scene: failed to parse %s: %s", path, err)
            return None
        if isinstance(data, dict):
            return data
        return None

    return await hass.async_add_executor_job(_read)


async def create_or_update_scene(
    hass: "HomeAssistant", object_id: str, config: dict
) -> None:
    """Write ``<scenes_dir>/<object_id>.yaml`` atomically."""
    from homeassistant.util.file import write_utf8_file_atomic
    from homeassistant.util.yaml import dump

    directory = _scenes_dir(hass)
    path = _file_for(hass, object_id)

    # Scenes may optionally carry an `id` for the UI; if caller provided
    # one, keep it, otherwise set it from object_id so the entity gets a
    # stable id across reloads.
    payload = dict(config)
    payload.setdefault("id", object_id)

    def _write() -> None:
        os.makedirs(directory, exist_ok=True)
        contents = dump(payload)
        write_utf8_file_atomic(path, contents)
        _LOGGER.info(
            "create_or_update_scene: wrote %d bytes to %s",
            len(contents), path,
        )

    _LOGGER.info(
        "create_or_update_scene: target path=%s object_id=%s", path, object_id
    )
    await hass.async_add_executor_job(_write)


async def delete_scene(hass: "HomeAssistant", object_id: str) -> None:
    """Remove the per-object_id file. Raises KeyError if absent."""
    path = _file_for(hass, object_id)

    def _unlink() -> None:
        if not os.path.isfile(path):
            raise KeyError(f"Scene {object_id} not found at {path}")
        os.unlink(path)
        _LOGGER.info("delete_scene: removed %s", path)

    await hass.async_add_executor_job(_unlink)


async def reload_scenes(hass: "HomeAssistant") -> None:
    """Fire the scene.reload service."""
    await hass.services.async_call("scene", "reload", blocking=True)
