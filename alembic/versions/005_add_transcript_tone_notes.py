"""Add transcript_tone_notes column to podcast_settings.

Revision ID: 005
Revises: 004
Create Date: 2026-04-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "podcast_settings",
        sa.Column("transcript_tone_notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("podcast_settings", "transcript_tone_notes")
