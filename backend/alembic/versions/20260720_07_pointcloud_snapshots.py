"""point-cloud snapshots

Revision ID: 20260720_07
Revises: 20260720_06
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260720_07"
down_revision = "20260720_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pointcloud_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", sa.String(96), nullable=False, unique=True),
        sa.Column("source_id", sa.String(96), nullable=False),
        sa.Column("frame_id", sa.String(64), nullable=False),
        sa.Column("points", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pointcloud_snapshots_source_id", "pointcloud_snapshots", ["source_id"])
    op.create_index("ix_pointcloud_snapshots_observed_at", "pointcloud_snapshots", ["observed_at"])
    op.create_index("ix_pointcloud_snapshots_received_at", "pointcloud_snapshots", ["received_at"])


def downgrade() -> None:
    op.drop_table("pointcloud_snapshots")
