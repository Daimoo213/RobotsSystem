"""Persist robot traversable paths and their route constraints.

Revision ID: 20260803_17
Revises: 20260731_16
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260803_17"
down_revision = "20260731_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "map_paths",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("points", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "direction",
            sa.String(length=16),
            nullable=False,
            server_default="bidirectional",
        ),
        sa.Column("min_width_m", sa.Float(), nullable=False),
        sa.Column("max_slope_percent", sa.Float(), nullable=False),
        sa.Column(
            "device_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("min_width_m > 0", name="ck_map_paths_min_width_positive"),
        sa.CheckConstraint("max_slope_percent >= 0", name="ck_map_paths_max_slope_nonnegative"),
        sa.CheckConstraint(
            "direction IN ('bidirectional', 'forward', 'reverse')",
            name="ck_map_paths_direction",
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_map_paths_status"),
    )
    op.create_index("ix_map_paths_status", "map_paths", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_map_paths_status", table_name="map_paths")
    op.drop_table("map_paths")
