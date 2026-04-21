"""add trace id to agents

Revision ID: 9a28b8b3f1a2
Revises: d2b70d60cda9
Create Date: 2026-04-10 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9a28b8b3f1a2"
down_revision: Union[str, Sequence[str], None] = "d2b70d60cda9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("trace_id", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_agents_trace_id"), "agents", ["trace_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agents_trace_id"), table_name="agents")
    op.drop_column("agents", "trace_id")
