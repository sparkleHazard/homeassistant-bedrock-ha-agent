"""Diff rendering helpers for config-editing proposals.

Two outputs per proposal:
  * `proposed_diff` — unified-diff string of YAML-dumped before/after; for text clients.
  * `proposed_summary` — short (<200 chars), TTS-safe natural-language description;
    NEVER contains YAML syntax or diff markers. Starts with an imperative/conditional verb
    ("Would add", "Would rename", ...).

The text-stream contract (AC12, Principle #6) forbids any diff marker in a TTS payload,
so `render_spoken_summary` asserts len < 200 and no newline-then-`-`/`+` sequences.
"""

from __future__ import annotations

from difflib import unified_diff
from typing import Any

import yaml

_DIFF_MARKER_PREFIXES = ("--- ", "+++ ", "@@")


def _to_plain(obj: Any) -> Any:
    """Strip HA YAML node subclasses (NodeStrClass/NodeDictClass/NodeListClass) to
    plain dict/list/str so ``yaml.safe_dump`` has a representer. HA's loader tags
    loaded values with filename+line metadata by subclassing str/dict/list, and
    the default SafeDumper doesn't know about those subclasses.
    """
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


def _dump_yaml(obj: Any) -> str:
    """Deterministic YAML for diffing. `None` → empty string."""
    if obj is None:
        return ""
    return yaml.safe_dump(_to_plain(obj), sort_keys=True, default_flow_style=False).rstrip() + "\n"


def render_unified_diff(
    before: Any,
    after: Any,
    *,
    fromfile: str = "before",
    tofile: str = "after",
    context_lines: int = 3,
) -> str:
    """Return a unified diff between YAML-dumped `before` and `after`.

    When before is None → diff shows pure additions.
    When after is None → diff shows pure deletions.
    When both equal → returns an empty string.
    """
    before_text = _dump_yaml(before)
    after_text = _dump_yaml(after)
    if before_text == after_text:
        return ""
    lines = unified_diff(
        before_text.splitlines(keepends=True),
        after_text.splitlines(keepends=True),
        fromfile=fromfile,
        tofile=tofile,
        n=context_lines,
    )
    return "".join(lines)


def render_spoken_summary(
    verb: str,
    noun_phrase: str,
    *,
    detail: str | None = None,
    max_length: int = 200,
) -> str:
    """Build a TTS-safe imperative/conditional summary.

    Examples:
        render_spoken_summary("Would add", "the automation 'Porch light at sunset'")
        render_spoken_summary("Would rename", "the area 'Living Room'", detail="to 'Family Room'")

    Runtime guarantees (defense-in-depth against AC12 regressions):
      * Never contains newline-then-`-`/`+` (diff markers).
      * Never contains `---`, `+++`, `@@`.
      * len <= max_length (default 200). If the composed string would exceed,
        the detail is truncated with an ellipsis; never the verb+noun_phrase core.
      * First token is the verb (imperative/conditional).
    """
    if not verb.strip():
        raise ValueError("verb is required")
    if not noun_phrase.strip():
        raise ValueError("noun_phrase is required")

    base = f"{verb.strip()} {noun_phrase.strip()}"
    if detail:
        candidate = f"{base} {detail.strip()}"
    else:
        candidate = base

    # Enforce length
    if len(candidate) > max_length:
        # Try to keep the core; truncate the detail
        if detail:
            # Available budget = max_length - len(base) - 1 (space) - 1 (ellipsis)
            ellipsis = "…"
            budget = max_length - len(base) - 1 - len(ellipsis)
            if budget > 0:
                truncated = detail.strip()[:budget].rstrip()
                candidate = f"{base} {truncated}{ellipsis}"
            else:
                candidate = base[:max_length]
        else:
            candidate = base[:max_length]

    _assert_tts_safe(candidate, max_length)
    return candidate


def _assert_tts_safe(text: str, max_length: int) -> None:
    """Runtime defense: catch accidental diff content slipping into a spoken summary."""
    if len(text) > max_length:
        raise ValueError(f"spoken summary exceeds max_length={max_length}: {len(text)} chars")
    for marker in _DIFF_MARKER_PREFIXES:
        if marker in text:
            raise ValueError(
                f"spoken summary contains diff marker '{marker.strip()}' (TTS-unsafe)"
            )
    # Newline-then-`-` or newline-then-`+` would also be a diff marker
    if "\n-" in text or "\n+" in text:
        raise ValueError("spoken summary contains newline-then-'-' or newline-then-'+' (TTS-unsafe)")


def is_tts_safe(text: str, *, max_length: int = 200) -> bool:
    """Non-raising check used in tests/AC12."""
    try:
        _assert_tts_safe(text, max_length)
    except ValueError:
        return False
    return True
