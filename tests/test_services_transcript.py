"""Tests for podcast.services.transcript."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_episode, make_mock_get_session, make_settings


def _setup_db(episode, settings=None):
    """Build a mock session for transcript tests."""
    db = AsyncMock()

    async def mock_get(model, id_val):
        from podcast.models import Episode, PodcastSettings
        if model is Episode or (hasattr(model, '__tablename__') and model.__tablename__ == 'episodes'):
            return episode
        if model is PodcastSettings or id_val == 1:
            return settings
        return None

    db.get = AsyncMock(side_effect=mock_get)
    return db


class TestGenerateTranscript:
    async def test_success(self):
        transcript_data = [
            {"speaker": "Alex", "text": "Welcome to our show."},
            {"speaker": "Sam", "text": "Thanks for having me!"},
        ]
        ep = make_episode(topic="AI", research_notes="Some research notes")
        settings = make_settings()
        db = _setup_db(ep, settings)
        response = MagicMock()
        block = MagicMock(type="text", text=json.dumps(transcript_data))
        response.content = [block]
        response.usage.input_tokens = 200
        response.usage.output_tokens = 400

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.get_client", return_value=mock_client):
                from podcast.services.transcript import generate_transcript

                metrics = await generate_transcript(ep.id)

        assert metrics["segment_count"] == 2
        assert metrics["input_tokens"] == 200
        assert metrics["output_tokens"] == 400
        assert metrics["word_count"] > 0
        assert "duration_seconds" in metrics

    async def test_saves_transcript_as_json(self):
        transcript_data = [
            {"speaker": "Alex", "text": "Hello world."},
        ]
        ep = make_episode(topic="Test", research_notes="notes")
        db = _setup_db(ep, make_settings())
        response = MagicMock()
        block = MagicMock(type="text", text=json.dumps(transcript_data))
        response.content = [block]
        response.usage.input_tokens = 50
        response.usage.output_tokens = 100

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.get_client", return_value=mock_client):
                from podcast.services.transcript import generate_transcript

                await generate_transcript(ep.id)

        saved = json.loads(ep.transcript)
        assert len(saved) == 1
        assert saved[0]["speaker"] == "Alex"

    async def test_episode_not_found_raises(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            from podcast.services.transcript import generate_transcript

            with pytest.raises(ValueError, match="not found"):
                await generate_transcript(uuid.uuid4())

    async def test_invalid_json_raises(self):
        ep = make_episode(topic="Test", research_notes="notes")
        db = _setup_db(ep, make_settings())
        response = MagicMock()
        block = MagicMock(type="text", text="not valid json at all")
        response.content = [block]
        response.usage.input_tokens = 50
        response.usage.output_tokens = 100

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.get_client", return_value=mock_client):
                from podcast.services.transcript import generate_transcript

                with pytest.raises(json.JSONDecodeError):
                    await generate_transcript(ep.id)

    async def test_empty_array_raises(self):
        ep = make_episode(topic="Test", research_notes="notes")
        db = _setup_db(ep, make_settings())
        response = MagicMock()
        block = MagicMock(type="text", text="[]")
        response.content = [block]
        response.usage.input_tokens = 50
        response.usage.output_tokens = 100

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.get_client", return_value=mock_client):
                from podcast.services.transcript import generate_transcript

                with pytest.raises(RuntimeError, match="non-empty JSON array"):
                    await generate_transcript(ep.id)

    async def test_missing_speaker_key_raises(self):
        ep = make_episode(topic="Test", research_notes="notes")
        db = _setup_db(ep, make_settings())
        response = MagicMock()
        block = MagicMock(type="text", text=json.dumps([{"text": "no speaker"}]))
        response.content = [block]
        response.usage.input_tokens = 50
        response.usage.output_tokens = 100

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.get_client", return_value=mock_client):
                from podcast.services.transcript import generate_transcript

                with pytest.raises(RuntimeError, match="Invalid segment"):
                    await generate_transcript(ep.id)

    async def test_missing_text_key_raises(self):
        ep = make_episode(topic="Test", research_notes="notes")
        db = _setup_db(ep, make_settings())
        response = MagicMock()
        block = MagicMock(type="text", text=json.dumps([{"speaker": "Alex"}]))
        response.content = [block]
        response.usage.input_tokens = 50
        response.usage.output_tokens = 100

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.get_client", return_value=mock_client):
                from podcast.services.transcript import generate_transcript

                with pytest.raises(RuntimeError, match="Invalid segment"):
                    await generate_transcript(ep.id)

    async def test_strips_markdown_code_blocks(self):
        """Claude sometimes wraps JSON in ```json ... ``` blocks."""
        transcript_data = [{"speaker": "Alex", "text": "Hello."}]
        json_text = json.dumps(transcript_data)
        wrapped = f"```json\n{json_text}\n```"

        ep = make_episode(topic="Test", research_notes="notes")
        db = _setup_db(ep, make_settings())
        response = MagicMock()
        block = MagicMock(type="text", text=wrapped)
        response.content = [block]
        response.usage.input_tokens = 50
        response.usage.output_tokens = 100

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.get_client", return_value=mock_client):
                from podcast.services.transcript import generate_transcript

                metrics = await generate_transcript(ep.id)

        assert metrics["segment_count"] == 1

    async def test_truncates_long_research_notes(self):
        long_notes = "x" * 20000
        ep = make_episode(topic="Test", research_notes=long_notes)
        db = _setup_db(ep, make_settings())

        transcript_data = [{"speaker": "Alex", "text": "Hello."}]
        response = MagicMock()
        block = MagicMock(type="text", text=json.dumps(transcript_data))
        response.content = [block]
        response.usage.input_tokens = 50
        response.usage.output_tokens = 100

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.get_client", return_value=mock_client):
                from podcast.services.transcript import generate_transcript

                await generate_transcript(ep.id)

        # Verify the user message was truncated
        call_kwargs = mock_client.messages.create.call_args[1]
        user_content = call_kwargs["messages"][0]["content"]
        assert "[...truncated]" in user_content

    async def test_uses_host_names_from_settings(self):
        ep = make_episode(topic="Test", research_notes="notes")
        settings = make_settings(host_a_name="Alice", host_b_name="Bob")
        db = _setup_db(ep, settings)

        transcript_data = [{"speaker": "Alice", "text": "Hi."}]
        response = MagicMock()
        block = MagicMock(type="text", text=json.dumps(transcript_data))
        response.content = [block]
        response.usage.input_tokens = 50
        response.usage.output_tokens = 100

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.get_client", return_value=mock_client):
                from podcast.services.transcript import generate_transcript

                await generate_transcript(ep.id)

        call_kwargs = mock_client.messages.create.call_args[1]
        system_prompt = call_kwargs["system"]
        assert "Alice" in system_prompt
        assert "Bob" in system_prompt

    async def test_no_settings_uses_defaults(self):
        ep = make_episode(topic="Test", research_notes="notes")
        db = _setup_db(ep, None)  # No settings

        transcript_data = [{"speaker": "Alex", "text": "Default hosts."}]
        response = MagicMock()
        block = MagicMock(type="text", text=json.dumps(transcript_data))
        response.content = [block]
        response.usage.input_tokens = 50
        response.usage.output_tokens = 100

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.get_client", return_value=mock_client):
                from podcast.services.transcript import generate_transcript

                await generate_transcript(ep.id)

        call_kwargs = mock_client.messages.create.call_args[1]
        user_content = call_kwargs["messages"][0]["content"]
        assert "Alex" in user_content
        assert "Sam" in user_content

    async def test_word_count_calculation(self):
        transcript_data = [
            {"speaker": "Alex", "text": "Hello world foo bar baz."},
            {"speaker": "Sam", "text": "One two three."},
        ]
        ep = make_episode(topic="Test", research_notes="notes")
        db = _setup_db(ep, make_settings())
        response = MagicMock()
        block = MagicMock(type="text", text=json.dumps(transcript_data))
        response.content = [block]
        response.usage.input_tokens = 50
        response.usage.output_tokens = 100

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.get_client", return_value=mock_client):
                from podcast.services.transcript import generate_transcript

                metrics = await generate_transcript(ep.id)

        # "Hello world foo bar baz." = 5 words, "One two three." = 3 words
        assert metrics["word_count"] == 8
