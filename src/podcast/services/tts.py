import asyncio
import json
import logging
import os
import time
import uuid

import torchaudio as ta
from pydub import AudioSegment

from podcast.config import settings
from podcast.database import get_session
from podcast.models import Episode, PodcastSettings

logger = logging.getLogger(__name__)


def _write_progress(
    segments_dir: str,
    segments_completed: int,
    total_segments: int,
    audio_duration_seconds: float,
):
    """Write progress file to disk for the web layer to read."""
    progress_path = os.path.join(segments_dir, "progress.json")
    progress = {
        "segments_completed": segments_completed,
        "total_segments": total_segments,
        "audio_duration_seconds": round(audio_duration_seconds, 1),
    }
    # Atomic write: write to temp file then rename to avoid partial reads
    tmp_path = progress_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(progress, f)
    os.replace(tmp_path, progress_path)


def get_tts_progress(episode_id: uuid.UUID) -> dict | None:
    """Read TTS progress from the progress file, if it exists.

    Returns dict with keys: segments_completed, total_segments, audio_duration_seconds
    or None if no progress file exists.
    """
    segments_dir = os.path.join(settings.audio_dir, "segments", str(episode_id))
    progress_path = os.path.join(segments_dir, "progress.json")
    try:
        with open(progress_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


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
) -> dict:
    """Synchronous TTS generation — runs in a thread. Returns metrics dict."""
    segments_dir = os.path.join(settings.audio_dir, "segments", str(episode_id))
    os.makedirs(segments_dir, exist_ok=True)

    model, sample_rate = _get_model()

    segment_durations = []
    total_gen_start = time.monotonic()
    cumulative_audio_seconds = 0.0

    # Generate each segment
    for i, segment in enumerate(segments):
        segment_path = os.path.join(segments_dir, f"{i:04d}.wav")

        # Skip if already generated (resume support)
        if os.path.exists(segment_path):
            logger.info("Segment %d already exists, skipping", i)
            segment_durations.append(None)  # unknown for skipped
            info = ta.info(segment_path)
            cumulative_audio_seconds += info.num_frames / info.sample_rate
            _write_progress(segments_dir, i + 1, len(segments), cumulative_audio_seconds)
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

        seg_start = time.monotonic()
        wav = model.generate(**kwargs)
        seg_duration = time.monotonic() - seg_start
        segment_durations.append(round(seg_duration, 2))

        ta.save(segment_path, wav, sample_rate)
        cumulative_audio_seconds += wav.shape[-1] / sample_rate
        _write_progress(segments_dir, i + 1, len(segments), cumulative_audio_seconds)
        logger.info("Segment %d generated in %.1fs", i, seg_duration)

    total_gen_duration = time.monotonic() - total_gen_start

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

    # Clean up progress file now that TTS is complete
    progress_path = os.path.join(segments_dir, "progress.json")
    if os.path.exists(progress_path):
        os.remove(progress_path)

    audio_duration = len(combined) / 1000
    generated = [d for d in segment_durations if d is not None]
    avg_per_segment = sum(generated) / len(generated) if generated else 0

    logger.info(
        "TTS complete for episode %s: %.1fs audio, %.1fs generation (%.1fx realtime)",
        episode_id,
        audio_duration,
        total_gen_duration,
        audio_duration / total_gen_duration if total_gen_duration > 0 else 0,
    )

    return {
        "duration_seconds": round(total_gen_duration, 2),
        "segment_count": len(segments),
        "segments_generated": len(generated),
        "audio_duration_seconds": round(audio_duration, 2),
        "avg_segment_seconds": round(avg_per_segment, 2),
        "realtime_factor": round(
            audio_duration / total_gen_duration if total_gen_duration > 0 else 0, 2
        ),
        "segment_durations": segment_durations,
    }


async def synthesize_speech(episode_id: uuid.UUID) -> dict:
    """Convert transcript segments to speech using Chatterbox TTS. Returns metrics dict."""
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
    return await asyncio.to_thread(
        _synthesize_segments, segments, episode_id, host_a, voice_ref_a, voice_ref_b
    )
