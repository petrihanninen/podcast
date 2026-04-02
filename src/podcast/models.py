import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    target_length_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    failed_step: Mapped[str | None] = mapped_column(String(50))

    research_notes: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)  # JSON array of segments

    audio_filename: Mapped[str | None] = mapped_column(String(255))
    audio_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    audio_size_bytes: Mapped[int | None] = mapped_column(BigInteger)

    episode_number: Mapped[int | None] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    jobs: Mapped[list["Job"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_episodes_status", "status"),
        Index("idx_episodes_published_at", published_at.desc()),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metrics_json: Mapped[str | None] = mapped_column(Text)

    episode: Mapped["Episode"] = relationship(back_populates="jobs")

    __table_args__ = (
        Index("idx_jobs_status", "status", "created_at"),
        Index("idx_jobs_episode_id", "episode_id"),
    )


class PodcastSettings(Base):
    __tablename__ = "podcast_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    title: Mapped[str] = mapped_column(
        String(500), nullable=False, default="My Private Podcast"
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="AI-generated podcast episodes"
    )
    author: Mapped[str] = mapped_column(
        String(255), nullable=False, default="Podcast Bot"
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    image_url: Mapped[str | None] = mapped_column(String(1000))

    host_a_name: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Alex"
    )
    host_b_name: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Sam"
    )
    voice_ref_a_path: Mapped[str | None] = mapped_column(String(500))
    voice_ref_b_path: Mapped[str | None] = mapped_column(String(500))

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (CheckConstraint("id = 1", name="single_row_settings"),)


class LogEntry(Base):
    __tablename__ = "log_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    logger_name: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)

    __table_args__ = (
        Index("idx_log_entries_timestamp", timestamp.desc()),
        Index("idx_log_entries_level", "level"),
        Index("idx_log_entries_source", "source"),
    )
