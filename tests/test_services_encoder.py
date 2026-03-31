"""Tests for podcast.services.encoder."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_episode, make_mock_get_session


class TestEncode:
    def test_wav_not_found_raises(self):
        episode_id = uuid.uuid4()
        with patch("podcast.services.encoder.os.path.exists", return_value=False):
            with patch("podcast.services.encoder.settings") as mock_settings:
                mock_settings.audio_dir = "/tmp/audio"

                from podcast.services.encoder import _encode

                with pytest.raises(FileNotFoundError, match="WAV file not found"):
                    _encode(episode_id)

    def test_successful_encode(self):
        episode_id = uuid.uuid4()
        mock_audio = MagicMock()
        mock_audio.set_channels.return_value = mock_audio
        mock_audio.set_frame_rate.return_value = mock_audio
        mock_audio.__len__ = MagicMock(return_value=120000)  # 120 seconds in ms

        with patch("podcast.services.encoder.os.path.exists", return_value=True):
            with patch("podcast.services.encoder.os.path.isdir", return_value=True):
                with patch("podcast.services.encoder.os.path.getsize", return_value=1024000):
                    with patch("podcast.services.encoder.os.remove"):
                        with patch("podcast.services.encoder.shutil.rmtree"):
                            with patch("podcast.services.encoder.AudioSegment") as mock_as:
                                mock_as.from_wav.return_value = mock_audio
                                with patch("podcast.services.encoder.settings") as mock_settings:
                                    mock_settings.audio_dir = "/tmp/audio"

                                    from podcast.services.encoder import _encode

                                    filename, duration, size = _encode(episode_id)

        assert filename == f"{episode_id}.mp3"
        assert duration == 120
        assert size == 1024000

    def test_sets_mono_and_sample_rate(self):
        episode_id = uuid.uuid4()
        mock_audio = MagicMock()
        mock_audio.set_channels.return_value = mock_audio
        mock_audio.set_frame_rate.return_value = mock_audio
        mock_audio.__len__ = MagicMock(return_value=1000)

        with patch("podcast.services.encoder.os.path.exists", return_value=True):
            with patch("podcast.services.encoder.os.path.isdir", return_value=False):
                with patch("podcast.services.encoder.os.path.getsize", return_value=100):
                    with patch("podcast.services.encoder.os.remove"):
                        with patch("podcast.services.encoder.AudioSegment") as mock_as:
                            mock_as.from_wav.return_value = mock_audio
                            with patch("podcast.services.encoder.settings") as mock_settings:
                                mock_settings.audio_dir = "/tmp/audio"

                                from podcast.services.encoder import _encode

                                _encode(episode_id)

        mock_audio.set_channels.assert_called_once_with(1)
        mock_audio.set_frame_rate.assert_called_once_with(44100)
        mock_audio.export.assert_called_once()
        export_kwargs = mock_audio.export.call_args
        assert export_kwargs[1]["format"] == "mp3"
        assert export_kwargs[1]["bitrate"] == "128k"

    def test_cleans_up_wav_and_segments(self):
        episode_id = uuid.uuid4()
        mock_audio = MagicMock()
        mock_audio.set_channels.return_value = mock_audio
        mock_audio.set_frame_rate.return_value = mock_audio
        mock_audio.__len__ = MagicMock(return_value=1000)

        with patch("podcast.services.encoder.os.path.exists", return_value=True):
            with patch("podcast.services.encoder.os.path.isdir", return_value=True):
                with patch("podcast.services.encoder.os.path.getsize", return_value=100):
                    with patch("podcast.services.encoder.os.remove") as mock_remove:
                        with patch("podcast.services.encoder.shutil.rmtree") as mock_rmtree:
                            with patch("podcast.services.encoder.AudioSegment") as mock_as:
                                mock_as.from_wav.return_value = mock_audio
                                with patch("podcast.services.encoder.settings") as mock_settings:
                                    mock_settings.audio_dir = "/tmp/audio"

                                    from podcast.services.encoder import _encode

                                    _encode(episode_id)

        mock_remove.assert_called_once()  # WAV removed
        mock_rmtree.assert_called_once()  # Segments dir removed


class TestEncodeMp3:
    async def test_updates_db_with_metadata(self):
        episode_id = uuid.uuid4()
        ep = make_episode(id=episode_id)
        db = AsyncMock()
        db.get = AsyncMock(return_value=ep)
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 3  # current max episode number
        db.execute = AsyncMock(return_value=mock_result)

        with patch("podcast.services.encoder.get_session", make_mock_get_session(db)):
            with patch("podcast.services.encoder.asyncio.to_thread") as mock_thread:
                mock_thread.return_value = ("test.mp3", 120, 1024000)

                from podcast.services.encoder import encode_mp3

                metrics = await encode_mp3(episode_id)

        assert ep.audio_filename == "test.mp3"
        assert ep.audio_duration_seconds == 120
        assert ep.audio_size_bytes == 1024000
        assert ep.episode_number == 4  # max(3) + 1

    async def test_returns_metrics(self):
        episode_id = uuid.uuid4()
        ep = make_episode(id=episode_id)
        db = AsyncMock()
        db.get = AsyncMock(return_value=ep)
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        db.execute = AsyncMock(return_value=mock_result)

        with patch("podcast.services.encoder.get_session", make_mock_get_session(db)):
            with patch("podcast.services.encoder.asyncio.to_thread") as mock_thread:
                mock_thread.return_value = ("test.mp3", 60, 512000)

                from podcast.services.encoder import encode_mp3

                metrics = await encode_mp3(episode_id)

        assert "duration_seconds" in metrics
        assert metrics["audio_duration_seconds"] == 60
        assert metrics["output_size_bytes"] == 512000

    async def test_episode_not_found_raises(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with patch("podcast.services.encoder.get_session", make_mock_get_session(db)):
            with patch("podcast.services.encoder.asyncio.to_thread") as mock_thread:
                mock_thread.return_value = ("test.mp3", 60, 512000)

                from podcast.services.encoder import encode_mp3

                with pytest.raises(ValueError, match="not found"):
                    await encode_mp3(uuid.uuid4())
