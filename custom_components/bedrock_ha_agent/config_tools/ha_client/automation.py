"""Automation config transport.

Writes to the flat, UI-editable ``<config>/automations.yaml`` file —
the same file HA's built-in automation editor reads and writes via
``/api/config/automation/config/<id>``. Using this file is what makes
agent-created automations round-trippable in the UI (the editor shows
"This automation cannot be edited from the UI, because it is not
stored in the automations.yaml file, or doesn't have an ID" for any
automation not in this file).

``automations.yaml`` is a YAML list of automation dicts, each carrying
an ``id`` field:

    - id: porch_light_sunset
      alias: Porch light at sunset
      trigger: [...]
      action: [...]

The file is missing on a fresh HA install and is created lazily on
first write as ``[]``. Callers must ensure ``configuration.yaml``
contains ``automation: !include automations.yaml`` for HA to actually
load from it — this is surfaced via a one-time persistent_notification
at integration setup when ``CONF_ENABLE_CONFIG_EDITING`` is True.

Why not per-file-per-object (the previous v1.1.8 layout)? Files under
``automations/`` load fine via ``!include_dir_merge_list automations/``
but the HA UI editor is hardcoded to edit ``automations.yaml`` and
will refuse to open anything it didn't put there itself. Keeping our
writes in the UI-editable file means the user can hand-edit or tweak
our output without leaving the UI.
"""
from __future__ import annotations
import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# HA's config.automation integration hardcodes this filename.
# See homeassistant/components/config/automation.py::CONFIG_PATH.
_AUTOMATIONS_FILE = "automations.yaml"


def _automations_path(hass: "HomeAssistant") -> str:
    return hass.config.path(_AUTOMATIONS_FILE)


def _load_list(hass: "HomeAssistant") -> list[dict]:
    """Load automations.yaml as a list-of-dicts. Missing/empty → []."""
    from homeassistant.util.yaml import load_yaml

    path = _automations_path(hass)
    if not os.path.isfile(path):
        return []
    try:
        data = load_yaml(path)
    except Exception as err:
        _LOGGER.warning(
            "automations.yaml parse failed (%s); treating as empty list", err
        )
        return []
    if data is None:
        return []
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    # Legacy or hand-edited single-dict file. Promote it to a 1-item list so
    # subsequent writes don't lose it.
    if isinstance(data, dict):
        return [data]
    _LOGGER.warning(
        "automations.yaml top-level is %s, expected list; treating as empty",
        type(data).__name__,
    )
    return []


def _save_list(hass: "HomeAssistant", items: list[dict]) -> None:
    """Atomically write items to automations.yaml as a YAML list."""
    from homeassistant.util.file import write_utf8_file_atomic
    from homeassistant.util.yaml import dump

    path = _automations_path(hass)
    # Normalize: strip HA YAML node subclasses so dump doesn't hit
    # RepresenterError on round-trip. Mirrors diff.py::_to_plain.
    plain = _to_plain(items)
    contents = dump(plain) if plain else "[]\n"
    write_utf8_file_atomic(path, contents)
    _LOGGER.info(
        "automations.yaml: wrote %d entries (%d bytes) to %s",
        len(items), len(contents), path,
    )


