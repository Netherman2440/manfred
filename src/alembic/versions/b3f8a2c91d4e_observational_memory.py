"""observational memory

Revision ID: b3f8a2c91d4e
Revises: a1b2c3d4e5f6
Create Date: 2026-05-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3f8a2c91d4e"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("last_observed_item_id", sa.String(length=64), nullable=True),
    )
    op.add_column("sessions", sa.Column("current_task", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "current_task")
    op.drop_column("sessions", "last_observed_item_id")
