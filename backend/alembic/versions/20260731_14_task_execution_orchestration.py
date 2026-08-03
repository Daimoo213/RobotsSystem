"""Add durable dispatch waiting and mission return orchestration.

Revision ID: 20260731_14
Revises: 20260730_13
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260731_14"
down_revision = "20260730_13"
branch_labels = None
depends_on = None


ACTIVE_EXECUTION_PREDICATE = (
    "state IN ('dispatched','accepted','running','paused',"
    "'pause_requested','resume_requested','cancel_requested')"
)


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("protocol_version", sa.String(length=16), nullable=False, server_default="v1"),
    )
    op.create_index("ix_devices_protocol_version", "devices", ["protocol_version"], unique=False)

    op.add_column("tasks", sa.Column("return_point_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_tasks_return_point_id_map_points",
        "tasks",
        "map_points",
        ["return_point_id"],
        ["id"],
    )
    op.add_column(
        "tasks",
        sa.Column("return_policy", sa.String(length=24), nullable=False, server_default="stay"),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "work_parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "tasks",
        sa.Column("dispatch_state", sa.String(length=32), nullable=False, server_default="waiting_device"),
    )
    op.add_column("tasks", sa.Column("dispatch_reason", sa.String(length=64), nullable=True))
    op.add_column(
        "tasks",
        sa.Column("dispatch_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("tasks", sa.Column("last_dispatch_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("current_phase", sa.String(length=32), nullable=True))
    op.create_index("ix_tasks_dispatch_state", "tasks", ["dispatch_state"], unique=False)

    op.execute(
        """
        UPDATE tasks
        SET dispatch_state = CASE
            WHEN status IN ('assigned', 'running', 'paused', 'reassign_pending') THEN 'dispatched'
            WHEN status = 'completed' THEN 'finished'
            WHEN status = 'failed' THEN 'failed'
            WHEN jsonb_array_length(COALESCE(dependencies, '[]'::jsonb)) > 0 THEN 'waiting_dependencies'
            ELSE 'waiting_device'
        END
        """
    )

    op.add_column(
        "mission_executions",
        sa.Column("protocol_version", sa.String(length=16), nullable=False, server_default="v1"),
    )
    op.add_column(
        "mission_executions",
        sa.Column("phase", sa.String(length=32), nullable=False, server_default="preparing"),
    )
    op.add_column(
        "mission_executions",
        sa.Column("phase_sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "mission_executions",
        sa.Column("phase_progress", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "mission_executions",
        sa.Column("phase_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mission_executions_phase", "mission_executions", ["phase"], unique=False)
    op.create_index(
        "ix_mission_executions_protocol_version",
        "mission_executions",
        ["protocol_version"],
        unique=False,
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT task_id FROM mission_executions
                WHERE {ACTIVE_EXECUTION_PREDICATE}
                GROUP BY task_id HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION 'migration blocked: one task has multiple active mission executions';
            END IF;
            IF EXISTS (
                SELECT device_id FROM mission_executions
                WHERE {ACTIVE_EXECUTION_PREDICATE}
                GROUP BY device_id HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION 'migration blocked: one device has multiple active mission executions';
            END IF;
        END $$;
        """
    )
    op.create_index(
        "uq_mission_executions_active_task",
        "mission_executions",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_EXECUTION_PREDICATE),
    )
    op.create_index(
        "uq_mission_executions_active_device",
        "mission_executions",
        ["device_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_EXECUTION_PREDICATE),
    )

    op.alter_column("tasks", "return_policy", server_default=None)
    op.alter_column("tasks", "work_parameters", server_default=None)
    op.alter_column("tasks", "dispatch_state", server_default=None)
    op.alter_column("tasks", "dispatch_attempts", server_default=None)
    op.alter_column("devices", "protocol_version", server_default=None)
    op.alter_column("mission_executions", "protocol_version", server_default=None)
    op.alter_column("mission_executions", "phase", server_default=None)
    op.alter_column("mission_executions", "phase_sequence", server_default=None)
    op.alter_column("mission_executions", "phase_progress", server_default=None)


def downgrade() -> None:
    op.drop_index("uq_mission_executions_active_device", table_name="mission_executions")
    op.drop_index("uq_mission_executions_active_task", table_name="mission_executions")
    op.drop_index("ix_mission_executions_protocol_version", table_name="mission_executions")
    op.drop_index("ix_mission_executions_phase", table_name="mission_executions")
    op.drop_column("mission_executions", "phase_updated_at")
    op.drop_column("mission_executions", "phase_progress")
    op.drop_column("mission_executions", "phase_sequence")
    op.drop_column("mission_executions", "phase")
    op.drop_column("mission_executions", "protocol_version")

    op.drop_index("ix_tasks_dispatch_state", table_name="tasks")
    op.drop_column("tasks", "current_phase")
    op.drop_column("tasks", "last_dispatch_attempt_at")
    op.drop_column("tasks", "dispatch_attempts")
    op.drop_column("tasks", "dispatch_reason")
    op.drop_column("tasks", "dispatch_state")
    op.drop_column("tasks", "work_parameters")
    op.drop_column("tasks", "return_policy")
    op.drop_constraint("fk_tasks_return_point_id_map_points", "tasks", type_="foreignkey")
    op.drop_column("tasks", "return_point_id")

    op.drop_index("ix_devices_protocol_version", table_name="devices")
    op.drop_column("devices", "protocol_version")
