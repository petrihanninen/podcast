"""Add research_model and transcript_model columns to episodes table.

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
    op.add_column("episodes", sa.Column("research_model", sa.String(100), nullable=True))
    op.add_column("episodes", sa.Column("transcript_model", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("episodes", "transcript_model")
    op.drop_column("episodes", "research_model")
