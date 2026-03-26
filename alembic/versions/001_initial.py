"""Initial schema.

Revision ID: 001
Revises:
Create Date: 2026-03-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "episodes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("failed_step", sa.String(50), nullable=True),
        sa.Column("research_notes", sa.Text(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("audio_filename", sa.String(255), nullable=True),
        sa.Column("audio_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("audio_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("episode_number", sa.Integer(), nullable=True),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_episodes_status", "episodes", ["status"])
    op.create_index(
        "idx_episodes_published_at", "episodes", [sa.text("published_at DESC")]
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("episode_id", sa.Uuid(), nullable=False),
        sa.Column("step", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["episode_id"], ["episodes.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_jobs_status", "jobs", ["status", "created_at"])
    op.create_index("idx_jobs_episode_id", "jobs", ["episode_id"])

    op.create_table(
        "podcast_settings",
        sa.Column("id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "title",
            sa.String(500),
            nullable=False,
            server_default="My Private Podcast",
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default="AI-generated podcast episodes",
        ),
        sa.Column(
            "author", sa.String(255), nullable=False, server_default="Podcast Bot"
        ),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("image_url", sa.String(1000), nullable=True),
        sa.Column(
            "host_a_name", sa.String(100), nullable=False, server_default="Alex"
        ),
        sa.Column(
            "host_b_name", sa.String(100), nullable=False, server_default="Sam"
        ),
        sa.Column("voice_ref_a_path", sa.String(500), nullable=True),
        sa.Column("voice_ref_b_path", sa.String(500), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = 1", name="single_row_settings"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Seed default settings row
    op.execute(
        "INSERT INTO podcast_settings (id) VALUES (1) ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("podcast_settings")
    op.drop_table("jobs")
    op.drop_table("episodes")
