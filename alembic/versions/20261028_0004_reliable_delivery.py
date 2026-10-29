"""Append-only events, canonical revisions, leased scheduled delivery.

Existing history cannot be reconstructed; preserve every surviving legacy row.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "20261028_0004"
down_revision = "20260901_0003"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("memories", sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE memories SET revision = COALESCE((SELECT MAX(memory_version) FROM projection_outbox WHERE memory_id = memories.id), 0)")
    op.add_column("projection_outbox", sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"))
    for name in ("next_attempt_at", "lease_until", "kafka_next_attempt_at", "kafka_lease_until"):
        op.add_column("projection_outbox", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    for name in ("lease_token", "kafka_lease_token"):
        op.add_column("projection_outbox", sa.Column(name, postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_projection_delivery_due", "projection_outbox", ["status", "next_attempt_at", "occurred_at"])
    op.create_index("ix_kafka_delivery_due", "projection_outbox", ["kafka_published_at", "kafka_next_attempt_at"])
    # Existing duplicate identities must be reviewed, never silently deleted.
    op.execute("""CREATE UNIQUE INDEX uq_active_work_order_identity ON memories
        (COALESCE(tenant_id, ''), COALESCE(facility_id, ''),
         COALESCE(metadata->'import'->>'source_system', 'default'), source_id)
        WHERE source_type = 'work_order' AND status = 'active'""")

def downgrade():
    op.drop_index("uq_active_work_order_identity", table_name="memories")
    op.drop_index("ix_kafka_delivery_due", table_name="projection_outbox")
    op.drop_index("ix_projection_delivery_due", table_name="projection_outbox")
    for name in ("kafka_lease_token", "lease_token", "kafka_lease_until", "kafka_next_attempt_at", "lease_until", "next_attempt_at", "payload"):
        op.drop_column("projection_outbox", name)
    op.drop_column("memories", "revision")
