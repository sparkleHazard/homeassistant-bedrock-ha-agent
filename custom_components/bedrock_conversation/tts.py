"""Amazon Polly text-to-speech platform for the Bedrock Conversation integration."""
from __future__ import annotations

import logging
import time
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from homeassistant.components.tts import (
    ATTR_VOICE,
    TextToSpeechEntity,
    TtsAudioType,
    Voice,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_AWS_ACCESS_KEY_ID,
    CONF_AWS_REGION,
    CONF_AWS_SECRET_ACCESS_KEY,
    CONF_AWS_SESSION_TOKEN,
    CONF_TTS_ENGINE,
    CONF_TTS_VOICE_ID,
    DEFAULT_AWS_REGION,
    DEFAULT_TTS_ENGINE,
    DEFAULT_TTS_VOICE_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Polly claims support for many languages; we forward whatever the pipeline
# gives us as the voice's language without pinning ourselves to a subset.
DEFAULT_LANGUAGE = "en-US"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Polly TTS entity from a config entry."""
    async_add_entities([BedrockPollyTTSEntity(config_entry)])


class BedrockPollyTTSEntity(TextToSpeechEntity):
    """Amazon Polly text-to-speech entity."""

    _attr_has_entity_name = True
    _attr_name = "AWS Polly"

    # Cache DescribeVoices results per language for VOICE_CACHE_TTL seconds so
    # the pipeline UI stays responsive without hammering the Polly API.
    VOICE_CACHE_TTL = 3600

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the Polly TTS entity."""
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_polly_tts"
        self._voices_cache: dict[str, tuple[float, list[Voice]]] = {}

    @property
    def default_language(self) -> str:
        """Return the default language."""
        return DEFAULT_LANGUAGE

    @property
    def supported_languages(self) -> list[str]:
        """Return the list of supported languages.

        Polly determines language from the voice, so we accept the common
        subset Polly supports. HA only uses this for pipeline routing.
        """
        return [
            "en-US", "en-GB", "en-AU", "en-IN", "en-ZA", "en-NZ",
            "de-DE", "fr-FR", "fr-CA", "es-ES", "es-MX", "es-US",
            "it-IT", "pt-BR", "pt-PT", "nl-NL", "ja-JP", "ko-KR",
            "cmn-CN", "ru-RU", "tr-TR", "sv-SE", "nb-NO", "da-DK",
            "pl-PL", "ro-RO", "cy-GB", "is-IS", "arb",
        ]

    @property
    def supported_options(self) -> list[str]:
        """Return list of supported options."""
        return [ATTR_VOICE, "engine"]

    async def async_get_supported_voices(
        self, language: str
    ) -> list[Voice] | None:
        """Return the list of Polly voices available for ``language``.

        Calls ``polly:DescribeVoices`` filtered by ``LanguageCode``. Results
        are cached per language for ``VOICE_CACHE_TTL`` seconds. Returns
        ``None`` on failure so Home Assistant can fall back to a free-form
        text input.
        """
        now = time.monotonic()
        cached = self._voices_cache.get(language)
        if cached and now - cached[0] < self.VOICE_CACHE_TTL:
            return cached[1]

        merged = {**self._config_entry.data, **self._config_entry.options}

        def _describe() -> list[Voice]:
            session = boto3.Session(
                aws_access_key_id=merged[CONF_AWS_ACCESS_KEY_ID],
                aws_secret_access_key=merged[CONF_AWS_SECRET_ACCESS_KEY],
                aws_session_token=merged.get(CONF_AWS_SESSION_TOKEN) or None,
                region_name=merged.get(CONF_AWS_REGION, DEFAULT_AWS_REGION),
            )
            polly = session.client("polly")
            voices: list[Voice] = []
            paginator = polly.get_paginator("describe_voices")
            for page in paginator.paginate(LanguageCode=language):
                for entry in page.get("Voices", []):
                    voice_id = entry.get("Id")
                    if not voice_id:
                        continue
                    name = entry.get("Name", voice_id)
                    gender = entry.get("Gender")
                    label = f"{name} ({gender})" if gender else name
                    voices.append(Voice(voice_id=voice_id, name=label))
            return sorted(voices, key=lambda v: v.name.lower())

        try:
            voices = await self.hass.async_add_executor_job(_describe)
        except (ClientError, BotoCoreError) as err:
            _LOGGER.warning(
                "Could not list Polly voices for language %s: %s", language, err
            )
            return None
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "Unexpected error listing Polly voices for language %s", language
            )
            return None

        self._voices_cache[language] = (now, voices)
        return voices

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any] | None = None
    ) -> TtsAudioType:
        """Synthesize speech for the given message."""
        merged = {**self._config_entry.data, **self._config_entry.options}
        opts = options or {}

        voice = opts.get(ATTR_VOICE) or merged.get(
            CONF_TTS_VOICE_ID, DEFAULT_TTS_VOICE_ID
        )
        engine = opts.get("engine") or merged.get(
            CONF_TTS_ENGINE, DEFAULT_TTS_ENGINE
        )

        def _synthesize() -> bytes:
            session = boto3.Session(
                aws_access_key_id=merged[CONF_AWS_ACCESS_KEY_ID],
                aws_secret_access_key=merged[CONF_AWS_SECRET_ACCESS_KEY],
                aws_session_token=merged.get(CONF_AWS_SESSION_TOKEN) or None,
                region_name=merged.get(CONF_AWS_REGION, DEFAULT_AWS_REGION),
            )
            polly = session.client("polly")
            response = polly.synthesize_speech(
                Engine=engine,
                OutputFormat="mp3",
                Text=message,
                VoiceId=voice,
            )
            with response["AudioStream"] as stream:
                return stream.read()

        try:
            audio = await self.hass.async_add_executor_job(_synthesize)
        except (ClientError, BotoCoreError) as err:
            _LOGGER.error(
                "Polly synthesis failed (voice=%s, engine=%s): %s",
                voice,
                engine,
                err,
            )
            return None, None
        except Exception:  # noqa: BLE001 — surface in logs but don't raise to the pipeline
            _LOGGER.exception("Unexpected Polly synthesis error")
            return None, None

        _LOGGER.debug(
            "Polly synthesized %d bytes (voice=%s, engine=%s, len=%d)",
            len(audio),
            voice,
            engine,
            len(message),
        )
        return "mp3", audio
