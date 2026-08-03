"""Replace point-cloud snapshots with one complete current map.

Revision ID: 20260728_11
Revises: 20260723_10
Create Date: 2026-07-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260728_11"
down_revision = "20260723_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("mapping_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_index("ix_projects_mapping_enabled", "projects", ["mapping_enabled"])

    op.create_table(
        "pointcloud_maps",
        sa.Column("scope", sa.String(length=32), primary_key=True),
        sa.Column("map_id", sa.String(length=96), nullable=False, unique=True),
        sa.Column("source_id", sa.String(length=96), nullable=False),
        sa.Column("frame_id", sa.String(length=64), nullable=False),
        sa.Column("points", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pointcloud_maps_source_id", "pointcloud_maps", ["source_id"])
    op.create_index("ix_pointcloud_maps_observed_at", "pointcloud_maps", ["observed_at"])
    op.create_index("ix_pointcloud_maps_received_at", "pointcloud_maps", ["received_at"])

    # Preserve the newest real record during the one-time schema migration;
    # older snapshots are intentionally removed because the runtime now owns
    # one complete map only.
    op.execute(
        sa.text(
            """
            INSERT INTO pointcloud_maps
                (scope, map_id, source_id, frame_id, points, metadata, observed_at, received_at)
            SELECT 'current', event_id, source_id, frame_id, points, metadata, observed_at, received_at
            FROM pointcloud_snapshots
            ORDER BY observed_at DESC
            LIMIT 1
            """
        )
    )
    op.drop_table("pointcloud_snapshots")


def downgrade() -> None:
    op.create_table(
        "pointcloud_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", sa.String(length=96), nullable=False, unique=True),
        sa.Column("source_id", sa.String(length=96), nullable=False),
        sa.Column("frame_id", sa.String(length=64), nullable=False),
        sa.Column("points", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.drop_index("ix_pointcloud_maps_received_at", table_name="pointcloud_maps")
    op.drop_index("ix_pointcloud_maps_observed_at", table_name="pointcloud_maps")
    op.drop_index("ix_pointcloud_maps_source_id", table_name="pointcloud_maps")
    op.drop_table("pointcloud_maps")
    op.drop_index("ix_projects_mapping_enabled", table_name="projects")
    op.drop_column("projects", "mapping_enabled")
