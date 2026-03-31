"""Tests for podcast.services.feed."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from podcast.services.feed import _format_duration, generate_feed
from tests.conftest import make_episode, make_settings


class TestFormatDuration:
    def test_zero_seconds(self):
        assert _format_duration(0) == "0:00"

    def test_seconds_only(self):
        assert _format_duration(45) == "0:45"

    def test_minutes_and_seconds(self):
        assert _format_duration(125) == "2:05"

    def test_exact_minutes(self):
        assert _format_duration(300) == "5:00"

    def test_with_hours(self):
        assert _format_duration(3661) == "1:01:01"

    def test_hours_exact(self):
        assert _format_duration(3600) == "1:00:00"

    def test_large_duration(self):
        assert _format_duration(7384) == "2:03:04"

    def test_one_second(self):
        assert _format_duration(1) == "0:01"

    def test_59_seconds(self):
        assert _format_duration(59) == "0:59"

    def test_60_seconds(self):
        assert _format_duration(60) == "1:00"


class TestGenerateFeed:
    async def test_empty_feed_with_default_settings(self):
        """Feed with no episodes and default settings should generate valid XML."""
        settings = make_settings(title="My Private Podcast", description="AI-generated podcast episodes")
        db = AsyncMock()
        db.get = AsyncMock(return_value=settings)
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=mock_result)

        with patch("podcast.services.feed.settings") as mock_settings:
            mock_settings.base_url = "http://localhost:8000"
            xml = await generate_feed(db)

        assert "<?xml" in xml
        assert "<rss" in xml
        assert "My Private Podcast" in xml

    async def test_feed_with_custom_settings(self):
        settings = make_settings(
            title="Custom Podcast",
            description="A custom podcast",
            author="Custom Author",
            language="fi",
            image_url="https://example.com/image.jpg",
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=settings)
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=mock_result)

        with patch("podcast.services.feed.settings") as mock_settings:
            mock_settings.base_url = "https://podcast.example.com"
            xml = await generate_feed(db)

        assert "Custom Podcast" in xml
        assert "Custom Author" in xml
        assert "fi" in xml

    async def test_feed_includes_ready_episodes(self):
        now = datetime.now(timezone.utc)
        ep = make_episode(
            title="Test Episode",
            description="About testing",
            status="ready",
            audio_filename="ep1.mp3",
            audio_size_bytes=1024000,
            audio_duration_seconds=600,
            episode_number=1,
            published_at=now,
        )

        settings = make_settings()
        db = AsyncMock()
        db.get = AsyncMock(return_value=settings)
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [ep]
        mock_result.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=mock_result)

        with patch("podcast.services.feed.settings") as mock_settings:
            mock_settings.base_url = "http://localhost:8000"
            xml = await generate_feed(db)

        assert "Test Episode" in xml
        assert "ep1.mp3" in xml
        assert "audio/mpeg" in xml

    async def test_feed_uses_topic_as_fallback_description(self):
        now = datetime.now(timezone.utc)
        ep = make_episode(
            title="No Desc",
            description=None,
            topic="Fallback topic",
            status="ready",
            audio_filename="ep.mp3",
            audio_size_bytes=100,
            published_at=now,
        )

        db = AsyncMock()
        db.get = AsyncMock(return_value=make_settings())
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [ep]
        mock_result.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=mock_result)

        with patch("podcast.services.feed.settings") as mock_settings:
            mock_settings.base_url = "http://localhost:8000"
            xml = await generate_feed(db)

        assert "Fallback topic" in xml

    async def test_feed_audio_url_format(self):
        now = datetime.now(timezone.utc)
        ep_id = uuid.uuid4()
        ep = make_episode(
            id=ep_id,
            status="ready",
            audio_filename=f"{ep_id}.mp3",
            audio_size_bytes=500,
            published_at=now,
        )

        db = AsyncMock()
        db.get = AsyncMock(return_value=make_settings())
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [ep]
        mock_result.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=mock_result)

        with patch("podcast.services.feed.settings") as mock_settings:
            mock_settings.base_url = "https://my.podcast.com"
            xml = await generate_feed(db)

        assert f"https://my.podcast.com/audio/{ep_id}.mp3" in xml
