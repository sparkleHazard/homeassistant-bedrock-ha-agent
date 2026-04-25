"""Helper entities (input_*, timer, counter) config transport."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


SUPPORTED_HELPER_DOMAINS = frozenset({
    "input_boolean",
    "input_number",
    "input_select",
    "input_text",
    "input_datetime",
    "input_button",
    "timer",
    "counter",
})


async def list_helpers(hass: "HomeAssistant", domain: str) -> list[dict]:
    """Return the list of helpers for the given domain."""
    _check_domain(domain)
    raise NotImplementedError("TODO: HA 2026.2 storage collection path")


async def get_helper(hass: "HomeAssistant", domain: str, object_id: str) -> dict | None:
    """Return the stored config for a given helper, or None if absent."""
    _check_domain(domain)
    raise NotImplementedError("TODO: HA 2026.2 storage collection path")


async def create_helper(hass: "HomeAssistant", domain: str, config: dict) -> str:
    """Create a helper; return the resulting object_id."""
    _check_domain(domain)
    raise NotImplementedError("TODO: HA 2026.2 storage collection path")


async def update_helper(
    hass: "HomeAssistant", domain: str, object_id: str, config: dict
) -> None:
    """Update a helper config."""
    _check_domain(domain)
    raise NotImplementedError("TODO: HA 2026.2 storage collection path")


async def delete_helper(hass: "HomeAssistant", domain: str, object_id: str) -> None:
    """DELETE a helper config. Raises KeyError if absent."""
    _check_domain(domain)
    raise NotImplementedError("TODO: HA 2026.2 storage collection path")


async def reload_helper_domain(hass: "HomeAssistant", domain: str) -> None:
    """Fire <domain>.reload if the service exists."""
    _check_domain(domain)
    if hass.services.has_service(domain, "reload"):
        await hass.services.async_call(domain, "reload", blocking=True)


def _check_domain(domain: str) -> None:
    if domain not in SUPPORTED_HELPER_DOMAINS:
        raise ValueError(
            f"helper domain {domain!r} not in supported set {sorted(SUPPORTED_HELPER_DOMAINS)}"
        )
