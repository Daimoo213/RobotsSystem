"""align baseline indexes with ORM metadata

Revision ID: 20260720_04
Revises: 20260720_03
Create Date: 2026-07-20
"""

from alembic import op

revision = "20260720_04"
down_revision = "20260720_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_devices_code", table_name="devices")
    op.drop_index("ix_projects_code", table_name="projects")
    op.create_index("ix_devices_section_id", "devices", ["section_id"])
    op.create_index("ix_devices_gateway_enabled", "devices", ["gateway_enabled"])
    op.create_index("ix_device_commands_mission_execution_id", "device_commands", ["mission_execution_id"])
    op.create_index("ix_mission_executions_state", "mission_executions", ["state"])
    op.create_index("ix_safety_states_active", "safety_states", ["active"])
    op.create_index("ix_safety_states_cycle_id", "safety_states", ["cycle_id"])
    op.create_index("ix_scripts_is_active", "scripts", ["is_active"])
    op.create_index("ix_scripts_stage", "scripts", ["stage"])


def downgrade() -> None:
    for name, table in (("ix_scripts_stage", "scripts"), ("ix_scripts_is_active", "scripts"), ("ix_safety_states_cycle_id", "safety_states"), ("ix_safety_states_active", "safety_states"), ("ix_mission_executions_state", "mission_executions"), ("ix_device_commands_mission_execution_id", "device_commands"), ("ix_devices_gateway_enabled", "devices"), ("ix_devices_section_id", "devices")):
        op.drop_index(name, table_name=table)
    op.create_index("ix_projects_code", "projects", ["code"])
    op.create_index("ix_devices_code", "devices", ["code"])
