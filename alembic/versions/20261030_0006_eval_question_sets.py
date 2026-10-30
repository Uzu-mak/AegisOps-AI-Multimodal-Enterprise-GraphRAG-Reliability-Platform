"""Versioned evaluation question sets: eval_question_set and eval_question.

New tables only; no existing table is altered. Downgrade drops them (and the
question sets they hold).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261030_0006"
down_revision = "20261029_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "eval_question_set",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("eval_question_set.id"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(200), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("history", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.UniqueConstraint("tenant_id", "name", "version", name="uq_eval_question_set_version"),
    )
    op.create_index("ix_eval_question_set_tenant_id", "eval_question_set", ["tenant_id"])
    op.create_index("ix_eval_question_set_name", "eval_question_set", ["name"])
    op.create_index("ix_eval_question_set_content_hash", "eval_question_set", ["content_hash"])
    op.create_table(
        "eval_question",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("set_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("eval_question_set.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_memory_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("anchor_memory_id", sa.String(64), nullable=True),
        sa.Column("expects_no_answer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("leaked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("labeling_method", sa.String(40), nullable=False, server_default="console"),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_eval_question_set_id", "eval_question", ["set_id"])


def downgrade():
    op.drop_index("ix_eval_question_set_id", table_name="eval_question")
    op.drop_table("eval_question")
    op.drop_index("ix_eval_question_set_content_hash", table_name="eval_question_set")
    op.drop_index("ix_eval_question_set_name", table_name="eval_question_set")
    op.drop_index("ix_eval_question_set_tenant_id", table_name="eval_question_set")
    op.drop_table("eval_question_set")
