"""Tests for podcast.services.tts."""

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from podcast.services.tts import _read_voice_ref_bytes, get_tts_progress
from tests.conftest import make_episode, make_mock_get_session, make_settings


class TestReadVoiceRefBytes:
    def test_reads_from_db_path(self, tmp_path):
        """When db_path is a valid filename within voice_refs_dir, should read from it."""
        voice_file = tmp_path / "voice.wav"
        voice_bytes = b"fake wav data"
        voice_file.write_bytes(voice_bytes)

        with patch("podcast.services.tts.settings") as mock_settings:
            mock_settings.voice_refs_dir = str(tmp_path)
            result = _read_voice_ref_bytes("voice.wav", "default.wav")
            assert result == voice_bytes

    def test_rejects_path_traversal(self, tmp_path):
        """db_path with path traversal should be rejected."""
        with patch("podcast.services.tts.settings") as mock_settings:
            mock_settings.voice_refs_dir = str(tmp_path)
            result = _read_voice_ref_bytes("../../etc/passwd", "default.wav")
            assert result is None

    def test_falls_back_to_default(self, tmp_path):
        """When db_path doesn't exist, should try default."""
        default_file = tmp_path / "default.wav"
        default_bytes = b"default wav"
        default_file.write_bytes(default_bytes)

        with patch("podcast.services.tts.settings") as mock_settings:
            mock_settings.voice_refs_dir = str(tmp_path)
            result = _read_voice_ref_bytes("nonexistent.wav", "default.wav")
            assert result == default_bytes

    def test_returns_none_when_not_found(self):
        """When neither path exists, should return None."""
        result = _read_voice_ref_bytes(None, "nonexistent.wav")
        assert result is None


class TestGetTtsProgress:
    def test_returns_none(self):
        """Progress should always return None since Modal TTS has no local progress file."""
        result = get_tts_progress(uuid.uuid4())
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

    async def test_calls_modal_function(self):
        """synthesize_speech should call Modal's generate_tts function."""
        segments = [{"speaker": "Alex", "text": "Hello"}]
        ep = make_episode(transcript=json.dumps(segments))
        settings = make_settings(user_id=ep.user_id)

        db = AsyncMock()
        # db.get() returns the episode
        db.get = AsyncMock(return_value=ep)
        # db.execute() returns settings for the user_id query
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = settings
        db.execute = AsyncMock(return_value=mock_result)

        mock_result = {
            "wav_bytes": b"fake audio",
            "metrics": {"duration_seconds": 1.0, "segment_count": 1},
        }

        with patch("podcast.services.tts.get_session", make_mock_get_session(db)):
            with patch("podcast.services.tts.modal.Function.from_name") as mock_fn:
                mock_modal_func = AsyncMock()
                mock_modal_func.remote.aio.return_value = mock_result
                mock_fn.return_value = mock_modal_func

                with patch("podcast.services.tts.os.makedirs"):
                    with patch("builtins.open", create=True) as mock_open:
                        from podcast.services.tts import synthesize_speech

                        result = await synthesize_speech(ep.id)

        # Verify Modal function was called
        mock_fn.assert_called_once_with("podcast-tts", "generate_tts")
        mock_modal_func.remote.aio.assert_awaited_once()

        # Verify result is the metrics
        assert result == mock_result["metrics"]

        # Verify WAV was written to disk
        mock_open.assert_called()
