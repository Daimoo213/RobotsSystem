"""Add persistent 3D map-grid settings and vertical region bounds.

Revision ID: 20260730_12
Revises: 20260728_11
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260730_12"
down_revision = "20260728_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "map_grid_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("projects", "map_grid_config", server_default=None)
    op.add_column("map_regions", sa.Column("min_z", sa.Float(), nullable=False, server_default="0"))
    op.add_column("map_regions", sa.Column("max_z", sa.Float(), nullable=False, server_default="0.5"))
    op.alter_column("map_regions", "min_z", server_default=None)
    op.alter_column("map_regions", "max_z", server_default=None)


def downgrade() -> None:
    op.drop_column("map_regions", "max_z")
    op.drop_column("map_regions", "min_z")
    op.drop_column("projects", "map_grid_config")