def _to_plain(obj: Any) -> Any:
    """Strip NodeDictClass/NodeStrClass/NodeListClass subclasses before dump."""
    if isinstance(obj, dict):
        return {_to_plain(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(x) for x in obj]
    if isinstance(obj, bool):
        return bool(obj)
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        return float(obj)
    if isinstance(obj, str):
        return str(obj)
    if obj is None:
        return None
    return str(obj)


async def list_automations(hass: "HomeAssistant") -> list[dict]:
    """Return every automation config in automations.yaml."""
    return await hass.async_add_executor_job(_load_list, hass)


async def get_automation(hass: "HomeAssistant", object_id: str) -> dict | None:
    """Return the stored config for a given automation id, or None if absent.

    ``object_id`` is matched against the ``id`` field of each entry (HA's UI
    editor uses ``id``, not a filename slug). This is the canonical identifier.
    """
    from homeassistant.const import CONF_ID

    def _find() -> dict | None:
        items = _load_list(hass)
        for item in items:
            if item.get(CONF_ID) == object_id:
                return dict(item)
        return None

    return await hass.async_add_executor_job(_find)


async def create_or_update_automation(
    hass: "HomeAssistant", object_id: str, config: dict
) -> None:
    """Upsert the automation into automations.yaml keyed by ``id``.

    If an entry with the same ``id`` exists, it is replaced in place
    (preserving order). Otherwise the entry is appended to the end.
    The ``id`` field is canonical: overwrites whatever is in ``config``.
    """
    from homeassistant.const import CONF_ID

    entry = {CONF_ID: object_id, **{k: v for k, v in config.items() if k != CONF_ID}}

    def _write() -> None:
        items = _load_list(hass)
        for i, existing in enumerate(items):
            if existing.get(CONF_ID) == object_id:
                items[i] = entry
                break
        else:
            items.append(entry)
        _save_list(hass, items)

    _LOGGER.info(
        "create_or_update_automation: target=%s object_id=%s",
        _automations_path(hass), object_id,
    )
    await hass.async_add_executor_job(_write)


async def delete_automation(hass: "HomeAssistant", object_id: str) -> None:
    """Remove the automation from automations.yaml. Raises KeyError if absent."""
    from homeassistant.const import CONF_ID

    def _write() -> None:
        items = _load_list(hass)
        filtered = [item for item in items if item.get(CONF_ID) != object_id]
        if len(filtered) == len(items):
            raise KeyError(
                f"Automation {object_id!r} not found in {_automations_path(hass)}"
            )
        _save_list(hass, filtered)
        _LOGGER.info("delete_automation: removed %s from automations.yaml", object_id)

    await hass.async_add_executor_job(_write)


async def reload_automations(hass: "HomeAssistant") -> None:
    """Fire the automation.reload service and clean orphaned registry stubs.

    Earlier versions of this integration (v1.1.0-v1.1.7) wrote automations
    through different storage paths (.storage/automations, then per-file
    directories). Each retry/collision could leave an orphaned entity in
    the entity registry tagged ``restored: true`` and state ``unavailable``
    — its backing config no longer exists anywhere. The UI keeps showing
    that stub and blocks the entity_id slot for the real, reloaded
    automation.

    After reload we scan the registry for automation entries whose
    ``unique_id`` (HA's automation platform uses the config ``id`` field
    as the unique_id) no longer exists in automations.yaml, and whose
    state is ``unavailable`` (the "restored stub" fingerprint). Those get
    removed. We never touch a live entity — the state check is the
    safety rail.
    """
    await hass.services.async_call("automation", "reload", blocking=True)
    await _cleanup_orphan_registry_entries(hass)


async def _cleanup_orphan_registry_entries(hass: "HomeAssistant") -> None:
    """Remove automation.* entity_registry stubs whose config is gone.

    Only removes entries that are BOTH unknown to automations.yaml AND
    currently unavailable — these are restored registry stubs from prior
    writes, not live automations the user or another integration loaded
    from .storage or a package.
    """
    from homeassistant.helpers import entity_registry as er

    def _known_ids() -> set[str]:
        return {str(item.get("id")) for item in _load_list(hass) if item.get("id")}

    known = await hass.async_add_executor_job(_known_ids)
    registry = er.async_get(hass)
    removed: list[str] = []
    for entry in list(registry.entities.values()):
        if entry.platform != "automation":
            continue
        if not entry.entity_id.startswith("automation."):
            continue
        unique_id = entry.unique_id
        if unique_id in known:
            continue  # live entry with a config backing it
        # Unknown unique_id. Only remove if the state says it's a restored stub —
        # an automation loaded from a package or .storage would be state != unavailable.
        state = hass.states.get(entry.entity_id)
        if state is None:
            continue
        if state.state != "unavailable":
            continue
        if not state.attributes.get("restored"):
            continue
        registry.async_remove(entry.entity_id)
        removed.append(entry.entity_id)
    if removed:
        _LOGGER.info(
            "cleanup_orphan_registry_entries: removed %d stale stub(s): %s",
            len(removed), ", ".join(removed),
        )
