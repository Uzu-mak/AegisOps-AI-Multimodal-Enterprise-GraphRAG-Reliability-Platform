"""initial memory table

Revision ID: 20260818_0001
Revises: 
Create Date: 2026-08-18 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260818_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.String(), nullable=True),
        sa.Column("component_id", sa.String(), nullable=True),
        sa.Column("incident_id", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("confidence", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("importance", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("facility_id", sa.String(), nullable=True),
        sa.Column("team_id", sa.String(), nullable=True),
        sa.Column("access_roles", sa.ARRAY(sa.String()), nullable=False, server_default=sa.text("ARRAY[]::varchar[]")),
        sa.Column("supersedes_memory_id", sa.Uuid(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("memory_type IN ('observation', 'incident', 'diagnosis', 'maintenance_action', 'resolution', 'recommendation', 'document_fact', 'agent_interaction', 'feedback')", name="ck_memories_memory_type"),
        sa.CheckConstraint("status IN ('active', 'superseded', 'disputed', 'archived')", name="ck_memories_status"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memories_confidence_range"),
        sa.CheckConstraint("importance >= 0 AND importance <= 1", name="ck_memories_importance_range"),
        sa.ForeignKeyConstraint(["supersedes_memory_id"], ["memories.id"], name="fk_memories_supersedes_memory_id"),
    )

    op.create_index("idx_memories_memory_type", "memories", ["memory_type"], unique=False)
    op.create_index("idx_memories_status", "memories", ["status"], unique=False)
    op.create_index("idx_memories_asset_id", "memories", ["asset_id"], unique=False)
    op.create_index("idx_memories_facility_id", "memories", ["facility_id"], unique=False)
    op.create_index("idx_memories_source_type", "memories", ["source_type"], unique=False)
    op.create_index("idx_memories_incident_id", "memories", ["incident_id"], unique=False)
    op.create_index("idx_memories_created_at", "memories", [sa.text("created_at DESC")], unique=False)
    op.create_index("idx_memories_updated_at", "memories", [sa.text("updated_at DESC")], unique=False)
    op.create_index("idx_memories_supersedes_memory_id", "memories", ["supersedes_memory_id"], unique=False)
    op.create_index("idx_memories_access_roles", "memories", ["access_roles"], unique=False, postgresql_using="GIN")
    op.create_index("idx_memories_metadata", "memories", [sa.text("metadata jsonb_path_ops")], unique=False, postgresql_using="GIN")


def downgrade() -> None:
    op.drop_index("idx_memories_metadata", table_name="memories", postgresql_using="GIN")
    op.drop_index("idx_memories_access_roles", table_name="memories", postgresql_using="GIN")
    op.drop_index("idx_memories_supersedes_memory_id", table_name="memories")
    op.drop_index("idx_memories_updated_at", table_name="memories")
    op.drop_index("idx_memories_created_at", table_name="memories")
    op.drop_index("idx_memories_incident_id", table_name="memories")
    op.drop_index("idx_memories_source_type", table_name="memories")
    op.drop_index("idx_memories_facility_id", table_name="memories")
    op.drop_index("idx_memories_asset_id", table_name="memories")
    op.drop_index("idx_memories_status", table_name="memories")
    op.drop_index("idx_memories_memory_type", table_name="memories")
    op.drop_table("memories")
