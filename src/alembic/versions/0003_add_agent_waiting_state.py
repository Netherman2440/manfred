"""Add waiting state fields to agents.

Revision ID: 0003_add_agent_waiting_state
Revises: 0002_add_attachments
Create Date: 2026-03-24 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_add_agent_waiting_state"
down_revision = "0002_add_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("agents")}

    if "source_call_id" not in existing_columns:
        op.add_column("agents", sa.Column("source_call_id", sa.String(length=64), nullable=True))
    if "waiting_for" not in existing_columns:
        op.add_column("agents", sa.Column("waiting_for", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    if "result" not in existing_columns:
        op.add_column("agents", sa.Column("result", sa.JSON(), nullable=True))
    if "error" not in existing_columns:
        op.add_column("agents", sa.Column("error", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("agents")}

    if "error" in existing_columns:
        op.drop_column("agents", "error")
    if "result" in existing_columns:
        op.drop_column("agents", "result")
    if "waiting_for" in existing_columns:
        op.drop_column("agents", "waiting_for")
    if "source_call_id" in existing_columns:
        op.drop_column("agents", "source_call_id")
