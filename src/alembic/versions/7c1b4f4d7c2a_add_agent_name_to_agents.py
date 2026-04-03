"""add agent_name to agents

Revision ID: 7c1b4f4d7c2a
Revises: 32cc87c13998
Create Date: 2026-04-03 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7c1b4f4d7c2a"
down_revision: Union[str, Sequence[str], None] = "32cc87c13998"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("agents", sa.Column("agent_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agents", "agent_name")
