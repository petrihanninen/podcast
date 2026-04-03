"""Tests for podcast.services.research."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_episode, make_mock_get_session
from podcast.services.llm_providers import LLMResponse


def _make_session_with_episode(episode):
    """Build a mock session where db.get(Episode, id) returns episode."""
    db = AsyncMock()
    db.get = AsyncMock(return_value=episode)
    return db


def _make_llm_response(text: str, input_tokens: int = 100, output_tokens: int = 200) -> LLMResponse:
    """Create a mock LLMResponse."""
    return LLMResponse(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model="claude-sonnet-4-6-20250514",
    )


class TestRunResearch:
    async def test_success(self):
        ep = make_episode(topic="Quantum computing", research_model="claude-sonnet")
        db = _make_session_with_episode(ep)
        response = _make_llm_response("Research notes about quantum computing", 150, 300)

        with patch("podcast.services.research.get_session", make_mock_get_session(db)):
            with patch("podcast.services.research.complete", new_callable=AsyncMock) as mock_complete:
                mock_complete.return_value = response
                from podcast.services.research import run_research

                metrics = await run_research(ep.id)

        assert metrics["model"] == "claude-sonnet-4-6-20250514"
        assert metrics["input_tokens"] == 150
        assert metrics["output_tokens"] == 300
        assert "duration_seconds" in metrics
        assert metrics["output_chars"] == len("Research notes about quantum computing")

    async def test_saves_research_notes(self):
        ep = make_episode(topic="AI safety", research_model="claude-sonnet")
        db = _make_session_with_episode(ep)
        response = _make_llm_response("Research about AI safety")

        with patch("podcast.services.research.get_session", make_mock_get_session(db)):
            with patch("podcast.services.research.complete", new_callable=AsyncMock) as mock_complete:
                mock_complete.return_value = response
                from podcast.services.research import run_research

                await run_research(ep.id)

        # Verify research_notes was set on the episode
        assert ep.research_notes == "Research about AI safety"

    async def test_episode_not_found_raises(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with patch("podcast.services.research.get_session", make_mock_get_session(db)):
            from podcast.services.research import run_research

            with pytest.raises(ValueError, match="not found"):
                await run_research(uuid.uuid4())

    async def test_empty_response_raises(self):
        ep = make_episode(topic="Empty topic", research_model="claude-sonnet")
        db = _make_session_with_episode(ep)
        response = _make_llm_response("", 10, 0)

        with patch("podcast.services.research.get_session", make_mock_get_session(db)):
            with patch("podcast.services.research.complete", new_callable=AsyncMock) as mock_complete:
                mock_complete.return_value = response
                from podcast.services.research import run_research

                with pytest.raises(RuntimeError, match="No research content"):
                    await run_research(ep.id)

    async def test_uses_web_search_flag(self):
        """Verify the complete() call includes use_web_search=True."""
        ep = make_episode(topic="Test", research_model="claude-sonnet")
        db = _make_session_with_episode(ep)
        response = _make_llm_response("research")

        with patch("podcast.services.research.get_session", make_mock_get_session(db)):
            with patch("podcast.services.research.complete", new_callable=AsyncMock) as mock_complete:
                mock_complete.return_value = response
                from podcast.services.research import run_research

                await run_research(ep.id)

        # Verify use_web_search was passed
        call_kwargs = mock_complete.call_args[1]
        assert call_kwargs.get("use_web_search") is True

    async def test_uses_default_research_model(self):
        """When episode has no research_model, default should be used."""
        ep = make_episode(topic="Test", research_model=None)
        db = _make_session_with_episode(ep)
        response = _make_llm_response("research")

        with patch("podcast.services.research.get_session", make_mock_get_session(db)):
            with patch("podcast.services.research.get_research_model") as mock_get_model:
                with patch("podcast.services.research.complete", new_callable=AsyncMock) as mock_complete:
                    mock_complete.return_value = response
                    # Set up the mock to return a ModelInfo
                    from podcast.services.llm_providers import get_research_model
                    mock_get_model.side_effect = get_research_model

                    from podcast.services.research import run_research

                    await run_research(ep.id)

        # Verify get_research_model was called with None (falls back to default)
        mock_get_model.assert_called_once_with(None)

    async def test_metric_calculation(self):
        """Verify metrics are calculated correctly."""
        ep = make_episode(topic="Test", research_model="gemini-flash")
        db = _make_session_with_episode(ep)
        response = _make_llm_response("Test research content", 500, 1000)

        with patch("podcast.services.research.get_session", make_mock_get_session(db)):
            with patch("podcast.services.research.complete", new_callable=AsyncMock) as mock_complete:
                mock_complete.return_value = response
                from podcast.services.research import run_research

                metrics = await run_research(ep.id)

        assert metrics["provider"] == "google"
        assert metrics["input_tokens"] == 500
        assert metrics["output_tokens"] == 1000
        assert metrics["output_chars"] == len("Test research content")
