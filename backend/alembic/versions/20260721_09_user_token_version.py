"""Add user token version for password-reset session revocation."""

from alembic import op
import sqlalchemy as sa


revision = "20260721_09"
down_revision = "20260720_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "auth_version")
