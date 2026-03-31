"""Tests for podcast.services.tts."""

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from podcast.services.tts import _get_voice_ref_path
from tests.conftest import make_episode, make_mock_get_session, make_settings


class TestGetVoiceRefPath:
    def test_host_a_with_custom_ref(self):
        with patch("podcast.services.tts.os.path.exists", return_value=True):
            result = _get_voice_ref_path("Alex", "Alex", "/custom/a.wav", "/custom/b.wav")
        assert result == "/custom/a.wav"

    def test_host_b_with_custom_ref(self):
        with patch("podcast.services.tts.os.path.exists", return_value=True):
            result = _get_voice_ref_path("Sam", "Alex", "/custom/a.wav", "/custom/b.wav")
        assert result == "/custom/b.wav"

    def test_host_a_custom_ref_not_exists_fallback(self):
        """When custom ref doesn't exist, fall back to default."""
        def exists_side_effect(path):
            if path == "/custom/a.wav":
                return False
            if path == "voice_refs/host_a.wav":
                return True
            return False

        with patch("podcast.services.tts.os.path.exists", side_effect=exists_side_effect):
            result = _get_voice_ref_path("Alex", "Alex", "/custom/a.wav", None)
        assert result == "voice_refs/host_a.wav"

    def test_host_b_custom_ref_not_exists_fallback(self):
        def exists_side_effect(path):
            if path == "/custom/b.wav":
                return False
            if path == "voice_refs/host_b.wav":
                return True
            return False

        with patch("podcast.services.tts.os.path.exists", side_effect=exists_side_effect):
            result = _get_voice_ref_path("Sam", "Alex", None, "/custom/b.wav")
        assert result == "voice_refs/host_b.wav"

    def test_host_a_no_ref_no_default(self):
        with patch("podcast.services.tts.os.path.exists", return_value=False):
            result = _get_voice_ref_path("Alex", "Alex", None, None)
        assert result is None

    def test_host_b_no_ref_no_default(self):
        with patch("podcast.services.tts.os.path.exists", return_value=False):
            result = _get_voice_ref_path("Sam", "Alex", None, None)
        assert result is None

    def test_host_a_none_ref_uses_default(self):
        """When voice_ref_a is None, should try the default path."""
        def exists_side_effect(path):
            return path == "voice_refs/host_a.wav"

        with patch("podcast.services.tts.os.path.exists", side_effect=exists_side_effect):
            result = _get_voice_ref_path("Alex", "Alex", None, None)
        assert result == "voice_refs/host_a.wav"


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

    async def test_delegates_to_thread(self):
        """synthesize_speech should call _synthesize_segments via asyncio.to_thread."""
        segments = [{"speaker": "Alex", "text": "Hello"}]
        ep = make_episode(transcript=json.dumps(segments))
        settings = make_settings()

        db = AsyncMock()
        async def mock_get(model, id_val):
            from podcast.models import Episode, PodcastSettings
            if model is Episode or (hasattr(model, '__tablename__') and model.__tablename__ == 'episodes'):
                return ep
            return settings

        db.get = AsyncMock(side_effect=mock_get)

        mock_metrics = {"duration_seconds": 1.0, "segment_count": 1}

        with patch("podcast.services.tts.get_session", make_mock_get_session(db)):
            with patch("podcast.services.tts.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
                mock_thread.return_value = mock_metrics

                from podcast.services.tts import synthesize_speech

                result = await synthesize_speech(ep.id)

        mock_thread.assert_awaited_once()
        assert result == mock_metrics


class TestSynthesizeSegments:
    def test_skips_existing_segments(self):
        """Already-generated segments should be skipped (resume support)."""
        segments = [
            {"speaker": "Alex", "text": "Already done."},
            {"speaker": "Sam", "text": "New segment."},
        ]
        episode_id = uuid.uuid4()

        mock_model = MagicMock()
        mock_model.sr = 22050
        mock_model.generate.return_value = MagicMock()

        mock_audio_segment = MagicMock()
        mock_audio_segment.__len__ = MagicMock(return_value=5000)
        mock_audio_segment.__add__ = MagicMock(return_value=mock_audio_segment)
        mock_audio_segment.__iadd__ = MagicMock(return_value=mock_audio_segment)

        def exists_side_effect(path):
            # First segment exists, second doesn't
            return "0000.wav" in path

        with patch("podcast.services.tts._get_model", return_value=(mock_model, 22050)):
            with patch("podcast.services.tts.os.path.exists", side_effect=exists_side_effect):
                with patch("podcast.services.tts.os.makedirs"):
                    with patch("podcast.services.tts.ta.save"):
                        with patch("podcast.services.tts._write_progress"):
                            with patch("podcast.services.tts.AudioSegment") as mock_as:
                                mock_as.silent.return_value = mock_audio_segment
                                mock_as.empty.return_value = mock_audio_segment
                                mock_as.from_wav.return_value = mock_audio_segment

                                with patch("podcast.services.tts._get_voice_ref_path", return_value=None):
                                    with patch("podcast.services.tts.settings") as mock_settings:
                                        mock_settings.audio_dir = "/tmp/audio"

                                        from podcast.services.tts import _synthesize_segments

                                        metrics = _synthesize_segments(
                                            segments, episode_id, "Alex", None, None
                                        )

        # Model generate should only be called for the second segment
        assert mock_model.generate.call_count == 1
        assert metrics["segment_count"] == 2
        assert metrics["segments_generated"] == 1
