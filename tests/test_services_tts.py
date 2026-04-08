"""Tests for podcast.services.tts (Modal-based TTS)."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from podcast.services.tts import _read_voice_ref_bytes, get_tts_progress
from tests.conftest import make_episode, make_mock_get_session, make_settings


class TestGetTtsProgress:
    def test_returns_none_when_no_file(self, tmp_path):
        with patch("podcast.services.tts.settings") as mock_settings:
            mock_settings.audio_dir = str(tmp_path)
            result = get_tts_progress(uuid.uuid4())
        assert result is None

    def test_returns_progress_when_file_exists(self, tmp_path):
        episode_id = uuid.uuid4()
        segments_dir = tmp_path / "segments" / str(episode_id)
        segments_dir.mkdir(parents=True)

        progress = {
            "segments_completed": 3,
            "total_segments": 10,
            "audio_duration_seconds": 15.0,
        }
        (segments_dir / "progress.json").write_text(json.dumps(progress))

        with patch("podcast.services.tts.settings") as mock_settings:
            mock_settings.audio_dir = str(tmp_path)
            result = get_tts_progress(episode_id)

        assert result == progress


class TestReadVoiceRefBytes:
    def test_reads_from_db_path(self, tmp_path):
        wav_file = tmp_path / "custom.wav"
        wav_file.write_bytes(b"fake-wav-data")

        result = _read_voice_ref_bytes(str(wav_file), "host_a.wav")
        assert result == b"fake-wav-data"

    def test_falls_back_to_default(self, tmp_path):
        default_file = tmp_path / "host_a.wav"
        default_file.write_bytes(b"default-wav")

        with patch("podcast.services.tts.settings") as mock_settings:
            mock_settings.voice_refs_dir = str(tmp_path)
            result = _read_voice_ref_bytes(None, "host_a.wav")

        assert result == b"default-wav"

    def test_db_path_not_found_falls_back(self, tmp_path):
        default_file = tmp_path / "host_b.wav"
        default_file.write_bytes(b"default-wav")

        with patch("podcast.services.tts.settings") as mock_settings:
            mock_settings.voice_refs_dir = str(tmp_path)
            result = _read_voice_ref_bytes("/nonexistent/path.wav", "host_b.wav")

        assert result == b"default-wav"

    def test_returns_none_when_nothing_found(self):
        with patch("podcast.services.tts.settings") as mock_settings:
            mock_settings.voice_refs_dir = "/nonexistent"
            result = _read_voice_ref_bytes(None, "host_a.wav")

        assert result is None


class TestSynthesizeSpeech:
    async def test_episode_not_found_raises(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with patch("podcast.services.tts.get_session", make_mock_get_session(db)):
            from podcast.services.tts import synthesize_speech

            with pytest.raises(ValueError, match="not found"):
                await synthesize_speech(uuid.uuid4())

    async def test_no_transcript_raises(self):
        ep = make_episode(transcript=None)
        db = AsyncMock()
        db.get = AsyncMock(return_value=ep)

        with patch("podcast.services.tts.get_session", make_mock_get_session(db)):
            from podcast.services.tts import synthesize_speech

            with pytest.raises(ValueError, match="no transcript"):
                await synthesize_speech(ep.id)

    async def test_calls_modal_and_saves_wav(self, tmp_path):
        """synthesize_speech should call Modal generate_tts and save the WAV."""
        segments = [{"speaker": "Alex", "text": "Hello"}]
        ep = make_episode(transcript=json.dumps(segments))
        settings_obj = make_settings()

        db = AsyncMock()

        async def mock_get(model, id_val):
            from podcast.models import Episode

            if model is Episode or id_val == ep.id:
                return ep
            return settings_obj

        db.get = AsyncMock(side_effect=mock_get)

        mock_metrics = {
            "duration_seconds": 1.0,
            "segment_count": 1,
            "segments_generated": 1,
            "audio_duration_seconds": 5.0,
            "avg_segment_seconds": 1.0,
            "realtime_factor": 5.0,
            "segment_durations": [1.0],
            "gpu": "T4",
        }
        mock_result = {"wav_bytes": b"fake-wav-bytes", "metrics": mock_metrics}

        # Mock the Modal function lookup and remote call
        mock_fn = MagicMock()
        mock_fn.remote = MagicMock()
        mock_fn.remote.aio = AsyncMock(return_value=mock_result)

        with patch("podcast.services.tts.get_session", make_mock_get_session(db)):
            with patch(
                "podcast.services.tts._read_voice_ref_bytes", return_value=b"voice"
            ):
                with patch("podcast.services.tts.modal") as mock_modal:
                    mock_modal.Function.from_name.return_value = mock_fn
                    with patch("podcast.services.tts.settings") as mock_settings:
                        mock_settings.audio_dir = str(tmp_path)
                        mock_settings.voice_refs_dir = "/app/voice_refs"

                        from podcast.services.tts import synthesize_speech

                        result = await synthesize_speech(ep.id)

        # Verify Modal was called correctly
        mock_modal.Function.from_name.assert_called_once_with(
            "podcast-tts", "generate_tts"
        )
        mock_fn.remote.aio.assert_awaited_once()

        # Verify WAV was saved to disk
        wav_path = tmp_path / f"{ep.id}.wav"
        assert wav_path.exists()
        assert wav_path.read_bytes() == b"fake-wav-bytes"

        # Verify metrics returned unchanged
        assert result == mock_metrics
