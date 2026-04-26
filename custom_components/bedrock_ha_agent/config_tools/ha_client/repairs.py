"""Transport for HA repairs component (user-surfaced issues).

Verified against: .venv/lib/python3.13/site-packages/homeassistant/helpers/issue_registry.py:24
(DATA_REGISTRY constant) and line 115 (IssueRegistry.issues attribute is dict[tuple[str, str], IssueEntry]).
"""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def list_issues(hass: "HomeAssistant") -> dict[str, Any]:
    """Return {'issues': [...], 'count': N}.

    Source: hass.data[homeassistant.helpers.issue_registry.DATA_REGISTRY].issues
    (dict of (domain, issue_id) -> IssueEntry).
    """
    from homeassistant.helpers.issue_registry import DATA_REGISTRY

    registry = hass.data.get(DATA_REGISTRY)
    if registry is None:
        return {"issues": [], "count": 0, "reason": "repairs not loaded"}

    # registry.issues is dict[(domain, issue_id), IssueEntry]
    issues = []
    for (domain, issue_id), issue_entry in registry.issues.items():
        issues.append(
            {
                "domain": domain,
                "issue_id": issue_id,
                "is_fixable": issue_entry.is_fixable,
                "is_persistent": issue_entry.is_persistent,
                "severity": issue_entry.severity.value if issue_entry.severity else None,
                "translation_key": issue_entry.translation_key,
                "translation_placeholders": issue_entry.translation_placeholders,
                "active": issue_entry.active,
                "created": issue_entry.created.isoformat() if issue_entry.created else None,
                "dismissed_version": issue_entry.dismissed_version,
            }
        )

    return {"issues": issues, "count": len(issues)}
