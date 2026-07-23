"""Add persisted colors for map point and region grid annotations.

Revision ID: 20260723_10
Revises: 20260721_09
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260723_10"
down_revision = "20260721_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "map_regions",
        sa.Column("color", sa.String(length=7), server_default="#2FD7FF", nullable=False),
    )
    op.add_column(
        "map_points",
        sa.Column("color", sa.String(length=7), server_default="#2FD7FF", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("map_points", "color")
    op.drop_column("map_regions", "color")
