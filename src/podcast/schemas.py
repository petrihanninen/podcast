import uuid
from datetime import datetime

from pydantic import BaseModel


class EpisodeCreate(BaseModel):
    topic: str
    title: str | None = None
    description: str | None = None


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

    model_config = {"from_attributes": True}


class EpisodeListItem(BaseModel):
    id: uuid.UUID
    title: str
    topic: str
    status: str
    episode_number: int | None
    audio_duration_seconds: int | None
    published_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SettingsUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    author: str | None = None
    language: str | None = None
    image_url: str | None = None
    host_a_name: str | None = None
    host_b_name: str | None = None


class SettingsResponse(BaseModel):
    title: str
    description: str
    author: str
    language: str
    image_url: str | None
    host_a_name: str
    host_b_name: str

    model_config = {"from_attributes": True}
