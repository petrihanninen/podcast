import json
import os
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TtsProgress(BaseModel):
    segments_completed: int
    total_segments: int
    audio_duration_seconds: float


class EpisodeCreate(BaseModel):
    topic: str = Field(..., min_length=1, max_length=5000)
    title: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=5000)
    target_length_minutes: Literal[15, 30, 60, 120] = 30
    research_model: str | None = None      # Registry key, e.g. "claude-sonnet"
    transcript_model: str | None = None    # Registry key, e.g. "deepseek"


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
    research_model: str | None
    transcript_model: str | None
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
    title: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=2000)
    author: str | None = Field(None, max_length=200)
    language: str | None = Field(None, max_length=10)
    image_url: str | None = Field(None, max_length=500)
    host_a_name: str | None = Field(None, max_length=50)
    host_b_name: str | None = Field(None, max_length=50)
    voice_ref_a_path: str | None = None
    voice_ref_b_path: str | None = None
    transcript_tone_notes: list[str] | None = Field(None, max_length=20)

    @field_validator("voice_ref_a_path", "voice_ref_b_path", mode="before")
    @classmethod
    def _validate_voice_filename(cls, v: str | None) -> str | None:
        if v is None:
            return v
        basename = os.path.basename(v)
        if basename != v or ".." in v:
            raise ValueError("Must be a simple filename, not a path")
        return basename


class SettingsResponse(BaseModel):
    title: str
    description: str
    author: str
    language: str
    image_url: str | None
    host_a_name: str
    host_b_name: str
    voice_ref_a_path: str | None
    voice_ref_b_path: str | None
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
