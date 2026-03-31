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


def _make_deepseek_response(content, prompt_tokens=200, completion_tokens=400):
    """Create a mock httpx response mimicking the DeepSeek chat completions API."""
    if isinstance(content, list):
        content = json.dumps(content)

    response_data = {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }
    mock_response = MagicMock()
    mock_response.json.return_value = response_data
    mock_response.raise_for_status = MagicMock()
    return mock_response


def _make_httpx_mock(deepseek_response):
    """Create a mock httpx.AsyncClient that supports async context manager."""
    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(return_value=deepseek_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=False)
    return mock_instance


class TestGenerateTranscript:
    async def test_success(self):
        transcript_data = [
            {"speaker": "Alex", "text": "Welcome to our show."},
            {"speaker": "Sam", "text": "Thanks for having me!"},
        ]
        ep = make_episode(topic="AI", research_notes="Some research notes")
        settings = make_settings()
        db = _setup_db(ep, settings)

        deepseek_resp = _make_deepseek_response(transcript_data, 200, 400)
        httpx_mock = _make_httpx_mock(deepseek_resp)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.httpx.AsyncClient", return_value=httpx_mock):
                with patch("podcast.services.transcript.settings") as mock_settings:
                    mock_settings.deepseek_api_key = "test-key"
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

        deepseek_resp = _make_deepseek_response(transcript_data)
        httpx_mock = _make_httpx_mock(deepseek_resp)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.httpx.AsyncClient", return_value=httpx_mock):
                with patch("podcast.services.transcript.settings") as mock_settings:
                    mock_settings.deepseek_api_key = "test-key"
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

        deepseek_resp = _make_deepseek_response("not valid json at all")
        httpx_mock = _make_httpx_mock(deepseek_resp)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.httpx.AsyncClient", return_value=httpx_mock):
                with patch("podcast.services.transcript.settings") as mock_settings:
                    mock_settings.deepseek_api_key = "test-key"
                    from podcast.services.transcript import generate_transcript

                    with pytest.raises(json.JSONDecodeError):
                        await generate_transcript(ep.id)

    async def test_empty_array_raises(self):
        ep = make_episode(topic="Test", research_notes="notes")
        db = _setup_db(ep, make_settings())

        deepseek_resp = _make_deepseek_response("[]")
        httpx_mock = _make_httpx_mock(deepseek_resp)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.httpx.AsyncClient", return_value=httpx_mock):
                with patch("podcast.services.transcript.settings") as mock_settings:
                    mock_settings.deepseek_api_key = "test-key"
                    from podcast.services.transcript import generate_transcript

                    with pytest.raises(RuntimeError, match="non-empty JSON array"):
                        await generate_transcript(ep.id)

    async def test_missing_speaker_key_raises(self):
        ep = make_episode(topic="Test", research_notes="notes")
        db = _setup_db(ep, make_settings())

        deepseek_resp = _make_deepseek_response([{"text": "no speaker"}])
        httpx_mock = _make_httpx_mock(deepseek_resp)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.httpx.AsyncClient", return_value=httpx_mock):
                with patch("podcast.services.transcript.settings") as mock_settings:
                    mock_settings.deepseek_api_key = "test-key"
                    from podcast.services.transcript import generate_transcript

                    with pytest.raises(RuntimeError, match="Invalid segment"):
                        await generate_transcript(ep.id)

    async def test_missing_text_key_raises(self):
        ep = make_episode(topic="Test", research_notes="notes")
        db = _setup_db(ep, make_settings())

        deepseek_resp = _make_deepseek_response([{"speaker": "Alex"}])
        httpx_mock = _make_httpx_mock(deepseek_resp)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.httpx.AsyncClient", return_value=httpx_mock):
                with patch("podcast.services.transcript.settings") as mock_settings:
                    mock_settings.deepseek_api_key = "test-key"
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

        deepseek_resp = _make_deepseek_response(wrapped)
        httpx_mock = _make_httpx_mock(deepseek_resp)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.httpx.AsyncClient", return_value=httpx_mock):
                with patch("podcast.services.transcript.settings") as mock_settings:
                    mock_settings.deepseek_api_key = "test-key"
                    from podcast.services.transcript import generate_transcript

                    metrics = await generate_transcript(ep.id)

        assert metrics["segment_count"] == 1

    async def test_truncates_long_research_notes(self):
        long_notes = "x" * 20000
        ep = make_episode(topic="Test", research_notes=long_notes)
        db = _setup_db(ep, make_settings())

        transcript_data = [{"speaker": "Alex", "text": "Hello."}]
        deepseek_resp = _make_deepseek_response(transcript_data)
        httpx_mock = _make_httpx_mock(deepseek_resp)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.httpx.AsyncClient", return_value=httpx_mock):
                with patch("podcast.services.transcript.settings") as mock_settings:
                    mock_settings.deepseek_api_key = "test-key"
                    from podcast.services.transcript import generate_transcript

                    await generate_transcript(ep.id)

        # Verify the user message was truncated
        call_kwargs = httpx_mock.post.call_args
        payload = call_kwargs[1]["json"]
        user_content = payload["messages"][1]["content"]
        assert "[...truncated]" in user_content

    async def test_uses_host_names_from_settings(self):
        ep = make_episode(topic="Test", research_notes="notes")
        settings = make_settings(host_a_name="Alice", host_b_name="Bob")
        db = _setup_db(ep, settings)

        transcript_data = [{"speaker": "Alice", "text": "Hi."}]
        deepseek_resp = _make_deepseek_response(transcript_data)
        httpx_mock = _make_httpx_mock(deepseek_resp)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.httpx.AsyncClient", return_value=httpx_mock):
                with patch("podcast.services.transcript.settings") as mock_settings:
                    mock_settings.deepseek_api_key = "test-key"
                    from podcast.services.transcript import generate_transcript

                    await generate_transcript(ep.id)

        call_kwargs = httpx_mock.post.call_args
        payload = call_kwargs[1]["json"]
        system_prompt = payload["messages"][0]["content"]
        assert "Alice" in system_prompt
        assert "Bob" in system_prompt

    async def test_no_settings_uses_defaults(self):
        ep = make_episode(topic="Test", research_notes="notes")
        db = _setup_db(ep, None)  # No settings

        transcript_data = [{"speaker": "Alex", "text": "Default hosts."}]
        deepseek_resp = _make_deepseek_response(transcript_data)
        httpx_mock = _make_httpx_mock(deepseek_resp)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.httpx.AsyncClient", return_value=httpx_mock):
                with patch("podcast.services.transcript.settings") as mock_settings:
                    mock_settings.deepseek_api_key = "test-key"
                    from podcast.services.transcript import generate_transcript

                    await generate_transcript(ep.id)

        call_kwargs = httpx_mock.post.call_args
        payload = call_kwargs[1]["json"]
        user_content = payload["messages"][1]["content"]
        assert "Alex" in user_content
        assert "Sam" in user_content

    async def test_word_count_calculation(self):
        transcript_data = [
            {"speaker": "Alex", "text": "Hello world foo bar baz."},
            {"speaker": "Sam", "text": "One two three."},
        ]
        ep = make_episode(topic="Test", research_notes="notes")
        db = _setup_db(ep, make_settings())

        deepseek_resp = _make_deepseek_response(transcript_data)
        httpx_mock = _make_httpx_mock(deepseek_resp)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.httpx.AsyncClient", return_value=httpx_mock):
                with patch("podcast.services.transcript.settings") as mock_settings:
                    mock_settings.deepseek_api_key = "test-key"
                    from podcast.services.transcript import generate_transcript

                    metrics = await generate_transcript(ep.id)

        # "Hello world foo bar baz." = 5 words, "One two three." = 3 words
        assert metrics["word_count"] == 8
