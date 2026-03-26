import asyncio
import json
import logging
import os
import uuid

import torchaudio as ta
from pydub import AudioSegment

from podcast.config import settings
from podcast.database import get_session
from podcast.models import Episode, PodcastSettings

logger = logging.getLogger(__name__)

# Module-level model cache — loaded once, kept in memory
_model = None
_sample_rate = None


def _get_model():
    global _model, _sample_rate
    if _model is None:
        logger.info("Loading Chatterbox TTS model (this may take a moment)...")
        from chatterbox.tts import ChatterboxTTS

        _model = ChatterboxTTS.from_pretrained(device="cpu")
        _sample_rate = _model.sr
        logger.info("Chatterbox TTS model loaded (sample rate: %d)", _sample_rate)
    return _model, _sample_rate


def _get_voice_ref_path(host: str, host_a_name: str, voice_ref_a: str | None, voice_ref_b: str | None) -> str | None:
    """Get the voice reference path for a host."""
    if host == host_a_name:
        if voice_ref_a and os.path.exists(voice_ref_a):
            return voice_ref_a
        default = "voice_refs/host_a.wav"
        return default if os.path.exists(default) else None
    else:
        if voice_ref_b and os.path.exists(voice_ref_b):
            return voice_ref_b
        default = "voice_refs/host_b.wav"
        return default if os.path.exists(default) else None


def _synthesize_segments(
    segments: list[dict],
    episode_id: uuid.UUID,
    host_a: str,
    voice_ref_a: str | None,
    voice_ref_b: str | None,
) -> None:
    """Synchronous TTS generation — runs in a thread to avoid blocking the event loop."""
    segments_dir = os.path.join(settings.audio_dir, "segments", str(episode_id))
    os.makedirs(segments_dir, exist_ok=True)

    model, sample_rate = _get_model()

    # Generate each segment
    for i, segment in enumerate(segments):
        segment_path = os.path.join(segments_dir, f"{i:04d}.wav")

        # Skip if already generated (resume support)
        if os.path.exists(segment_path):
            logger.info("Segment %d already exists, skipping", i)
            continue

        text = segment["text"]
        voice_ref = _get_voice_ref_path(
            segment["speaker"], host_a, voice_ref_a, voice_ref_b
        )

        logger.info(
            "Generating segment %d/%d (%s): %s...",
            i + 1,
            len(segments),
            segment["speaker"],
            text[:50],
        )

        kwargs = {"text": text}
        if voice_ref:
            kwargs["audio_prompt_path"] = voice_ref

        wav = model.generate(**kwargs)
        ta.save(segment_path, wav, sample_rate)

    # Concatenate all segments with 300ms silence between them
    logger.info("Concatenating %d segments", len(segments))
    silence = AudioSegment.silent(duration=300, frame_rate=sample_rate)
    combined = AudioSegment.empty()

    for i in range(len(segments)):
        segment_path = os.path.join(segments_dir, f"{i:04d}.wav")
        segment_audio = AudioSegment.from_wav(segment_path)
        if len(combined) > 0:
            combined += silence
        combined += segment_audio

    # Save concatenated WAV
    output_wav = os.path.join(settings.audio_dir, f"{episode_id}.wav")
    combined.export(output_wav, format="wav")

    logger.info(
        "TTS complete for episode %s: %.1f seconds",
        episode_id,
        len(combined) / 1000,
    )


async def synthesize_speech(episode_id: uuid.UUID) -> None:
    """Convert transcript segments to speech using Chatterbox TTS."""
    # Read data from DB
    async with get_session() as db:
        episode = await db.get(Episode, episode_id)
        if not episode or not episode.transcript:
            raise ValueError(f"Episode {episode_id} not found or has no transcript")

        podcast_settings = await db.get(PodcastSettings, 1)
        host_a = podcast_settings.host_a_name if podcast_settings else "Alex"
        voice_ref_a = podcast_settings.voice_ref_a_path if podcast_settings else None
        voice_ref_b = podcast_settings.voice_ref_b_path if podcast_settings else None
        segments = json.loads(episode.transcript)

    logger.info("Synthesizing %d segments for episode %s", len(segments), episode_id)

    # Run CPU-heavy TTS in a thread so signal handling still works
    await asyncio.to_thread(
        _synthesize_segments, segments, episode_id, host_a, voice_ref_a, voice_ref_b
    )
