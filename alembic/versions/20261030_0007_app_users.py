"""Signed-in people: app_user.

New table only; no existing table is altered. Accounts, passwords and roles
stay with the identity provider; this records who used AegisOps.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261030_0007"
down_revision = "20261030_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("issuer", sa.String(500), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("tenant_id", sa.String(100), nullable=True),
        sa.Column("roles", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("issuer", "subject", name="uq_app_user_identity"),
    )
    op.create_index("ix_app_user_username", "app_user", ["username"])
    op.create_index("ix_app_user_tenant_id", "app_user", ["tenant_id"])


def downgrade():
    op.drop_index("ix_app_user_tenant_id", table_name="app_user")
    op.drop_index("ix_app_user_username", table_name="app_user")
    op.drop_table("app_user")
