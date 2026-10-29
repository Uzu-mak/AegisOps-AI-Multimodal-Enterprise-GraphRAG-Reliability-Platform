"""Evaluation run history: eval_run and eval_case_result.

New tables only; no existing table is altered. Downgrade drops them (and the
history they hold).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261029_0005"
down_revision = "20261028_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "eval_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(100), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="console"),
        sa.Column("trigger", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("k", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("llm_model", sa.String(200), nullable=True),
        sa.Column("commit", sa.String(64), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("modes_run", postgresql.JSONB(), nullable=False),
        sa.Column("unavailable_modes", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("per_mode", postgresql.JSONB(), nullable=False),
        sa.Column("failure_taxonomy", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_eval_run_tenant_id", "eval_run", ["tenant_id"])
    op.create_index("ix_eval_run_created_at", "eval_run", ["created_at"])
    op.create_table(
        "eval_case_result",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("eval_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", sa.String(100), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("expected_memory_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("anchor_memory_id", sa.String(64), nullable=True),
        sa.Column("labeled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("retrieved_memory_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("recall_at_5", sa.Float(), nullable=False),
        sa.Column("recall_at_k", sa.Float(), nullable=False),
        sa.Column("mrr", sa.Float(), nullable=False),
        sa.Column("groundedness", sa.Float(), nullable=True),
        sa.Column("citation_accuracy", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_eval_case_result_run_id", "eval_case_result", ["run_id"])


def downgrade():
    op.drop_index("ix_eval_case_result_run_id", table_name="eval_case_result")
    op.drop_table("eval_case_result")
    op.drop_index("ix_eval_run_created_at", table_name="eval_run")
    op.drop_index("ix_eval_run_tenant_id", table_name="eval_run")
    op.drop_table("eval_run")
