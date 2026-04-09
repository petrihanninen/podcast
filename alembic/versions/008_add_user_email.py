"""Add email column to users table.

Revision ID: 008
Revises: 007
Create Date: 2026-04-09
"""

from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(320), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "email")
