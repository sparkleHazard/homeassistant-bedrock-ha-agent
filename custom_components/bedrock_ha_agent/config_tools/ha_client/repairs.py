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


async def list_issues(
    hass: "HomeAssistant",
    domain: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Return a slim list of active Repairs issues.

    Issue shape (minimal — voice-pipeline friendly):
        {'domain': str, 'issue_id': str, 'severity': str|None, 'active': bool}

    Drops `is_fixable`, `is_persistent`, `translation_key`,
    `translation_placeholders`, `created`, `dismissed_version` —
    those are debug-level, not "what should I tell the user" level.
    Agents can follow up with a specific issue lookup if needed.

    Filters:
        domain: return only issues from this integration domain.
        limit: cap the count (default 20, prevents dashboard-wide dumps).
    """
    from homeassistant.helpers.issue_registry import DATA_REGISTRY

    registry = hass.data.get(DATA_REGISTRY)
    if registry is None:
        return {"issues": [], "count": 0, "reason": "repairs not loaded"}

    issues: list[dict[str, Any]] = []
    for (d, issue_id), issue_entry in registry.issues.items():
        if domain and d != domain:
            continue
        if not issue_entry.active:
            continue
        issues.append({
            "domain": d,
            "issue_id": issue_id,
            "severity": issue_entry.severity.value if issue_entry.severity else None,
        })
        if len(issues) >= limit:
            break

    return {"issues": issues, "count": len(issues)}
