"""Require each robot road to be stored by exactly two endpoints.

Revision ID: 20260804_18
Revises: 20260803_17
Create Date: 2026-08-04
"""

from alembic import op


revision = "20260804_18"
down_revision = "20260803_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_map_paths_two_endpoints",
        "map_paths",
        "jsonb_array_length(points) = 2",
    )


def downgrade() -> None:
    op.drop_constraint("ck_map_paths_two_endpoints", "map_paths", type_="check")
