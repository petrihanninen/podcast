import asyncio
import logging
import os
import shutil
import time
import uuid

from pydub import AudioSegment
from sqlalchemy import func, select

from podcast.config import settings
from podcast.database import get_session
from podcast.models import Episode

logger = logging.getLogger(__name__)


def _encode(episode_id: uuid.UUID, audio_dir: str) -> tuple[str, int, int]:
    """Synchronous MP3 encoding — returns (filename, duration_seconds, file_size)."""
    wav_path = os.path.join(audio_dir, f"{episode_id}.wav")
    if not os.path.exists(wav_path):
        raise FileNotFoundError(f"WAV file not found: {wav_path}")

    mp3_filename = f"{episode_id}.mp3"
    mp3_path = os.path.join(audio_dir, mp3_filename)

    logger.info("Encoding MP3 for episode %s", episode_id)

    # Load WAV, convert to mono, export as MP3
    audio = AudioSegment.from_wav(wav_path)
    audio = audio.set_channels(1)  # Mono
    audio = audio.set_frame_rate(44100)
    audio.export(mp3_path, format="mp3", bitrate="128k")

    duration_seconds = int(len(audio) / 1000)
    file_size = os.path.getsize(mp3_path)

    # Clean up WAV and segments
    os.remove(wav_path)
    segments_dir = os.path.join(audio_dir, "segments", str(episode_id))
    if os.path.isdir(segments_dir):
        shutil.rmtree(segments_dir)

    return mp3_filename, duration_seconds, file_size


async def encode_mp3(episode_id: uuid.UUID) -> dict:
    """Convert WAV to MP3 and update episode metadata. Returns metrics dict."""
    # Look up user_id to determine audio directory
    async with get_session() as db:
        episode = await db.get(Episode, episode_id)
        if not episode:
            raise ValueError(f"Episode {episode_id} not found")
        user_id = episode.user_id

    user_audio_dir = os.path.join(settings.audio_dir, str(user_id))

    # Run encoding in a thread
    t0 = time.monotonic()
    mp3_filename, duration_seconds, file_size = await asyncio.to_thread(
        _encode, episode_id, user_audio_dir
    )
    encode_duration = time.monotonic() - t0

    # Update DB with results
    async with get_session() as db:
        episode = await db.get(Episode, episode_id)
        if not episode:
            raise ValueError(f"Episode {episode_id} not found")

        # Get next episode number (scoped per user)
        result = await db.execute(
            select(func.coalesce(func.max(Episode.episode_number), 0))
            .where(Episode.user_id == user_id)
        )
        next_number = result.scalar_one() + 1

        episode.audio_filename = mp3_filename
        episode.audio_duration_seconds = duration_seconds
        episode.audio_size_bytes = file_size
        episode.episode_number = next_number

    logger.info(
        "Encoding complete for episode %s: %ds, %d bytes, episode #%d (%.1fs)",
        episode_id,
        duration_seconds,
        file_size,
        next_number,
        encode_duration,
    )
    return {
        "duration_seconds": round(encode_duration, 2),
        "audio_duration_seconds": duration_seconds,
        "output_size_bytes": file_size,
    }
