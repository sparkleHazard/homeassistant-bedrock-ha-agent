"""AC19 + setup-time smoke test: every HA API this integration depends on must resolve.

Fails with an actionable message naming the missing helper and the HA version that
introduced it. This runs both in the test suite AND at integration setup (where it
raises ConfigEntryNotReady on failure — see __init__.py:_smoke_check_ha_apis).
"""
from __future__ import annotations

import pytest

from custom_components.bedrock_ha_agent._ha_api_smoke import check_required_ha_apis


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


def test_check_required_ha_apis_raises_configentrynotready_when_helper_missing(monkeypatch):
    """Simulate a missing helper; setup-time smoke check raises ConfigEntryNotReady."""
    from custom_components.bedrock_ha_agent._ha_api_smoke import REQUIRED_HA_ATTRS

    # Inject a bogus required attr
    fake_attr = (
        "homeassistant.helpers.llm.DefinitelyNotAReal_attr",
        "9999.1",
        "fake for test",
    )
    monkeypatch.setattr(
        "custom_components.bedrock_ha_agent._ha_api_smoke.REQUIRED_HA_ATTRS",
        REQUIRED_HA_ATTRS + [fake_attr],
    )
    failures = check_required_ha_apis()
    assert any("DefinitelyNotAReal_attr" in msg for msg in failures)
    assert any("9999.1" in msg for msg in failures)


@pytest.mark.asyncio
async def test_async_setup_entry_raises_configentrynotready_on_missing_apis(hass):
    """Test that async_setup_entry raises ConfigEntryNotReady when check_required_ha_apis returns failures."""
    from unittest.mock import patch

    from homeassistant.exceptions import ConfigEntryNotReady
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.bedrock_ha_agent import async_setup_entry
    from custom_components.bedrock_ha_agent.const import DOMAIN

    # Create a mock entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Bedrock",
        data={
            "aws_access_key_id": "test_key",
            "aws_secret_access_key": "test_secret",
            "aws_region": "us-west-2",
        },
        options={},
        entry_id="test_entry_id",
    )
    entry.add_to_hass(hass)

    # Mock check_required_ha_apis to return failures
    with patch(
        "custom_components.bedrock_ha_agent.check_required_ha_apis",
        return_value=["homeassistant.helpers.llm.FakeAPI — not found (introduced in HA 9999.1; test)"],
    ):
        with pytest.raises(ConfigEntryNotReady) as exc_info:
            await async_setup_entry(hass, entry)

        assert "Missing required Home Assistant APIs" in str(exc_info.value)
        assert "homeassistant.helpers.llm.FakeAPI" in str(exc_info.value)
