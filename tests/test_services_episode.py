"""Tests for podcast.services.episode."""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from podcast.models import Episode, Job
from podcast.services.episode import (
    create_episode,
    delete_episode,
    get_episode,
    get_next_episode_number,
    list_episodes,
    retry_episode,
)
from tests.conftest import make_episode, make_job

_TEST_USER_ID = uuid.uuid4()


def _mock_openai_title(title_text="Generated Title"):
    """Return a patch context for generate_title_from_topic's OpenAI call."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": title_text}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    return patch("podcast.services.episode.httpx.AsyncClient", return_value=mock_client)


class TestCreateEpisode:
    async def test_creates_episode_with_all_fields(self):
        db = AsyncMock()
        added = []
        db.add = lambda obj: added.append(obj)

        episode = await create_episode(db, "Test topic", "My Title", "My desc", user_id=_TEST_USER_ID)

        assert isinstance(episode, Episode)
        assert episode.title == "My Title"
        assert episode.topic == "Test topic"
        assert episode.description == "My desc"
        assert episode.status == "pending"
        assert episode.user_id == _TEST_USER_ID
        db.flush.assert_awaited_once()

    async def test_creates_initial_research_job(self):
        db = AsyncMock()
        added = []
        db.add = lambda obj: added.append(obj)

        with _mock_openai_title():
            await create_episode(db, "Topic", user_id=_TEST_USER_ID)

        jobs = [o for o in added if isinstance(o, Job)]
        assert len(jobs) == 1
        assert jobs[0].step == "research"
        assert jobs[0].status == "pending"

    async def test_auto_title_from_topic(self):
        db = AsyncMock()
        db.add = MagicMock()

        with _mock_openai_title("Short topic"):
            episode = await create_episode(db, "Short topic", user_id=_TEST_USER_ID)
        assert episode.title == "Short topic"

    async def test_auto_title_truncation(self):
        db = AsyncMock()
        db.add = MagicMock()

        long_topic = "x" * 200
        with _mock_openai_title(long_topic[:200]):
            episode = await create_episode(db, long_topic, user_id=_TEST_USER_ID)
        assert len(episode.title) <= 200

    async def test_none_title_uses_topic(self):
        db = AsyncMock()
        db.add = MagicMock()

        with _mock_openai_title("My topic"):
            episode = await create_episode(db, "My topic", title=None, user_id=_TEST_USER_ID)
        assert episode.title == "My topic"

    async def test_empty_string_title_uses_topic(self):
        db = AsyncMock()
        db.add = MagicMock()

        with _mock_openai_title("My topic"):
            episode = await create_episode(db, "My topic", title="", user_id=_TEST_USER_ID)
        assert episode.title == "My topic"


class TestListEpisodes:
    async def test_returns_list(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        ep1 = make_episode(title="Ep 1", user_id=_TEST_USER_ID)
        ep2 = make_episode(title="Ep 2", user_id=_TEST_USER_ID)
        mock_scalars.all.return_value = [ep1, ep2]
        mock_result.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=mock_result)

        result = await list_episodes(db, _TEST_USER_ID)

        assert len(result) == 2
        assert result[0].title == "Ep 1"
        assert result[1].title == "Ep 2"

    async def test_returns_empty_list(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=mock_result)

        result = await list_episodes(db, _TEST_USER_ID)
        assert result == []


class TestGetEpisode:
    async def test_found(self):
        ep = make_episode(title="Found Episode", user_id=_TEST_USER_ID)
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ep
        db.execute = AsyncMock(return_value=mock_result)

        result = await get_episode(db, ep.id, _TEST_USER_ID)
        assert result is ep

    async def test_not_found(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        result = await get_episode(db, uuid.uuid4(), _TEST_USER_ID)
        assert result is None


class TestDeleteEpisode:
    async def test_deletes_existing_episode(self):
        ep = make_episode(audio_filename=None, user_id=_TEST_USER_ID)
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ep
        db.execute = AsyncMock(return_value=mock_result)

        with patch("podcast.services.episode.os.path.exists", return_value=False):
            with patch("podcast.services.episode.os.path.isdir", return_value=False):
                result = await delete_episode(db, ep.id, _TEST_USER_ID)

        assert result is True
        db.delete.assert_awaited_once_with(ep)

    async def test_returns_false_when_not_found(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        result = await delete_episode(db, uuid.uuid4(), _TEST_USER_ID)
        assert result is False

    async def test_cleans_up_audio_file(self):
        ep = make_episode(audio_filename="test.mp3", user_id=_TEST_USER_ID)
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ep
        db.execute = AsyncMock(return_value=mock_result)

        with patch("podcast.services.episode.os.path.exists", return_value=True) as mock_exists:
            with patch("podcast.services.episode.os.remove") as mock_remove:
                with patch("podcast.services.episode.os.path.isdir", return_value=False):
                    await delete_episode(db, ep.id, _TEST_USER_ID)

        mock_remove.assert_called_once()

    async def test_cleans_up_segments_directory(self):
        ep = make_episode(audio_filename=None, user_id=_TEST_USER_ID)
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ep
        db.execute = AsyncMock(return_value=mock_result)

        with patch("podcast.services.episode.os.path.exists", return_value=False):
            with patch("podcast.services.episode.os.path.isdir", return_value=True):
                with patch("shutil.rmtree") as mock_rmtree:
                    await delete_episode(db, ep.id, _TEST_USER_ID)

        mock_rmtree.assert_called_once()


class TestRetryEpisode:
    async def test_retries_failed_episode(self):
        ep = make_episode(status="failed", failed_step="tts", user_id=_TEST_USER_ID)
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ep
        db.execute = AsyncMock(return_value=mock_result)
        added = []
        db.add = lambda obj: added.append(obj)

        result = await retry_episode(db, ep.id, _TEST_USER_ID)

        assert result is ep
        assert ep.status == "pending"
        assert ep.error_message is None
        assert ep.failed_step is None

        jobs = [o for o in added if isinstance(o, Job)]
        assert len(jobs) == 1
        assert jobs[0].step == "tts"

    async def test_defaults_to_research_step(self):
        ep = make_episode(status="failed", failed_step=None, user_id=_TEST_USER_ID)
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ep
        db.execute = AsyncMock(return_value=mock_result)
        added = []
        db.add = lambda obj: added.append(obj)

        await retry_episode(db, ep.id, _TEST_USER_ID)

        jobs = [o for o in added if isinstance(o, Job)]
        assert jobs[0].step == "research"

    async def test_returns_none_for_non_failed(self):
        ep = make_episode(status="ready", user_id=_TEST_USER_ID)
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ep
        db.execute = AsyncMock(return_value=mock_result)

        result = await retry_episode(db, ep.id, _TEST_USER_ID)
        assert result is None

    async def test_returns_none_when_not_found(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        result = await retry_episode(db, uuid.uuid4(), _TEST_USER_ID)
        assert result is None


class TestGetNextEpisodeNumber:
    async def test_returns_next_number(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 5
        db.execute = AsyncMock(return_value=mock_result)

        result = await get_next_episode_number(db, _TEST_USER_ID)
        assert result == 6

    async def test_returns_1_when_no_episodes(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0  # coalesce returns 0
        db.execute = AsyncMock(return_value=mock_result)

        result = await get_next_episode_number(db, _TEST_USER_ID)
        assert result == 1
