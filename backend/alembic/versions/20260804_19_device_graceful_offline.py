"""Persist gateway-reported graceful device disconnects.

Revision ID: 20260804_19
Revises: 20260804_18
Create Date: 2026-08-04
"""

from alembic import op
import sqlalchemy as sa


revision = "20260804_19"
down_revision = "20260804_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("offline_reported_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("devices", sa.Column("offline_reason_code", sa.String(length=32), nullable=True))
    op.add_column("devices", sa.Column("offline_note", sa.String(length=512), nullable=True))
    op.add_column("devices", sa.Column("offline_expected_reconnect_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_devices_offline_reported_at", "devices", ["offline_reported_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_devices_offline_reported_at", table_name="devices")
    op.drop_column("devices", "offline_expected_reconnect_at")
    op.drop_column("devices", "offline_note")
    op.drop_column("devices", "offline_reason_code")
    op.drop_column("devices", "offline_reported_at")
