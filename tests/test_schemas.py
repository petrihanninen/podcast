"""Tests for podcast.schemas (Pydantic models)."""

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from podcast.schemas import (
    EpisodeCreate,
    EpisodeListItem,
    EpisodeResponse,
    JobResponse,
    LogEntryResponse,
    LogListResponse,
    SettingsResponse,
    SettingsUpdate,
)


class TestEpisodeCreate:
    def test_valid_with_topic_only(self):
        data = EpisodeCreate(topic="AI advancements")
        assert data.topic == "AI advancements"
        assert data.title is None
        assert data.description is None

    def test_valid_with_all_fields(self):
        data = EpisodeCreate(
            topic="AI advancements",
            title="Episode 1",
            description="About AI",
        )
        assert data.topic == "AI advancements"
        assert data.title == "Episode 1"
        assert data.description == "About AI"

    def test_missing_topic_raises(self):
        with pytest.raises(ValidationError):
            EpisodeCreate()

    def test_empty_string_topic_accepted(self):
        """Pydantic allows empty string for str fields by default."""
        data = EpisodeCreate(topic="")
        assert data.topic == ""


class TestJobResponse:
    def test_from_attributes(self):
        now = datetime.now(timezone.utc)
        job_id = uuid.uuid4()

        class FakeJob:
            id = job_id
            step = "research"
            status = "completed"
            error_message = None
            attempts = 1
            created_at = now
            started_at = now
            completed_at = now

        resp = JobResponse.model_validate(FakeJob(), from_attributes=True)
        assert resp.id == job_id
        assert resp.step == "research"
        assert resp.status == "completed"
        assert resp.attempts == 1

    def test_nullable_fields(self):
        now = datetime.now(timezone.utc)
        data = JobResponse(
            id=uuid.uuid4(),
            step="tts",
            status="pending",
            error_message=None,
            attempts=0,
            created_at=now,
            started_at=None,
            completed_at=None,
        )
        assert data.started_at is None
        assert data.completed_at is None


class TestEpisodeResponse:
    def test_complete_episode(self):
        now = datetime.now(timezone.utc)
        ep_id = uuid.uuid4()
        data = EpisodeResponse(
            id=ep_id,
            title="Test",
            description=None,
            topic="Topic",
            status="ready",
            error_message=None,
            failed_step=None,
            research_notes="notes",
            transcript='[{"speaker":"A","text":"hi"}]',
            audio_filename="test.mp3",
            audio_duration_seconds=120,
            audio_size_bytes=1024000,
            episode_number=1,
            published_at=now,
            created_at=now,
            updated_at=now,
            jobs=[],
        )
        assert data.id == ep_id
        assert data.status == "ready"
        assert data.audio_filename == "test.mp3"

    def test_default_jobs_empty_list(self):
        now = datetime.now(timezone.utc)
        data = EpisodeResponse(
            id=uuid.uuid4(),
            title="Test",
            description=None,
            topic="Topic",
            status="pending",
            error_message=None,
            failed_step=None,
            research_notes=None,
            transcript=None,
            audio_filename=None,
            audio_duration_seconds=None,
            audio_size_bytes=None,
            episode_number=None,
            published_at=None,
            created_at=now,
            updated_at=now,
        )
        assert data.jobs == []


class TestEpisodeListItem:
    def test_minimal_episode(self):
        now = datetime.now(timezone.utc)
        data = EpisodeListItem(
            id=uuid.uuid4(),
            title="Test",
            topic="Topic",
            status="pending",
            episode_number=None,
            audio_duration_seconds=None,
            published_at=None,
            created_at=now,
        )
        assert data.episode_number is None
        assert data.published_at is None


class TestSettingsUpdate:
    def test_all_none_by_default(self):
        data = SettingsUpdate()
        assert data.title is None
        assert data.description is None
        assert data.author is None

    def test_partial_update(self):
        data = SettingsUpdate(title="New Title", author="New Author")
        assert data.title == "New Title"
        assert data.author == "New Author"
        assert data.language is None

    def test_exclude_unset(self):
        data = SettingsUpdate(title="New Title")
        dumped = data.model_dump(exclude_unset=True)
        assert dumped == {"title": "New Title"}
        assert "description" not in dumped


class TestSettingsResponse:
    def test_from_attributes(self):
        class FakeSettings:
            title = "My Podcast"
            description = "A podcast"
            author = "Author"
            language = "en"
            image_url = None
            host_a_name = "Alex"
            host_b_name = "Sam"

        resp = SettingsResponse.model_validate(FakeSettings(), from_attributes=True)
        assert resp.title == "My Podcast"
        assert resp.host_a_name == "Alex"
        assert resp.image_url is None


class TestLogEntryResponse:
    def test_from_attributes(self):
        now = datetime.now(timezone.utc)

        class FakeLog:
            id = 42
            timestamp = now
            level = "ERROR"
            logger_name = "podcast.worker"
            message = "Something failed"
            source = "worker"

        resp = LogEntryResponse.model_validate(FakeLog(), from_attributes=True)
        assert resp.id == 42
        assert resp.level == "ERROR"
        assert resp.source == "worker"


class TestLogListResponse:
    def test_structure(self):
        data = LogListResponse(
            logs=[],
            total=0,
            page=1,
            page_size=100,
            has_more=False,
        )
        assert data.logs == []
        assert data.total == 0
        assert data.has_more is False

    def test_has_more_true(self):
        data = LogListResponse(
            logs=[],
            total=150,
            page=1,
            page_size=100,
            has_more=True,
        )
        assert data.has_more is True
