"""Tests for podcast.services.transcript."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_episode, make_mock_get_session, make_settings
from podcast.services.llm_providers import LLMResponse


def _setup_db(episode, settings=None):
    """Build a mock session for transcript tests."""
    db = AsyncMock()

    # db.get() is used to load the episode by ID
    db.get = AsyncMock(return_value=episode)

    # db.execute() is used for the settings query (select where user_id=...)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = settings
    db.execute = AsyncMock(return_value=mock_result)

    return db


def _make_llm_response(text: str, input_tokens: int = 200, output_tokens: int = 400) -> LLMResponse:
    """Create a mock LLMResponse."""
    if isinstance(text, list):
        text = json.dumps(text)
    return LLMResponse(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model="gpt-5.4-mini-2026-03-17",
    )


class TestGenerateTranscript:
    async def test_success(self):
        transcript_data = [
            {"speaker": "Alex", "text": "Welcome to our show."},
            {"speaker": "Sam", "text": "Thanks for having me!"},
        ]
        ep = make_episode(
            topic="AI",
            research_notes="Some research notes",
            transcript_model="gpt-mini"
        )
        settings = make_settings()
        db = _setup_db(ep, settings)

        response = _make_llm_response(transcript_data, 200, 400)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.complete", new_callable=AsyncMock) as mock_complete:
                with patch("podcast.services.transcript.get_client", new_callable=AsyncMock):
                    mock_complete.return_value = response
                    from podcast.services.transcript import generate_transcript

                    metrics = await generate_transcript(ep.id)

        assert metrics["segment_count"] == 2
        assert metrics["input_tokens"] == 200
        assert metrics["output_tokens"] == 400
        assert metrics["word_count"] > 0
        assert "duration_seconds" in metrics
        assert metrics["model"] == "gpt-5.4-mini-2026-03-17"

    async def test_saves_transcript_as_json(self):
        transcript_data = [
            {"speaker": "Alex", "text": "Hello world."},
        ]
        ep = make_episode(
            topic="Test",
            research_notes="notes",
            transcript_model="gpt-mini"
        )
        db = _setup_db(ep, make_settings())

        response = _make_llm_response(transcript_data)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.complete", new_callable=AsyncMock) as mock_complete:
                with patch("podcast.services.transcript.get_client", new_callable=AsyncMock):
                    mock_complete.return_value = response
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
        ep = make_episode(
            topic="Test",
            research_notes="notes",
            transcript_model="gpt-mini"
        )
        db = _setup_db(ep, make_settings())

        response = _make_llm_response("not valid json at all")

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.complete", new_callable=AsyncMock) as mock_complete:
                with patch("podcast.services.transcript.get_client", new_callable=AsyncMock):
                    mock_complete.return_value = response
                    from podcast.services.transcript import generate_transcript

                    with pytest.raises(json.JSONDecodeError):
                        await generate_transcript(ep.id)

    async def test_empty_array_raises(self):
        ep = make_episode(
            topic="Test",
            research_notes="notes",
            transcript_model="gpt-mini"
        )
        db = _setup_db(ep, make_settings())

        response = _make_llm_response("[]")

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.complete", new_callable=AsyncMock) as mock_complete:
                with patch("podcast.services.transcript.get_client", new_callable=AsyncMock):
                    mock_complete.return_value = response
                    from podcast.services.transcript import generate_transcript

                    with pytest.raises(RuntimeError, match="non-empty JSON array"):
                        await generate_transcript(ep.id)

    async def test_missing_speaker_key_raises(self):
        ep = make_episode(
            topic="Test",
            research_notes="notes",
            transcript_model="gpt-mini"
        )
        db = _setup_db(ep, make_settings())

        response = _make_llm_response([{"text": "no speaker"}])

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.complete", new_callable=AsyncMock) as mock_complete:
                with patch("podcast.services.transcript.get_client", new_callable=AsyncMock):
                    mock_complete.return_value = response
                    from podcast.services.transcript import generate_transcript

                    with pytest.raises(RuntimeError, match="Invalid segment"):
                        await generate_transcript(ep.id)

    async def test_missing_text_key_raises(self):
        ep = make_episode(
            topic="Test",
            research_notes="notes",
            transcript_model="gpt-mini"
        )
        db = _setup_db(ep, make_settings())

        response = _make_llm_response([{"speaker": "Alex"}])

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.complete", new_callable=AsyncMock) as mock_complete:
                with patch("podcast.services.transcript.get_client", new_callable=AsyncMock):
                    mock_complete.return_value = response
                    from podcast.services.transcript import generate_transcript

                    with pytest.raises(RuntimeError, match="Invalid segment"):
                        await generate_transcript(ep.id)

    async def test_strips_markdown_code_blocks(self):
        """LLM sometimes wraps JSON in ```json ... ``` blocks."""
        transcript_data = [{"speaker": "Alex", "text": "Hello."}]
        json_text = json.dumps(transcript_data)
        wrapped = f"```json\n{json_text}\n```"

        ep = make_episode(
            topic="Test",
            research_notes="notes",
            transcript_model="gpt-mini"
        )
        db = _setup_db(ep, make_settings())

        response = _make_llm_response(wrapped)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.complete", new_callable=AsyncMock) as mock_complete:
                with patch("podcast.services.transcript.get_client", new_callable=AsyncMock):
                    mock_complete.return_value = response
                    from podcast.services.transcript import generate_transcript

                    metrics = await generate_transcript(ep.id)

        assert metrics["segment_count"] == 1

    async def test_truncates_long_research_notes(self):
        long_notes = "x" * 20000
        ep = make_episode(
            topic="Test",
            research_notes=long_notes,
            transcript_model="gpt-mini"
        )
        db = _setup_db(ep, make_settings())

        transcript_data = [{"speaker": "Alex", "text": "Hello."}]
        response = _make_llm_response(transcript_data)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.complete", new_callable=AsyncMock) as mock_complete:
                with patch("podcast.services.transcript.get_client", new_callable=AsyncMock):
                    mock_complete.return_value = response
                    from podcast.services.transcript import generate_transcript

                    await generate_transcript(ep.id)

        # Verify the user message was truncated
        call_kwargs = mock_complete.call_args[1]
        user_message = call_kwargs["user_message"]
        assert "[...truncated]" in user_message

    async def test_uses_host_names_from_settings(self):
        ep = make_episode(
            topic="Test",
            research_notes="notes",
            transcript_model="gpt-mini"
        )
        settings = make_settings(host_a_name="Alice", host_b_name="Bob")
        db = _setup_db(ep, settings)

        transcript_data = [{"speaker": "Alice", "text": "Hi."}]
        response = _make_llm_response(transcript_data)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.complete", new_callable=AsyncMock) as mock_complete:
                with patch("podcast.services.transcript.get_client", new_callable=AsyncMock):
                    mock_complete.return_value = response
                    from podcast.services.transcript import generate_transcript

                    await generate_transcript(ep.id)

        call_kwargs = mock_complete.call_args[1]
        system_prompt = call_kwargs["system"]
        assert "Alice" in system_prompt
        assert "Bob" in system_prompt

    async def test_no_settings_uses_defaults(self):
        ep = make_episode(
            topic="Test",
            research_notes="notes",
            transcript_model="gpt-mini"
        )
        db = _setup_db(ep, None)

        transcript_data = [{"speaker": "Alex", "text": "Default hosts."}]
        response = _make_llm_response(transcript_data)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.complete", new_callable=AsyncMock) as mock_complete:
                with patch("podcast.services.transcript.get_client", new_callable=AsyncMock):
                    mock_complete.return_value = response
                    from podcast.services.transcript import generate_transcript

                    await generate_transcript(ep.id)

        call_kwargs = mock_complete.call_args[1]
        user_message = call_kwargs["user_message"]
        assert "Alex" in user_message
        assert "Sam" in user_message

    async def test_word_count_calculation(self):
        transcript_data = [
            {"speaker": "Alex", "text": "Hello world foo bar baz."},
            {"speaker": "Sam", "text": "One two three."},
        ]
        ep = make_episode(
            topic="Test",
            research_notes="notes",
            transcript_model="gpt-mini"
        )
        db = _setup_db(ep, make_settings())

        response = _make_llm_response(transcript_data)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.complete", new_callable=AsyncMock) as mock_complete:
                with patch("podcast.services.transcript.get_client", new_callable=AsyncMock):
                    mock_complete.return_value = response
                    from podcast.services.transcript import generate_transcript

                    metrics = await generate_transcript(ep.id)

        # "Hello world foo bar baz." = 5 words, "One two three." = 3 words
        assert metrics["word_count"] == 8

    async def test_uses_default_transcript_model(self):
        """When episode has no transcript_model, default should be used."""
        ep = make_episode(
            topic="Test",
            research_notes="notes",
            transcript_model=None
        )
        db = _setup_db(ep, make_settings())

        transcript_data = [{"speaker": "Alex", "text": "Default model test."}]
        response = _make_llm_response(transcript_data)

        with patch("podcast.services.transcript.get_session", make_mock_get_session(db)):
            with patch("podcast.services.transcript.get_transcript_model") as mock_get_model:
                with patch("podcast.services.transcript.complete", new_callable=AsyncMock) as mock_complete:
                    with patch("podcast.services.transcript.get_client", new_callable=AsyncMock):
                        mock_complete.return_value = response
                        from podcast.services.llm_providers import get_transcript_model
                        mock_get_model.side_effect = get_transcript_model
                        from podcast.services.transcript import generate_transcript

                        await generate_transcript(ep.id)

        # Verify get_transcript_model was called with None (falls back to default)
        mock_get_model.assert_called_once_with(None)
