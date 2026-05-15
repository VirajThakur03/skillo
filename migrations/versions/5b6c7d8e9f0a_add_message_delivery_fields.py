"""add message delivery fields

Revision ID: 5b6c7d8e9f0a
Revises: 4a5b6c7d8e9f
Create Date: 2026-04-17 12:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "5b6c7d8e9f0a"  # pragma: allowlist secret
down_revision = "4a5b6c7d8e9f"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def _has_column(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    with op.batch_alter_table("messages", schema=None) as batch_op:
        if not _has_column("messages", "delivered_at"):
            batch_op.add_column(sa.Column("delivered_at", sa.DateTime(), nullable=True))
        if not _has_column("messages", "read_at"):
            batch_op.add_column(sa.Column("read_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("messages", schema=None) as batch_op:
        if _has_column("messages", "read_at"):
            batch_op.drop_column("read_at")
        if _has_column("messages", "delivered_at"):
            batch_op.drop_column("delivered_at")
