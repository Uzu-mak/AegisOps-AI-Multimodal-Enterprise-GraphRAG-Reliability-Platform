"""Add projection_outbox table for reliable derived-store synchronization.

Revision ID: 20260819_0002
Revises: 20260818_0001_initial_memory_table
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260819_0002"
down_revision = "20260818_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projection_outbox",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "memory_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("memories.id"),
            nullable=False,
        ),
        sa.Column("projection_type", sa.String(20), nullable=False),
        sa.Column("operation", sa.String(30), nullable=False, server_default="project"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )
    # Create indexes only if they don't exist yet
    connection = op.get_bind()
    insp = sa.inspect(connection)
    existing_indexes = [
        idx["name"]
        for idx in insp.get_indexes("projection_outbox")
    ]
    if "ix_projection_outbox_status" not in existing_indexes:
        op.create_index("ix_projection_outbox_status", "projection_outbox", ["status"])
    if "ix_projection_outbox_memory_id" not in existing_indexes:
        op.create_index("ix_projection_outbox_memory_id", "projection_outbox", ["memory_id"])


def downgrade() -> None:
    op.drop_table("projection_outbox")
