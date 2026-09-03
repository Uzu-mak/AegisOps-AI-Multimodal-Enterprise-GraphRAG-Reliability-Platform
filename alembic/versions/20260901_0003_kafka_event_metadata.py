"""Add Kafka publication metadata to projection_outbox.

Revision ID: 20260901_0003
Revises: 20260819_0002
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260901_0003"
down_revision = "20260819_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projection_outbox", sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("projection_outbox", sa.Column("event_type", sa.String(length=40), nullable=True))
    op.add_column("projection_outbox", sa.Column("memory_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("projection_outbox", sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column(
        "projection_outbox",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column(
        "projection_outbox",
        sa.Column("kafka_publish_status", sa.String(length=20), nullable=False, server_default="pending"),
    )
    op.add_column("projection_outbox", sa.Column("kafka_retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("projection_outbox", sa.Column("kafka_error_message", sa.Text(), nullable=True))
    op.add_column("projection_outbox", sa.Column("kafka_published_at", sa.DateTime(timezone=True), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, memory_id, operation, created_at FROM projection_outbox ORDER BY memory_id, created_at, id"
        )
    ).mappings().all()

    memory_versions: dict[object, int] = {}
    seen_operation_keys: dict[tuple[object, str, datetime], tuple[object, int]] = {}
    for row in rows:
        op_key = (row["memory_id"], row["operation"], row["created_at"])
        if op_key not in seen_operation_keys:
            next_version = memory_versions.get(row["memory_id"], 0) + 1
            memory_versions[row["memory_id"]] = next_version
            seen_operation_keys[op_key] = (uuid4(), next_version)

        event_id, memory_version = seen_operation_keys[op_key]
        event_type = "MEMORY_UPDATED" if row["operation"] == "status_update" else "MEMORY_CREATED"
        connection.execute(
            sa.text(
                """
                UPDATE projection_outbox
                SET event_id = :event_id,
                    event_type = :event_type,
                    memory_version = :memory_version,
                    schema_version = 1,
                    occurred_at = COALESCE(created_at, :occurred_at),
                    kafka_publish_status = 'pending',
                    kafka_retry_count = 0
                WHERE id = :row_id
                """
            ),
            {
                "event_id": event_id,
                "event_type": event_type,
                "memory_version": memory_version,
                "occurred_at": datetime.now(timezone.utc),
                "row_id": row["id"],
            },
        )

    op.alter_column("projection_outbox", "event_id", nullable=False)
    op.alter_column("projection_outbox", "event_type", nullable=False)

    insp = sa.inspect(connection)
    existing_indexes = [idx["name"] for idx in insp.get_indexes("projection_outbox")]
    if "ix_projection_outbox_event_id" not in existing_indexes:
        op.create_index("ix_projection_outbox_event_id", "projection_outbox", ["event_id"])
    if "ix_projection_outbox_kafka_publish_status" not in existing_indexes:
        op.create_index(
            "ix_projection_outbox_kafka_publish_status",
            "projection_outbox",
            ["kafka_publish_status"],
        )


def downgrade() -> None:
    op.drop_index("ix_projection_outbox_kafka_publish_status", table_name="projection_outbox")
    op.drop_index("ix_projection_outbox_event_id", table_name="projection_outbox")
    op.drop_column("projection_outbox", "kafka_published_at")
    op.drop_column("projection_outbox", "kafka_error_message")
    op.drop_column("projection_outbox", "kafka_retry_count")
    op.drop_column("projection_outbox", "kafka_publish_status")
    op.drop_column("projection_outbox", "occurred_at")
    op.drop_column("projection_outbox", "schema_version")
    op.drop_column("projection_outbox", "memory_version")
    op.drop_column("projection_outbox", "event_type")
    op.drop_column("projection_outbox", "event_id")