"""camera stream metadata

Revision ID: 20260720_03
Revises: 20260720_02
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa

revision = "20260720_03"
down_revision = "20260720_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("stream_url", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("cameras", "stream_url")
