"""Shared fixtures for podcast application tests."""

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from podcast.models import Episode, Job, LogEntry, PodcastSettings


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------


@pytest.fixture
def episode_id():
    return uuid.uuid4()


@pytest.fixture
def job_id():
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Mock database session
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """Create a mock AsyncSession suitable for unit tests."""
    db = AsyncMock()
    db.add = MagicMock()
    return db


def make_mock_get_session(db_mock):
    """Create a mock get_session() async context manager that yields db_mock."""

    @asynccontextmanager
    async def _get_session():
        yield db_mock

    return _get_session


# ---------------------------------------------------------------------------
# Model factory helpers
# ---------------------------------------------------------------------------


def make_episode(**overrides) -> MagicMock:
    """Create a mock Episode with sensible defaults."""
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid.uuid4(),
        "title": "Test Episode",
        "description": "A test episode",
        "topic": "Test Topic",
        "status": "pending",
        "error_message": None,
        "failed_step": None,
        "research_notes": None,
        "transcript": None,
        "audio_filename": None,
        "audio_duration_seconds": None,
        "audio_size_bytes": None,
        "episode_number": None,
        "published_at": None,
        "created_at": now,
        "updated_at": now,
        "jobs": [],
    }
    defaults.update(overrides)
    ep = MagicMock(spec=Episode)
    for k, v in defaults.items():
        setattr(ep, k, v)
    return ep


def make_job(**overrides) -> MagicMock:
    """Create a mock Job with sensible defaults."""
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid.uuid4(),
        "episode_id": uuid.uuid4(),
        "step": "research",
        "status": "pending",
        "error_message": None,
        "attempts": 0,
        "max_attempts": 3,
        "created_at": now,
        "started_at": None,
        "completed_at": None,
        "metrics_json": None,
    }
    defaults.update(overrides)
    job = MagicMock(spec=Job)
    for k, v in defaults.items():
        setattr(job, k, v)
    return job


def make_settings(**overrides) -> MagicMock:
    """Create a mock PodcastSettings with sensible defaults."""
    defaults = {
        "id": 1,
        "title": "My Podcast",
        "description": "A test podcast",
        "author": "Test Author",
        "language": "en",
        "image_url": None,
        "host_a_name": "Alex",
        "host_b_name": "Sam",
        "voice_ref_a_path": None,
        "voice_ref_b_path": None,
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    s = MagicMock(spec=PodcastSettings)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def make_log_entry(**overrides) -> MagicMock:
    """Create a mock LogEntry."""
    defaults = {
        "id": 1,
        "timestamp": datetime.now(timezone.utc),
        "level": "INFO",
        "logger_name": "test",
        "message": "Test log message",
        "source": "web",
    }
    defaults.update(overrides)
    entry = MagicMock(spec=LogEntry)
    for k, v in defaults.items():
        setattr(entry, k, v)
    return entry


# ---------------------------------------------------------------------------
# Claude API mock helpers
# ---------------------------------------------------------------------------


def make_claude_response(text: str, input_tokens: int = 100, output_tokens: int = 200):
    """Create a mock Claude API response."""
    block = MagicMock()
    block.type = "text"
    block.text = text

    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens

    response = MagicMock()
    response.content = [block]
    response.usage = usage
    return response
