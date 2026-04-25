"""AC13: no file I/O under /config from the integration's own code.

HA's integrations (automation, script, scene) persist YAML via their own
storage paths. Our job is to call HA APIs; HA does the disk work. This test
walks the integration source with ast.parse and rejects direct `open()`,
`Path.read_*`/`write_*`, and `os.path.*` calls on `/config`-rooted paths.

Known allowlisted exceptions (documented, tracked for future migration):

- config_tools/ha_client/automation.py — uses HA's write_utf8_file_atomic
  + load_yaml to read/write the UI-managed automations.yaml file. This is
  routed through HA's own atomic-write helper AND wrapped in
  hass.async_add_executor_job (HA's recommended pattern for sync I/O from
  async code). It targets HA's OWN storage file in /config, not arbitrary
  paths. A future HA release may expose a storage-collection API that
  eliminates this exception; TODO tracked in the plan's follow-up section.

Any new file-I/O caller must either route through HA APIs OR be added to
this allowlist with justification.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


INTEGRATION_ROOT = Path("custom_components/bedrock_conversation")

# Files explicitly allowed to do file I/O, with justification.
ALLOWLISTED_FILES: dict[str, str] = {
    "config_tools/ha_client/automation.py": (
        "Routes automations.yaml writes through HA's write_utf8_file_atomic "
        "+ load_yaml via hass.async_add_executor_job. Targets HA's own "
        "UI-managed storage file, not arbitrary paths. Tracked for migration "
        "once HA 2026+ exposes a storage-collection API."
    ),
}


class _FileIoFinder(ast.NodeVisitor):
    """Walks an AST looking for disallowed file-I/O call patterns."""

    FORBIDDEN_FUNCTION_NAMES = frozenset({"open"})
    FORBIDDEN_PATH_METHODS = frozenset({
        "read_text", "write_text", "read_bytes", "write_bytes",
        "open", "touch", "unlink", "mkdir",
    })
    OS_PATH_SENSITIVE = frozenset({"join", "exists", "isfile", "isdir"})

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.offenses: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        # Case 1: bare `open(...)`
        if isinstance(node.func, ast.Name) and node.func.id in self.FORBIDDEN_FUNCTION_NAMES:
            self.offenses.append((node.lineno, f"{self.filename}:{node.lineno} — disallowed call `{node.func.id}(...)`"))

        # Case 2: `something.read_text()` / `something.write_text()` etc.
        if isinstance(node.func, ast.Attribute) and node.func.attr in self.FORBIDDEN_PATH_METHODS:
            # Heuristic: flag only when the call has any /config string literal arg
            # OR when the receiver looks like a Path object
            if self._args_contain_config_path(node) or self._receiver_looks_like_path(node.func):
                self.offenses.append((
                    node.lineno,
                    f"{self.filename}:{node.lineno} — disallowed method call `.{node.func.attr}(...)`"
                ))

        # Case 3: `os.path.<sensitive>(..., '/config/...')`
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in self.OS_PATH_SENSITIVE
            and self._args_contain_config_path(node)
        ):
            self.offenses.append((
                node.lineno,
                f"{self.filename}:{node.lineno} — disallowed `os.path.{node.func.attr}(.../config/...)`"
            ))

        self.generic_visit(node)

    @staticmethod
    def _args_contain_config_path(node: ast.Call) -> bool:
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "/config" in arg.value:
                return True
        return False

    @staticmethod
    def _receiver_looks_like_path(attr: ast.Attribute) -> bool:
        """Heuristic: flag `Path(...).read_text()` and `some_path.read_text()`.

        Skip cases where the receiver is clearly a stream object (e.g., response['body'].read()).
        """
        # Path(...).read_text()
        if isinstance(attr.value, ast.Call) and isinstance(attr.value.func, ast.Name) and attr.value.func.id == "Path":
            return True

        # Skip stream-like patterns: response['body'], response["AudioStream"], etc.
        if isinstance(attr.value, ast.Subscript):
            return False

        # path_var.read_text() — we can't always tell; be conservative and flag when the
        # attribute chain begins with a 'path' substring in the identifier name.
        node = attr.value
        while isinstance(node, ast.Attribute):
            node = node.value
        if isinstance(node, ast.Name) and "path" in node.id.lower():
            return True
        return False


def _walk_python_files(root: Path):
    for path in root.rglob("*.py"):
        # Skip __pycache__
        if "__pycache__" in path.parts:
            continue
        yield path


@pytest.mark.no_file_io
def test_no_file_io_under_config_from_integration():
    """AC13: AST walk the integration; no disallowed file-I/O patterns except the allowlist."""
    offenses: list[str] = []
    for path in _walk_python_files(INTEGRATION_ROOT):
        # Compute the relative path for allowlist matching
        try:
            rel_parts = path.relative_to(INTEGRATION_ROOT).parts
        except ValueError:
            continue
        rel = "/".join(rel_parts)
        if rel in ALLOWLISTED_FILES:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as err:
            offenses.append(f"{path}: syntax error {err}")
            continue
        finder = _FileIoFinder(str(path))
        finder.visit(tree)
        offenses.extend(msg for _, msg in finder.offenses)

    if offenses:
        lines = ["File-I/O offenses detected (spec Principle #2):"]
        lines.extend(f"  - {o}" for o in offenses)
        lines.append("")
        lines.append("If this offense is intentional and unavoidable, add the relative file path to "
                     "ALLOWLISTED_FILES in tests/test_no_file_io.py with a justification comment.")
        pytest.fail("\n".join(lines))


@pytest.mark.no_file_io
def test_allowlist_entries_still_exist():
    """Guard against the allowlist drifting from reality (stale entries rot)."""
    for rel_path in ALLOWLISTED_FILES:
        full = INTEGRATION_ROOT / rel_path
        assert full.exists(), (
            f"Allowlisted file {rel_path} does not exist — entry is stale. "
            "Either restore the file or remove the allowlist entry."
        )
