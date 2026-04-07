"""TTS service using Modal's GPU-accelerated Chatterbox."""

import json
import logging
import os
import uuid

import modal

from podcast.config import settings
from podcast.database import get_session
from podcast.models import Episode, PodcastSettings

logger = logging.getLogger(__name__)


def get_tts_progress(episode_id: uuid.UUID) -> dict | None:
    """Read TTS progress from the progress file, if it exists.

    Note: Modal TTS doesn't write progress files (GPU work is remote).
    Returns None since there's no segment-by-segment progress to report.
    Callers should handle gracefully (show spinner without progress).
    """
    return None


def _read_voice_ref_bytes(db_path: str | None, default_filename: str) -> bytes | None:
    """Read voice reference WAV file as bytes.

    Args:
        db_path: Path from database (may be None or nonexistent)
        default_filename: Default filename in voice_refs dir (e.g. "host_a.wav")

    Returns:
        WAV bytes if file exists, None otherwise
    """
    # Try database path first
    if db_path and os.path.exists(db_path):
        logger.debug("Reading voice ref from DB path: %s", db_path)
        with open(db_path, "rb") as f:
            return f.read()

    # Try default path
    default_path = os.path.join(settings.voice_refs_dir, default_filename)
    if os.path.exists(default_path):
        logger.debug("Reading voice ref from default path: %s", default_path)
        with open(default_path, "rb") as f:
            return f.read()

    logger.warning(
        "No voice ref found, tried: db=%s, default=%s", db_path, default_path
    )
    return None


async def synthesize_speech(episode_id: uuid.UUID) -> dict:
    """Convert transcript segments to speech using Modal GPU TTS.

    Returns metrics dict with generation stats.
    """
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

    # Read voice ref bytes
    voice_ref_a_bytes = _read_voice_ref_bytes(voice_ref_a, "host_a.wav")
    voice_ref_b_bytes = _read_voice_ref_bytes(voice_ref_b, "host_b.wav")

    # Call Modal function
    try:
        fn = modal.Function.from_name("podcast-tts", "generate_tts")
        result = await fn.remote.aio(
            segments=segments,
            host_a_name=host_a,
            voice_ref_a_bytes=voice_ref_a_bytes,
            voice_ref_b_bytes=voice_ref_b_bytes,
        )
    except Exception as e:
        logger.error("Modal TTS call failed: %s", e)
        raise

    # Write WAV bytes to disk
    output_wav = os.path.join(settings.audio_dir, f"{episode_id}.wav")
    os.makedirs(settings.audio_dir, exist_ok=True)
    with open(output_wav, "wb") as f:
        f.write(result["wav_bytes"])
    logger.info("Wrote audio file: %s", output_wav)

    return result["metrics"]
