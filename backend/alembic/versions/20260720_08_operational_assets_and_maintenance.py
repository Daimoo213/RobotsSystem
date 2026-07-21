"""operational assets, telemetry metrics, and maintenance work orders

Revision ID: 20260720_08
Revises: 20260720_07
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260720_08"
down_revision = "20260720_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("operational_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.alter_column("devices", "operational_metrics", server_default=None)
    op.add_column("map_points", sa.Column("qrcode_id", sa.String(96), nullable=True))
    op.add_column("map_points", sa.Column("qrcode_type", sa.String(32), nullable=True))
    op.create_unique_constraint("uq_map_points_qrcode_id", "map_points", ["qrcode_id"])
    op.create_table(
        "map_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", sa.String(96), nullable=False, unique=True),
        sa.Column("source_id", sa.String(96), nullable=False),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("asset_uri", sa.String(1024), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("frame_id", sa.String(64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_map_assets_source_id", "map_assets", ["source_id"])
    op.create_index("ix_map_assets_asset_type", "map_assets", ["asset_type"])
    op.create_index("ix_map_assets_observed_at", "map_assets", ["observed_at"])
    op.create_index("ix_map_assets_received_at", "map_assets", ["received_at"])
    op.create_table(
        "maintenance_work_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("observed_value", sa.Float(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_maintenance_work_orders_device_id", "maintenance_work_orders", ["device_id"])
    op.create_index("ix_maintenance_work_orders_trigger_type", "maintenance_work_orders", ["trigger_type"])
    op.create_index("ix_maintenance_work_orders_status", "maintenance_work_orders", ["status"])


def downgrade() -> None:
    op.drop_table("maintenance_work_orders")
    op.drop_table("map_assets")
    op.drop_constraint("uq_map_points_qrcode_id", "map_points", type_="unique")
    op.drop_column("map_points", "qrcode_type")
    op.drop_column("map_points", "qrcode_id")
    op.drop_column("devices", "operational_metrics")
