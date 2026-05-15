"""add provider notes and review replies

Revision ID: 6c7d8e9f0a1b
Revises: 5b6c7d8e9f0a
Create Date: 2026-04-17 19:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "6c7d8e9f0a1b"  # pragma: allowlist secret
down_revision = "5b6c7d8e9f0a"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def _has_column(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    with op.batch_alter_table("bookings", schema=None) as batch_op:
        if not _has_column("bookings", "provider_notes"):
            batch_op.add_column(sa.Column("provider_notes", sa.Text(), nullable=True))

    with op.batch_alter_table("reviews", schema=None) as batch_op:
        if not _has_column("reviews", "provider_reply"):
            batch_op.add_column(sa.Column("provider_reply", sa.Text(), nullable=True))
        if not _has_column("reviews", "provider_replied_at"):
            batch_op.add_column(sa.Column("provider_replied_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("reviews", schema=None) as batch_op:
        if _has_column("reviews", "provider_replied_at"):
            batch_op.drop_column("provider_replied_at")
        if _has_column("reviews", "provider_reply"):
            batch_op.drop_column("provider_reply")

    with op.batch_alter_table("bookings", schema=None) as batch_op:
        if _has_column("bookings", "provider_notes"):
            batch_op.drop_column("provider_notes")
