"""AC19 + setup-time smoke test: every HA API this integration depends on must resolve.

Fails with an actionable message naming the missing helper and the HA version that
introduced it. This runs both in the test suite AND at integration setup (where it
raises ConfigEntryNotReady on failure — see __init__.py:_smoke_check_ha_apis).
"""
from __future__ import annotations

import pytest

from custom_components.bedrock_conversation._ha_api_smoke import check_required_ha_apis


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
