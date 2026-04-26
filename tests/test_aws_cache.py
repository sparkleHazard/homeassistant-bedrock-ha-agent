"""Tests for the shared AWS discovery cache.

Covers the acceptance criteria in the plan at
``/Users/alan1/.claude/plans/jolly-wobbling-bubble.md`` §6.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from homeassistant.core import HomeAssistant

from custom_components.bedrock_ha_agent import aws_cache
from custom_components.bedrock_ha_agent.const import (
    CONF_AWS_ACCESS_KEY_ID,
    CONF_AWS_SECRET_ACCESS_KEY,
    CONF_AWS_SESSION_TOKEN,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def _reset_aws_cache(hass: HomeAssistant):
    """Ensure the shared cache starts empty before each test.

    The cache lives in ``hass.data[DOMAIN]`` which is per-hass-fixture and
    usually fresh, but we still wipe it defensively so that tests which
    import ``aws_cache`` directly don't see state from previous setups of
    the integration within the same test module.
    """
    domain_bucket = hass.data.setdefault(DOMAIN, {})
    domain_bucket.pop("aws_cache", None)
    domain_bucket.pop("aws_cache_locks", None)
    yield


CREDS_A = {
    CONF_AWS_ACCESS_KEY_ID: "AKIA_AAAA",
    CONF_AWS_SECRET_ACCESS_KEY: "secret-a",
    CONF_AWS_SESSION_TOKEN: None,
}
CREDS_B = {
    CONF_AWS_ACCESS_KEY_ID: "AKIA_BBBB",
    CONF_AWS_SECRET_ACCESS_KEY: "secret-b",
    CONF_AWS_SESSION_TOKEN: None,
}


def _mock_bedrock_paginator(profile_ids: list[str]) -> MagicMock:
    """Return a boto3 paginator mock that yields a single page."""
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {
            "inferenceProfileSummaries": [
                {"inferenceProfileId": pid, "status": "ACTIVE"}
                for pid in profile_ids
            ]
        }
    ]
    return paginator


def _mock_polly_paginator(voices: list[dict]) -> MagicMock:
    paginator = MagicMock()
    paginator.paginate.return_value = [{"Voices": voices}]
    return paginator


def _install_bedrock_session(mock_session: MagicMock, profile_ids: list[str]) -> MagicMock:
    """Wire a patched boto3.Session so `.client("bedrock")` returns our mock.

    Returns the bedrock client mock so callers can assert call counts.
    """
    bedrock_client = MagicMock()
    bedrock_client.get_paginator.return_value = _mock_bedrock_paginator(profile_ids)
    session_instance = MagicMock()
    session_instance.client.return_value = bedrock_client
    mock_session.return_value = session_instance
    return bedrock_client


def _install_polly_session(mock_session: MagicMock, voices: list[dict]) -> MagicMock:
    polly_client = MagicMock()
    polly_client.get_paginator.return_value = _mock_polly_paginator(voices)
    session_instance = MagicMock()
    session_instance.client.return_value = polly_client
    mock_session.return_value = session_instance
    return polly_client


async def test_list_inference_profiles_cache_hit_within_ttl(hass: HomeAssistant):
    """Two calls within TTL trigger one boto3 invocation."""
    with patch("boto3.Session") as mock_session:
        bedrock_client = _install_bedrock_session(
            mock_session, ["us.anthropic.claude-sonnet-4-5"]
        )

        first = await aws_cache.async_list_inference_profiles(
            hass, credentials=CREDS_A, region="us-east-1"
        )
        second = await aws_cache.async_list_inference_profiles(
            hass, credentials=CREDS_A, region="us-east-1"
        )

    assert first == ["us.anthropic.claude-sonnet-4-5"]
    assert second == first
    assert bedrock_client.get_paginator.call_count == 1


async def test_list_inference_profiles_cache_miss_after_ttl(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
):
    """A second call after TTL expiry re-hits boto3."""
    fake_clock = [1000.0]

    def _fake_monotonic() -> float:
        return fake_clock[0]

    monkeypatch.setattr(aws_cache.time, "monotonic", _fake_monotonic)

    with patch("boto3.Session") as mock_session:
        bedrock_client = _install_bedrock_session(
            mock_session, ["us.anthropic.claude-sonnet-4-5"]
        )

        await aws_cache.async_list_inference_profiles(
            hass, credentials=CREDS_A, region="us-east-1"
        )

        # Jump past the TTL.
        fake_clock[0] += aws_cache.CACHE_TTL_SECONDS + 1

        await aws_cache.async_list_inference_profiles(
            hass, credentials=CREDS_A, region="us-east-1"
        )

    assert bedrock_client.get_paginator.call_count == 2


async def test_list_polly_voices_language_scope_independence(hass: HomeAssistant):
    """Full-catalog and language-scoped queries do not share a cache entry."""
    voices_payload = [
        {
            "Id": "Joanna",
            "Name": "Joanna",
            "Gender": "Female",
            "SupportedEngines": ["neural"],
        }
    ]

    with patch("boto3.Session") as mock_session:
        polly_client = _install_polly_session(mock_session, voices_payload)

        await aws_cache.async_list_polly_voices(
            hass, credentials=CREDS_A, region="us-east-1", language=None, engine="neural"
        )
        await aws_cache.async_list_polly_voices(
            hass,
            credentials=CREDS_A,
            region="us-east-1",
            language="en-US",
            engine="neural",
        )

    assert polly_client.get_paginator.call_count == 2


async def test_list_polly_voices_engine_scope_independence(hass: HomeAssistant):
    """Different engines under the same language are distinct cache entries."""
    voices_payload = [
        {
            "Id": "Joanna",
            "Name": "Joanna",
            "Gender": "Female",
            "SupportedEngines": ["neural", "long-form"],
        }
    ]

    with patch("boto3.Session") as mock_session:
        polly_client = _install_polly_session(mock_session, voices_payload)

        await aws_cache.async_list_polly_voices(
            hass,
            credentials=CREDS_A,
            region="us-east-1",
            language="en-US",
            engine="neural",
        )
        await aws_cache.async_list_polly_voices(
            hass,
            credentials=CREDS_A,
            region="us-east-1",
            language="en-US",
            engine="long-form",
        )

    assert polly_client.get_paginator.call_count == 2


async def test_invalidate_drops_entries_for_access_key(hass: HomeAssistant):
    """`invalidate()` removes entries for the target key, preserves others."""
    with patch("boto3.Session") as mock_session:
        bedrock_client = _install_bedrock_session(
            mock_session, ["us.anthropic.claude-sonnet-4-5"]
        )

        await aws_cache.async_list_inference_profiles(
            hass, credentials=CREDS_A, region="us-east-1"
        )
        await aws_cache.async_list_inference_profiles(
            hass, credentials=CREDS_B, region="us-east-1"
        )
        first_count = bedrock_client.get_paginator.call_count

        aws_cache.invalidate(hass, access_key_id=CREDS_A[CONF_AWS_ACCESS_KEY_ID])

        # CREDS_A should re-fetch; CREDS_B should be served from cache.
        await aws_cache.async_list_inference_profiles(
            hass, credentials=CREDS_A, region="us-east-1"
        )
        await aws_cache.async_list_inference_profiles(
            hass, credentials=CREDS_B, region="us-east-1"
        )

    # Exactly one additional boto3 call (for CREDS_A after invalidation).
    assert bedrock_client.get_paginator.call_count == first_count + 1


async def test_concurrent_calls_coalesce(hass: HomeAssistant):
    """Parallel calls for the same key trigger exactly one executor invocation."""
    call_count = 0
    enter_event = asyncio.Event()
    release_event = asyncio.Event()

    real_executor = hass.async_add_executor_job

    async def _blocking_executor(func, *args):
        nonlocal call_count
        call_count += 1
        enter_event.set()
        # Hold the executor slot until the test releases it, so every coroutine
        # queues on the per-key lock rather than completing serially.
        await release_event.wait()
        return await real_executor(func, *args)

    hass.async_add_executor_job = _blocking_executor  # type: ignore[assignment]

    try:
        with patch("boto3.Session") as mock_session:
            _install_bedrock_session(
                mock_session, ["us.anthropic.claude-sonnet-4-5"]
            )

            tasks = [
                asyncio.create_task(
                    aws_cache.async_list_inference_profiles(
                        hass, credentials=CREDS_A, region="us-east-1"
                    )
                )
                for _ in range(5)
            ]

            await enter_event.wait()
            release_event.set()
            results = await asyncio.gather(*tasks)
    finally:
        hass.async_add_executor_job = real_executor  # type: ignore[assignment]

    assert call_count == 1
    assert all(r == ["us.anthropic.claude-sonnet-4-5"] for r in results)


async def test_cache_not_poisoned_on_error(hass: HomeAssistant):
    """On AWS error the exception propagates and no entry is cached."""
    with patch("boto3.Session") as mock_session:
        bedrock_client = MagicMock()
        bedrock_client.get_paginator.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "nope"}},
            "ListInferenceProfiles",
        )
        session_instance = MagicMock()
        session_instance.client.return_value = bedrock_client
        mock_session.return_value = session_instance

        with pytest.raises(ClientError):
            await aws_cache.async_list_inference_profiles(
                hass, credentials=CREDS_A, region="us-east-1"
            )

    # Cache store should be empty — no entry was written.
    store = hass.data[DOMAIN].get("aws_cache", {})
    assert store == {}


async def test_cache_key_excludes_secret_and_session_token(hass: HomeAssistant):
    """Build-key helper must not leak secret_key or session_token."""
    creds = {
        CONF_AWS_ACCESS_KEY_ID: "AKIA_TEST",
        CONF_AWS_SECRET_ACCESS_KEY: "super-secret-value",
        CONF_AWS_SESSION_TOKEN: "sts-token-value",
    }
    key = aws_cache._build_key(creds, "us-east-1", "bedrock:list_inference_profiles")
    flat = str(key)
    assert "super-secret-value" not in flat
    assert "sts-token-value" not in flat
    assert "AKIA_TEST" in flat
