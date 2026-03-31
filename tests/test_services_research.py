"""Tests for podcast.services.research."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_claude_response, make_episode, make_mock_get_session


def _make_session_with_episode(episode):
    """Build a mock session where db.get(Episode, id) returns episode."""
    db = AsyncMock()
    db.get = AsyncMock(return_value=episode)
    return db


class TestRunResearch:
    async def test_success(self):
        ep = make_episode(topic="Quantum computing")
        db = _make_session_with_episode(ep)
        response = make_claude_response("Research notes about quantum computing", 150, 300)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.research.get_session", make_mock_get_session(db)):
            with patch("podcast.services.research.get_client", return_value=mock_client):
                from podcast.services.research import run_research

                metrics = await run_research(ep.id)

        assert metrics["model"] == "claude-sonnet-4-20250514"
        assert metrics["input_tokens"] == 150
        assert metrics["output_tokens"] == 300
        assert "duration_seconds" in metrics
        assert metrics["output_chars"] == len("Research notes about quantum computing")

    async def test_saves_research_notes(self):
        ep = make_episode(topic="AI safety")
        db = _make_session_with_episode(ep)
        response = make_claude_response("Research about AI safety")
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.research.get_session", make_mock_get_session(db)):
            with patch("podcast.services.research.get_client", return_value=mock_client):
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
        ep = make_episode(topic="Empty topic")
        db = _make_session_with_episode(ep)

        # Response with no text blocks
        empty_response = MagicMock()
        empty_response.content = []
        empty_response.usage.input_tokens = 10
        empty_response.usage.output_tokens = 0

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=empty_response)

        with patch("podcast.services.research.get_session", make_mock_get_session(db)):
            with patch("podcast.services.research.get_client", return_value=mock_client):
                from podcast.services.research import run_research

                with pytest.raises(RuntimeError, match="No research content"):
                    await run_research(ep.id)

    async def test_multi_block_response(self):
        """When response has multiple text blocks, they should be concatenated."""
        ep = make_episode(topic="Multi-block")
        db = _make_session_with_episode(ep)

        block1 = MagicMock(type="text", text="Part one. ")
        block2 = MagicMock(type="web_search", text=None)  # non-text block
        block3 = MagicMock(type="text", text="Part two.")

        response = MagicMock()
        response.content = [block1, block2, block3]
        response.usage.input_tokens = 100
        response.usage.output_tokens = 50

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.research.get_session", make_mock_get_session(db)):
            with patch("podcast.services.research.get_client", return_value=mock_client):
                from podcast.services.research import run_research

                metrics = await run_research(ep.id)

        assert ep.research_notes == "Part one. Part two."
        assert metrics["output_chars"] == len("Part one. Part two.")

    async def test_uses_web_search_tool(self):
        """Verify the Claude API call includes web_search tool."""
        ep = make_episode(topic="Test")
        db = _make_session_with_episode(ep)
        response = make_claude_response("research")
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("podcast.services.research.get_session", make_mock_get_session(db)):
            with patch("podcast.services.research.get_client", return_value=mock_client):
                from podcast.services.research import run_research

                await run_research(ep.id)

        call_kwargs = mock_client.messages.create.call_args[1]
        assert any(t["type"] == "web_search_20250305" for t in call_kwargs["tools"])
