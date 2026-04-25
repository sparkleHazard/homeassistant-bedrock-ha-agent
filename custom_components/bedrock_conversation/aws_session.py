"""Shared AWS session/client factory for the bedrock_conversation integration.

The config-flow, Bedrock client, and Polly TTS all need to build a ``boto3``
session from the same credential fields. Centralising that here keeps the
constructor call shape consistent (session token handling, region fallback)
and makes it easy to swap in a different credential source later.
"""
from __future__ import annotations

from typing import Any, Mapping

import boto3

from .const import (
    CONF_AWS_ACCESS_KEY_ID,
    CONF_AWS_REGION,
    CONF_AWS_SECRET_ACCESS_KEY,
    CONF_AWS_SESSION_TOKEN,
    DEFAULT_AWS_REGION,
)


def build_session(
    *,
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: str | None = None,
    aws_region: str | None = None,
) -> boto3.Session:
    """Return a ``boto3.Session`` for the given credentials.

    Empty session-token strings are normalised to ``None`` because boto3
    distinguishes "no token provided" from "empty-string token" and the
    latter causes signing failures.
    """
    return boto3.Session(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        aws_session_token=aws_session_token or None,
        region_name=aws_region or DEFAULT_AWS_REGION,
    )


def session_from_entry_data(
    data: Mapping[str, Any], region_override: str | None = None
) -> boto3.Session:
    """Return a session built from a config entry's ``data`` mapping.

    ``data`` may be ``ConfigEntry.data`` or a merged
    ``{**entry.data, **entry.options}`` dict — any mapping carrying the
    ``CONF_AWS_*`` keys works. Pass ``region_override`` to force a
    different region (rare; the config-flow uses this to validate a
    region the user just typed in before committing it).
    """
    return build_session(
        aws_access_key_id=data[CONF_AWS_ACCESS_KEY_ID],
        aws_secret_access_key=data[CONF_AWS_SECRET_ACCESS_KEY],
        aws_session_token=data.get(CONF_AWS_SESSION_TOKEN),
        aws_region=region_override or data.get(CONF_AWS_REGION, DEFAULT_AWS_REGION),
    )
