"""Add auditable capacity planning and multi-device task allocations.

Revision ID: 20260731_15
Revises: 20260731_14
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260731_15"
down_revision = "20260731_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_work_capacities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability_code", sa.String(length=64), nullable=False),
        sa.Column("output_unit", sa.String(length=32), nullable=False),
        sa.Column("rate_per_hour", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("evidence_ref", sa.String(length=256), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("rate_per_hour > 0", name="ck_device_work_capacity_positive_rate"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "capability_code", "output_unit", name="uq_device_work_capacity"),
    )
    op.create_index("ix_device_work_capacities_device_id", "device_work_capacities", ["device_id"], unique=False)
    op.create_index("ix_device_work_capacities_capability_code", "device_work_capacities", ["capability_code"], unique=False)
    op.create_index(
        "ix_device_work_capacities_capability_unit",
        "device_work_capacities",
        ["capability_code", "output_unit"],
        unique=False,
    )
    op.create_index("ix_device_work_capacities_valid_until", "device_work_capacities", ["valid_until"], unique=False)

    op.create_table(
        "task_resource_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=96), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("required_rate_per_hour", sa.Float(), nullable=True),
        sa.Column("planned_rate_per_hour", sa.Float(), nullable=False),
        sa.Column("coverage_ratio", sa.Float(), nullable=False),
        sa.Column("predicted_completion_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("coverage_ratio >= 0", name="ck_task_resource_plan_coverage_nonnegative"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index("ix_task_resource_plans_state", "task_resource_plans", ["state"], unique=False)

    op.create_table(
        "task_resource_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_code", sa.String(length=64), nullable=False),
        sa.Column("capability_code", sa.String(length=64), nullable=False),
        sa.Column("required_qty", sa.Float(), nullable=False),
        sa.Column("output_unit", sa.String(length=32), nullable=False),
        sa.Column("completed_qty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_completion_gate", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("work_scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("required_qty > 0", name="ck_task_resource_requirement_positive_qty"),
        sa.CheckConstraint("completed_qty >= 0", name="ck_task_resource_requirement_completed_nonnegative"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_resource_requirements_task_id", "task_resource_requirements", ["task_id"], unique=False)
    op.create_index("ix_task_resource_requirements_capability_code", "task_resource_requirements", ["capability_code"], unique=False)
    op.create_index(
        "ix_task_resource_requirements_task_gate",
        "task_resource_requirements",
        ["task_id", "is_completion_gate"],
        unique=False,
    )

    op.create_table(
        "task_resource_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requirement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_revision", sa.Integer(), nullable=False),
        sa.Column("planned_qty", sa.Float(), nullable=False),
        sa.Column("completed_qty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("output_unit", sa.String(length=32), nullable=False),
        sa.Column("rate_per_hour_snapshot", sa.Float(), nullable=False),
        sa.Column("capacity_source", sa.String(length=32), nullable=False),
        sa.Column("capacity_evidence_ref", sa.String(length=256), nullable=False),
        sa.Column("capacity_reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("work_scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("available_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("predicted_finish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("planned_qty > 0", name="ck_task_resource_allocation_positive_qty"),
        sa.CheckConstraint("completed_qty >= 0", name="ck_task_resource_allocation_completed_nonnegative"),
        sa.CheckConstraint("rate_per_hour_snapshot > 0", name="ck_task_resource_allocation_positive_rate"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requirement_id"], ["task_resource_requirements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_resource_allocations_task_id", "task_resource_allocations", ["task_id"], unique=False)
    op.create_index("ix_task_resource_allocations_requirement_id", "task_resource_allocations", ["requirement_id"], unique=False)
    op.create_index("ix_task_resource_allocations_device_id", "task_resource_allocations", ["device_id"], unique=False)
    op.create_index("ix_task_resource_allocations_state", "task_resource_allocations", ["state"], unique=False)
    op.create_index(
        "ix_task_resource_allocations_task_state",
        "task_resource_allocations",
        ["task_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_task_resource_allocations_device_state",
        "task_resource_allocations",
        ["device_id", "state"],
        unique=False,
    )

    op.add_column("mission_executions", sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("mission_executions", sa.Column("planned_qty", sa.Float(), nullable=True))
    op.add_column("mission_executions", sa.Column("output_unit", sa.String(length=32), nullable=True))
    op.add_column("mission_executions", sa.Column("rate_per_hour_snapshot", sa.Float(), nullable=True))
    op.create_foreign_key(
        "fk_mission_executions_allocation_id",
        "mission_executions",
        "task_resource_allocations",
        ["allocation_id"],
        ["id"],
    )
    op.create_index("ix_mission_executions_allocation_id", "mission_executions", ["allocation_id"], unique=False)
    op.drop_index("uq_mission_executions_active_task", table_name="mission_executions")

    # Existing tasks remain real historical input. Mark only incomplete work
    # that cannot be capacity-planned; do not create fictional requirements.
    op.execute(
        """
        UPDATE tasks
        SET dispatch_state = 'waiting_planning_input',
            dispatch_reason = 'planning_input_required'
        WHERE status = 'pending'
          AND (deliverable_qty IS NULL OR deliverable_qty <= 0 OR planned_start IS NULL OR planned_end IS NULL)
        """
    )


def downgrade() -> None:
    op.create_index(
        "uq_mission_executions_active_task",
        "mission_executions",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('dispatched','accepted','running','paused',"
            "'pause_requested','resume_requested','cancel_requested')"
        ),
    )
    op.drop_index("ix_mission_executions_allocation_id", table_name="mission_executions")
    op.drop_constraint("fk_mission_executions_allocation_id", "mission_executions", type_="foreignkey")
    op.drop_column("mission_executions", "rate_per_hour_snapshot")
    op.drop_column("mission_executions", "output_unit")
    op.drop_column("mission_executions", "planned_qty")
    op.drop_column("mission_executions", "allocation_id")

    op.drop_index("ix_task_resource_allocations_device_state", table_name="task_resource_allocations")
    op.drop_index("ix_task_resource_allocations_task_state", table_name="task_resource_allocations")
    op.drop_index("ix_task_resource_allocations_state", table_name="task_resource_allocations")
    op.drop_index("ix_task_resource_allocations_device_id", table_name="task_resource_allocations")
    op.drop_index("ix_task_resource_allocations_requirement_id", table_name="task_resource_allocations")
    op.drop_index("ix_task_resource_allocations_task_id", table_name="task_resource_allocations")
    op.drop_table("task_resource_allocations")

    op.drop_index("ix_task_resource_requirements_task_gate", table_name="task_resource_requirements")
    op.drop_index("ix_task_resource_requirements_capability_code", table_name="task_resource_requirements")
    op.drop_index("ix_task_resource_requirements_task_id", table_name="task_resource_requirements")
    op.drop_table("task_resource_requirements")

    op.drop_index("ix_task_resource_plans_state", table_name="task_resource_plans")
    op.drop_table("task_resource_plans")

    op.drop_index("ix_device_work_capacities_valid_until", table_name="device_work_capacities")
    op.drop_index("ix_device_work_capacities_capability_unit", table_name="device_work_capacities")
    op.drop_index("ix_device_work_capacities_capability_code", table_name="device_work_capacities")
    op.drop_index("ix_device_work_capacities_device_id", table_name="device_work_capacities")
    op.drop_table("device_work_capacities")
