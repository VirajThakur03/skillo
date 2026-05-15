"""add audit log

Revision ID: b1c2d3e4f5a6
Revises: af10b20c30d4
Create Date: 2026-04-18 00:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5a6"  # pragma: allowlist secret
down_revision = "af10b20c30d4"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "audit_log" not in inspector.get_table_names():
        op.create_table(
            "audit_log",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("actor_role", sa.String(length=20), nullable=True),
            sa.Column("target_type", sa.String(length=50), nullable=True),
            sa.Column("target_id", sa.Integer(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("ip_address", sa.String(length=45), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    existing_indexes = {index["name"] for index in inspector.get_indexes("audit_log")}
    if "idx_audit_event" not in existing_indexes:
        op.create_index("idx_audit_event", "audit_log", ["event_type", "created_at"], unique=False)
    if "idx_audit_target" not in existing_indexes:
        op.create_index("idx_audit_target", "audit_log", ["target_type", "target_id"], unique=False)
    if "idx_audit_actor" not in existing_indexes:
        op.create_index("idx_audit_actor", "audit_log", ["actor_id", "created_at"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "audit_log" in inspector.get_table_names():
        existing_indexes = {index["name"] for index in inspector.get_indexes("audit_log")}
        for index_name in ("idx_audit_actor", "idx_audit_target", "idx_audit_event"):
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="audit_log")
        op.drop_table("audit_log")
