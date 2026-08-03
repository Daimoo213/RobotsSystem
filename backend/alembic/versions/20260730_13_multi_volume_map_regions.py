"""Store multiple three-dimensional volume components for one map region.

Revision ID: 20260730_13
Revises: 20260730_12
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260730_13"
down_revision = "20260730_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "map_regions",
        sa.Column(
            "volumes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("map_regions", "volumes", server_default=None)


def downgrade() -> None:
    op.drop_column("map_regions", "volumes")
