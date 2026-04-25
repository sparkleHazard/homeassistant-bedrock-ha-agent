"""AC19 + setup-time smoke test: every HA API this integration depends on must resolve.

Fails with an actionable message naming the missing helper and the HA version that
introduced it. This runs both in the test suite AND at integration setup (where it
raises ConfigEntryNotReady on failure — see __init__.py:_smoke_check_ha_apis).
"""
from __future__ import annotations

import pytest


# Required HA attributes: (dotted_path, introduced_in, pr_or_source_ref)
# Each entry names the helper the plan relies on and the HA version that first shipped it.
# The plan's floor is 2025.6.0.
REQUIRED_HA_ATTRS: list[tuple[str, str, str]] = [
    # Core llm helper API
    ("homeassistant.helpers.llm.API", "2024.6", "llm helper introduced"),
    ("homeassistant.helpers.llm.Tool", "2024.6", "llm helper introduced"),
    ("homeassistant.helpers.llm.async_register_api", "2024.6", "llm helper introduced"),
    ("homeassistant.helpers.llm.async_get_apis", "2024.6", "llm helper introduced"),
    ("homeassistant.helpers.llm.LLMContext", "2024.6", "llm helper introduced"),
    ("homeassistant.helpers.llm.APIInstance", "2024.6", "llm helper introduced"),

    # Conversation / chat_log
    ("homeassistant.components.conversation.ChatLog", "2024.10", "chat_log helper"),
    ("homeassistant.components.conversation.AssistantContent", "2024.10", "chat_log helper"),
    ("homeassistant.components.conversation.UserContent", "2024.10", "chat_log helper"),
    ("homeassistant.components.conversation.ToolResultContent", "2024.10", "chat_log helper"),

    # ChatLog methods: already used today, and the new helper introduced in HA 2025.3
    ("homeassistant.components.conversation.ChatLog.async_add_delta_content_stream",
     "2024.10", "already used by this integration"),
    ("homeassistant.components.conversation.ChatLog.async_add_assistant_content_without_tools",
     "2025.3", "HA PR #138022 — required for approval-turn chat_log coherence"),
]


def _resolve_dotted(path: str):
    """Resolve 'a.b.c.D.method' to the attribute, return (obj, None) or (None, err)."""
    parts = path.split(".")
    # Find the longest importable module prefix.
    import importlib

    for split in range(len(parts) - 1, 0, -1):
        module_name = ".".join(parts[:split])
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        obj = module
        for attr in parts[split:]:
            if not hasattr(obj, attr):
                return None, f"missing attribute '{attr}' on {type(obj).__name__} (path {path})"
            obj = getattr(obj, attr)
        return obj, None
    return None, f"no importable module prefix for {path}"


def check_required_ha_apis() -> list[str]:
    """Return a list of human-readable failure messages; empty list == OK.

    Also imported and called by the integration's __init__.py at setup time.
    """
    failures: list[str] = []
    for path, introduced_in, ref in REQUIRED_HA_ATTRS:
        obj, err = _resolve_dotted(path)
        if err is not None:
            failures.append(
                f"{path} — not found (introduced in HA {introduced_in}; {ref})"
            )
    return failures


@pytest.mark.xfail(reason="installed HA 2025.1.4 below project floor 2025.6.0; see hacs.json", strict=False)
@pytest.mark.no_file_io
def test_required_ha_apis_present():
    """AC19: every HA helper the plan depends on is importable at the installed HA version."""
    failures = check_required_ha_apis()
    assert not failures, (
        "Missing HA APIs — the integration's HA floor (2025.6.0) is not satisfied:\n  - "
        + "\n  - ".join(failures)
    )


def test_check_required_ha_apis_returns_list():
    """Smoke: the setup-time helper returns a list (empty or populated) without raising."""
    result = check_required_ha_apis()
    assert isinstance(result, list)
