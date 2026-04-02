import json
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator


class TtsProgress(BaseModel):
    segments_completed: int
    total_segments: int
    audio_duration_seconds: float


class EpisodeCreate(BaseModel):
    topic: str
    title: str | None = None
    description: str | None = None
    target_length_minutes: Literal[15, 30, 60, 120] = 30


class JobResponse(BaseModel):
    id: uuid.UUID
    step: str
    status: str
    error_message: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class EpisodeResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    topic: str
    target_length_minutes: int
    status: str
    error_message: str | None
    failed_step: str | None
    research_notes: str | None
    transcript: str | None
    audio_filename: str | None
    audio_duration_seconds: int | None
    audio_size_bytes: int | None
    episode_number: int | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    jobs: list[JobResponse] = []
    tts_progress: TtsProgress | None = None

    model_config = {"from_attributes": True}


class EpisodeListItem(BaseModel):
    id: uuid.UUID
    title: str
    topic: str
    target_length_minutes: int
    status: str
    episode_number: int | None
    audio_duration_seconds: int | None
    published_at: datetime | None
    created_at: datetime
    tts_progress: TtsProgress | None = None

    model_config = {"from_attributes": True}


class SettingsUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    author: str | None = None
    language: str | None = None
    image_url: str | None = None
    host_a_name: str | None = None
    host_b_name: str | None = None
    transcript_tone_notes: list[str] | None = None


class SettingsResponse(BaseModel):
    title: str
    description: str
    author: str
    language: str
    image_url: str | None
    host_a_name: str
    host_b_name: str
    transcript_tone_notes: list[str] = None  # type: ignore[assignment]

    model_config = {"from_attributes": True}

    @field_validator("transcript_tone_notes", mode="before")
    @classmethod
    def _parse_tone_notes(cls, v: str | list | None) -> list[str]:
        from podcast.services.transcript import DEFAULT_TONE_NOTES

        if v is None:
            return list(DEFAULT_TONE_NOTES)
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else list(DEFAULT_TONE_NOTES)
            except (json.JSONDecodeError, TypeError):
                return list(DEFAULT_TONE_NOTES)
        return v


class LogEntryResponse(BaseModel):
    id: int
    timestamp: datetime
    level: str
    logger_name: str
    message: str
    source: str

    model_config = {"from_attributes": True}


class LogListResponse(BaseModel):
    logs: list[LogEntryResponse]
    total: int
    page: int
    page_size: int
    has_more: bool
