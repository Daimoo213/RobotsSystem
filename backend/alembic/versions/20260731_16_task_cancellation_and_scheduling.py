"""Add safe task-cancellation and automatic-scheduling state.

Revision ID: 20260731_16
Revises: 20260731_15
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_16"
down_revision = "20260731_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("schedule_mode", sa.String(length=16), nullable=False, server_default="auto"),
    )
    op.add_column("tasks", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tasks_schedule_mode", "tasks", ["schedule_mode"], unique=False)
    op.create_check_constraint(
        "ck_tasks_schedule_mode",
        "tasks",
        "schedule_mode IN ('auto', 'fixed')",
    )
    # Preserve historical plans as operator-fixed. Dependency-driven tasks are
    # safely migrated to automatic mode without creating any task records.
    op.execute(
        """
        UPDATE tasks
        SET schedule_mode = CASE
            WHEN jsonb_array_length(COALESCE(dependencies, '[]'::jsonb)) > 0 THEN 'auto'
            WHEN planned_start IS NOT NULL THEN 'fixed'
            ELSE 'auto'
        END
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_tasks_schedule_mode", "tasks", type_="check")
    op.drop_index("ix_tasks_schedule_mode", table_name="tasks")
    op.drop_column("tasks", "cancelled_at")
    op.drop_column("tasks", "schedule_mode")
