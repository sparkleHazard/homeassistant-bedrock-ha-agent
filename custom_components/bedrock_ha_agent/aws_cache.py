"""Shared in-memory cache for AWS discovery APIs.

`bedrock:ListInferenceProfiles` and `polly:DescribeVoices` are called from both
the config/options flow and the TTS entity. Without caching, every options-flow
open and every HA TTS pipeline setup triggers a live AWS round-trip. This module
caches the results at the integration level (``hass.data[DOMAIN]["aws_cache"]``)
with a 1-hour TTL, keyed by ``(access_key_id, region, api_tag, extras)``. Secret
keys and session tokens are never part of the cache key.

Concurrent callers for the same key coalesce via a per-key ``asyncio.Lock``
using double-checked locking. AWS errors propagate; the cache is never poisoned
with an exception-state entry.

Invalidation is credential-scoped. ``_async_update_listener`` in ``__init__.py``
only calls ``invalidate()`` when the stored credential fingerprint actually
changes, so ordinary options-saves (which always trigger ``async_reload``) do
not flush the cache.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Mapping

from homeassistant.core import HomeAssistant

from .aws_session import build_session
from .const import (
    CONF_AWS_ACCESS_KEY_ID,
    CONF_AWS_SECRET_ACCESS_KEY,
    CONF_AWS_SESSION_TOKEN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CACHE_TTL_SECONDS: int = 3600

_STORE_KEY = "aws_cache"
_LOCKS_KEY = "aws_cache_locks"

_API_BEDROCK_PROFILES = "bedrock:list_inference_profiles"
_API_POLLY_VOICES = "polly:describe_voices"


@dataclass(frozen=True)
class VoiceInfo:
    """One Polly voice, in a provider-neutral shape.

    ``supported_engines`` preserves the set of engines Polly returned for the
    voice so callers can filter client-side if they ever need to (today the
    filter happens in the boto3 call via ``engine`` kwarg).
    """

    voice_id: str
    name: str
    gender: str | None
    supported_engines: tuple[str, ...]


def _get_store(hass: HomeAssistant) -> dict[tuple[Any, ...], tuple[float, Any]]:
    """Return the cache dict, creating it on first use."""
    domain_bucket = hass.data.setdefault(DOMAIN, {})
    store: dict[tuple[Any, ...], tuple[float, Any]] = domain_bucket.setdefault(
        _STORE_KEY, {}
    )
    return store


def _get_locks(hass: HomeAssistant) -> dict[tuple[Any, ...], asyncio.Lock]:
    """Return the per-key lock dict, creating it on first use.

    Locks themselves are created lazily on first acquisition so that
    ``asyncio.Lock()`` runs inside a running event loop.
    """
    domain_bucket = hass.data.setdefault(DOMAIN, {})
    locks: dict[tuple[Any, ...], asyncio.Lock] = domain_bucket.setdefault(
        _LOCKS_KEY, {}
    )
    return locks


def _lock_for(hass: HomeAssistant, key: tuple[Any, ...]) -> asyncio.Lock:
    locks = _get_locks(hass)
    lock = locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        locks[key] = lock
    return lock


def _credentials_triplet(
    credentials: Mapping[str, Any],
) -> tuple[str, str, str | None]:
    """Return the (access_key_id, secret_key, session_token) triplet.

    Pulled out so test assertions can verify the key-building code only uses
    ``access_key_id`` — the other two must never leak into ``_build_key``.
    """
    return (
        credentials[CONF_AWS_ACCESS_KEY_ID],
        credentials[CONF_AWS_SECRET_ACCESS_KEY],
        credentials.get(CONF_AWS_SESSION_TOKEN),
    )


def _build_key(
    credentials: Mapping[str, Any],
    region: str,
    api_tag: str,
    extras: tuple[Any, ...] = (),
) -> tuple[Any, ...]:
    """Build a cache key. Deliberately excludes secret key and session token."""
    access_key_id = credentials[CONF_AWS_ACCESS_KEY_ID]
    return (access_key_id, region, api_tag, extras)


async def _cached_or_fetch(
    hass: HomeAssistant,
    key: tuple[Any, ...],
    fetch: Any,
) -> Any:
    """Return cached result if fresh, otherwise run ``fetch`` under a lock."""
    store = _get_store(hass)
    now = time.monotonic()

    cached = store.get(key)
    if cached is not None and (now - cached[0]) < CACHE_TTL_SECONDS:
        _LOGGER.debug("aws_cache hit api=%s region=%s", key[2], key[1])
        return cached[1]

    lock = _lock_for(hass, key)
    async with lock:
        # Double-checked locking: another coroutine may have populated the
        # cache while we waited on the lock.
        now = time.monotonic()
        cached = store.get(key)
        if cached is not None and (now - cached[0]) < CACHE_TTL_SECONDS:
            _LOGGER.debug(
                "aws_cache hit-after-wait api=%s region=%s", key[2], key[1]
            )
            return cached[1]

        _LOGGER.debug("aws_cache miss api=%s region=%s", key[2], key[1])
        result = await hass.async_add_executor_job(fetch)
        store[key] = (time.monotonic(), result)
        return result


async def async_list_inference_profiles(
    hass: HomeAssistant,
    *,
    credentials: Mapping[str, Any],
    region: str,
) -> list[str]:
    """Return sorted, active Anthropic inference profile IDs for the account/region.

    Cached per ``(access_key_id, region)`` for ``CACHE_TTL_SECONDS``. Raises
    on AWS errors so callers can fall back to a hardcoded list.
    """
    key = _build_key(credentials, region, _API_BEDROCK_PROFILES)
    access_key, secret_key, session_token = _credentials_triplet(credentials)

    def _fetch() -> list[str]:
        session = build_session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            aws_session_token=session_token,
            aws_region=region,
        )
        client = session.client("bedrock")

        profile_ids: list[str] = []
        paginator = client.get_paginator("list_inference_profiles")
        for page in paginator.paginate():
            for summary in page.get("inferenceProfileSummaries", []):
                profile_id = summary.get("inferenceProfileId")
                status = summary.get("status")
                if not profile_id or status != "ACTIVE":
                    continue
                if "anthropic" not in profile_id.lower():
                    continue
                profile_ids.append(profile_id)

        return sorted(set(profile_ids))

    result: list[str] = await _cached_or_fetch(hass, key, _fetch)
    return result


async def async_list_polly_voices(
    hass: HomeAssistant,
    *,
    credentials: Mapping[str, Any],
    region: str,
    language: str | None = None,
    engine: str | None = None,
) -> list[VoiceInfo]:
    """Return Polly voices for the account/region, sorted by name.

    ``language=None`` lists the full catalog; ``language=X`` passes
    ``LanguageCode=X`` to Polly. ``engine`` filters to voices whose
    ``SupportedEngines`` include the given engine. The cache distinguishes
    ``(language=None)`` from ``(language=X)`` — the full catalog is **not**
    client-side-filtered to answer language-scoped queries.
    """
    key = _build_key(
        credentials, region, _API_POLLY_VOICES, (engine, language)
    )
    access_key, secret_key, session_token = _credentials_triplet(credentials)

    def _fetch() -> list[VoiceInfo]:
        session = build_session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            aws_session_token=session_token,
            aws_region=region,
        )
        polly = session.client("polly")
        voices: list[VoiceInfo] = []
        paginator = polly.get_paginator("describe_voices")
        paginate_kwargs: dict[str, Any] = {}
        if language is not None:
            paginate_kwargs["LanguageCode"] = language
        for page in paginator.paginate(**paginate_kwargs):
            for voice in page.get("Voices", []):
                voice_id = voice.get("Id")
                if not voice_id:
                    continue
                supported = tuple(voice.get("SupportedEngines") or ())
                if engine is not None and engine not in supported:
                    continue
                voices.append(
                    VoiceInfo(
                        voice_id=voice_id,
                        name=voice.get("Name", voice_id),
                        gender=voice.get("Gender"),
                        supported_engines=supported,
                    )
                )
        return sorted(voices, key=lambda v: v.name.lower())

    result: list[VoiceInfo] = await _cached_or_fetch(hass, key, _fetch)
    return result


def invalidate(
    hass: HomeAssistant,
    *,
    access_key_id: str,
    region: str | None = None,
) -> None:
    """Drop cached entries matching the given access key (and region if set)."""
    store = _get_store(hass)
    locks = _get_locks(hass)

    to_drop = [
        key
        for key in store
        if key[0] == access_key_id and (region is None or key[1] == region)
    ]
    for key in to_drop:
        store.pop(key, None)
        locks.pop(key, None)

    if to_drop:
        _LOGGER.debug(
            "aws_cache invalidate access_key_id=%s region=%s count=%d",
            access_key_id,
            region,
            len(to_drop),
        )


def credential_fingerprint(credentials: Mapping[str, Any]) -> str:
    """Return a stable fingerprint for credentials, for change-detection.

    Used by ``_async_update_listener`` to decide whether to invalidate the
    cache. ``hash`` is stable within a single Python process, which is all
    the caller needs.
    """
    return str(
        hash(
            (
                credentials.get(CONF_AWS_ACCESS_KEY_ID),
                credentials.get(CONF_AWS_SECRET_ACCESS_KEY),
                credentials.get(CONF_AWS_SESSION_TOKEN),
            )
        )
    )
