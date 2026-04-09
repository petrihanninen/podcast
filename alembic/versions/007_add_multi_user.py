"""Add multi-user support: users table, user_id FKs on episodes and podcast_settings.

Revision ID: 007
Revises: 006
Create Date: 2026-04-09

WARNING: This migration wipes all existing episodes, jobs, and podcast_settings data.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Wipe existing data (FK order: jobs -> episodes -> podcast_settings)
    op.execute("TRUNCATE jobs, episodes CASCADE")
    op.drop_table("podcast_settings")

    # 2. Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shoo_sub", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("feed_token", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shoo_sub"),
        sa.UniqueConstraint("feed_token"),
    )

    # 3. Add user_id to episodes
    op.add_column("episodes", sa.Column("user_id", sa.Uuid(), nullable=False))
    op.create_foreign_key(
        "fk_episodes_user_id", "episodes", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("idx_episodes_user_id", "episodes", ["user_id"])

    # 4. Recreate podcast_settings with UUID PK and user_id FK (no singleton constraint)
    op.create_table(
        "podcast_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False, server_default="My Private Podcast"),
        sa.Column("description", sa.Text(), nullable=False, server_default="AI-generated podcast episodes"),
        sa.Column("author", sa.String(255), nullable=False, server_default="Podcast Bot"),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("image_url", sa.String(1000), nullable=True),
        sa.Column("host_a_name", sa.String(100), nullable=False, server_default="Alex"),
        sa.Column("host_b_name", sa.String(100), nullable=False, server_default="Sam"),
        sa.Column("voice_ref_a_path", sa.String(500), nullable=True),
        sa.Column("voice_ref_b_path", sa.String(500), nullable=True),
        sa.Column("transcript_tone_notes", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
    )


def downgrade() -> None:
    # Drop new tables / columns in reverse order
    op.drop_table("podcast_settings")
    op.drop_index("idx_episodes_user_id", table_name="episodes")
    op.drop_constraint("fk_episodes_user_id", "episodes", type_="foreignkey")
    op.drop_column("episodes", "user_id")
    op.drop_table("users")

    # Recreate original singleton podcast_settings
    op.create_table(
        "podcast_settings",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("title", sa.String(500), nullable=False, server_default="My Private Podcast"),
        sa.Column("description", sa.Text(), nullable=False, server_default="AI-generated podcast episodes"),
        sa.Column("author", sa.String(255), nullable=False, server_default="Podcast Bot"),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("image_url", sa.String(1000), nullable=True),
        sa.Column("host_a_name", sa.String(100), nullable=False, server_default="Alex"),
        sa.Column("host_b_name", sa.String(100), nullable=False, server_default="Sam"),
        sa.Column("voice_ref_a_path", sa.String(500), nullable=True),
        sa.Column("voice_ref_b_path", sa.String(500), nullable=True),
        sa.Column("transcript_tone_notes", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="single_row_settings"),
    )
    op.execute("INSERT INTO podcast_settings (id) VALUES (1)")
