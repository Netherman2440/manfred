"""Add attachments table.

Revision ID: 0002_add_attachments
Revises: 0001_initial_chat_setup
Create Date: 2026-03-23 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_add_attachments"
down_revision = "0001_initial_chat_setup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=True),
        sa.Column("item_id", sa.String(length=64), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("workspace_path", sa.String(length=1024), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("transcription_status", sa.String(length=32), nullable=False),
        sa.Column("transcription_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], name=op.f("fk_attachments_agent_id_agents")),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], name=op.f("fk_attachments_item_id_items")),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], name=op.f("fk_attachments_session_id_sessions")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
    )
    op.create_index(op.f("ix_attachments_agent_id"), "attachments", ["agent_id"], unique=False)
    op.create_index(op.f("ix_attachments_item_id"), "attachments", ["item_id"], unique=False)
    op.create_index(op.f("ix_attachments_session_id"), "attachments", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_attachments_session_id"), table_name="attachments")
    op.drop_index(op.f("ix_attachments_item_id"), table_name="attachments")
    op.drop_index(op.f("ix_attachments_agent_id"), table_name="attachments")
    op.drop_table("attachments")
