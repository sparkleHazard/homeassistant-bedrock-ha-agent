"""Amazon Transcribe speech-to-text platform for the Bedrock Conversation integration."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable

from amazon_transcribe.auth import StaticCredentialResolver
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent

from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    SpeechMetadata,
    SpeechResult,
    SpeechResultState,
    SpeechToTextEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_AWS_ACCESS_KEY_ID,
    CONF_AWS_REGION,
    CONF_AWS_SECRET_ACCESS_KEY,
    CONF_AWS_SESSION_TOKEN,
    DEFAULT_AWS_REGION,
)

_LOGGER = logging.getLogger(__name__)

# Transcribe's streaming language codes.
SUPPORTED_LANGUAGES = [
    "en-US", "en-GB", "en-AU", "en-IN", "en-IE", "en-AB", "en-NZ", "en-WL", "en-ZA",
    "de-DE", "de-CH",
    "fr-FR", "fr-CA",
    "es-ES", "es-US",
    "it-IT",
    "pt-BR", "pt-PT",
    "nl-NL",
    "ja-JP", "ko-KR",
    "zh-CN", "zh-TW",
    "ru-RU",
    "ar-AE", "ar-SA",
    "hi-IN",
    "id-ID", "ms-MY", "th-TH", "tr-TR", "vi-VN",
    "he-IL",
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Transcribe STT entity from a config entry."""
    async_add_entities([BedrockTranscribeSTTEntity(config_entry)])


class _TranscriptCollector(TranscriptResultStreamHandler):
    """Accumulate final transcript segments from the streaming response."""

    def __init__(self, output_stream) -> None:
        super().__init__(output_stream)
        self.segments: list[str] = []

    async def handle_transcript_event(self, transcript_event: TranscriptEvent) -> None:
        for result in transcript_event.transcript.results:
            # Ignore partial results; only append finalised segments.
            if result.is_partial or not result.alternatives:
                continue
            text = result.alternatives[0].transcript
            if text:
                self.segments.append(text)


class BedrockTranscribeSTTEntity(SpeechToTextEntity):
    """Amazon Transcribe speech-to-text entity."""

    _attr_has_entity_name = True
    _attr_name = "AWS Transcribe"

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the Transcribe STT entity."""
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_transcribe_stt"

    @property
    def supported_languages(self) -> list[str]:
        return SUPPORTED_LANGUAGES

    @property
    def supported_formats(self) -> list[AudioFormats]:
        return [AudioFormats.WAV, AudioFormats.OGG]

    @property
    def supported_codecs(self) -> list[AudioCodecs]:
        return [AudioCodecs.PCM]

    @property
    def supported_bit_rates(self) -> list[AudioBitRates]:
        return [AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[AudioSampleRates]:
        return [AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self) -> list[AudioChannels]:
        return [AudioChannels.CHANNEL_MONO]

    async def async_process_audio_stream(
        self, metadata: SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> SpeechResult:
        """Stream audio to Amazon Transcribe and return the recognised transcript."""
        merged = {**self._config_entry.data, **self._config_entry.options}
        region = merged.get(CONF_AWS_REGION, DEFAULT_AWS_REGION)
        language = metadata.language if metadata.language in SUPPORTED_LANGUAGES else "en-US"

        resolver = StaticCredentialResolver(
            access_key_id=merged[CONF_AWS_ACCESS_KEY_ID],
            secret_access_key=merged[CONF_AWS_SECRET_ACCESS_KEY],
            session_token=merged.get(CONF_AWS_SESSION_TOKEN) or None,
        )
        client = TranscribeStreamingClient(region=region, credential_resolver=resolver)

        try:
            transcribe_stream = await client.start_stream_transcription(
                language_code=language,
                media_sample_rate_hz=int(metadata.sample_rate),
                media_encoding="pcm",
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to start Transcribe streaming")
            return SpeechResult(None, SpeechResultState.ERROR)

        collector = _TranscriptCollector(transcribe_stream.output_stream)

        async def _pump_audio() -> None:
            try:
                async for chunk in stream:
                    if chunk:
                        await transcribe_stream.input_stream.send_audio_event(
                            audio_chunk=chunk
                        )
            finally:
                await transcribe_stream.input_stream.end_stream()

        try:
            await asyncio.gather(_pump_audio(), collector.handle_events())
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Transcribe streaming error")
            return SpeechResult(None, SpeechResultState.ERROR)

        transcript = " ".join(collector.segments).strip()
        _LOGGER.debug(
            "Transcribe finished (language=%s, segments=%d, len=%d)",
            language, len(collector.segments), len(transcript),
        )
        return SpeechResult(transcript, SpeechResultState.SUCCESS)
