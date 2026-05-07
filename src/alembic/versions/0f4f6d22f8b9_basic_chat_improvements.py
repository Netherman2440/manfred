"""basic chat improvements

Revision ID: 0f4f6d22f8b9
Revises: 9a28b8b3f1a2
Create Date: 2026-04-30 10:00:00.000000

"""
from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0f4f6d22f8b9"
down_revision: Union[str, Sequence[str], None] = "9a28b8b3f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("items", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "item_attachments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], name=op.f("fk_item_attachments_item_id_items"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_item_attachments")),
    )
    op.create_index(op.f("ix_item_attachments_item_id"), "item_attachments", ["item_id"], unique=False)

    op.create_table(
        "queued_inputs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], name=op.f("fk_queued_inputs_agent_id_agents"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], name=op.f("fk_queued_inputs_session_id_sessions"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_queued_inputs")),
    )
    op.create_index(op.f("ix_queued_inputs_agent_id"), "queued_inputs", ["agent_id"], unique=False)
    op.create_index(op.f("ix_queued_inputs_accepted_at"), "queued_inputs", ["accepted_at"], unique=False)
    op.create_index(op.f("ix_queued_inputs_consumed_at"), "queued_inputs", ["consumed_at"], unique=False)
    op.create_index(op.f("ix_queued_inputs_session_id"), "queued_inputs", ["session_id"], unique=False)

def downgrade() -> None:
    op.drop_index(op.f("ix_queued_inputs_session_id"), table_name="queued_inputs")
    op.drop_index(op.f("ix_queued_inputs_consumed_at"), table_name="queued_inputs")
    op.drop_index(op.f("ix_queued_inputs_accepted_at"), table_name="queued_inputs")
    op.drop_index(op.f("ix_queued_inputs_agent_id"), table_name="queued_inputs")
    op.drop_table("queued_inputs")

    op.drop_index(op.f("ix_item_attachments_item_id"), table_name="item_attachments")
    op.drop_table("item_attachments")

    op.drop_column("items", "edited_at")
