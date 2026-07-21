"""remove obsolete alert foreign-key index

Revision ID: 20260720_06
Revises: 20260720_05
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa

revision = "20260720_06"
down_revision = "20260720_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_alerts_device_id"))


def downgrade() -> None:
    op.create_index("ix_alerts_device_id", "alerts", ["device_id"])
