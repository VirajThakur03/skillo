"""add booking invoice metadata

Revision ID: 4a5b6c7d8e9f
Revises: 3f4a5b6c7d8e
Create Date: 2026-04-16 17:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "4a5b6c7d8e9f"  # pragma: allowlist secret
down_revision = "3f4a5b6c7d8e"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def _has_column(inspector, table_name, column_name):
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    with op.batch_alter_table("bookings", schema=None) as batch_op:
        if not _has_column(inspector, "bookings", "invoice_number"):
            batch_op.add_column(sa.Column("invoice_number", sa.String(length=50), nullable=True))
        if not _has_column(inspector, "bookings", "invoice_generated_at"):
            batch_op.add_column(sa.Column("invoice_generated_at", sa.DateTime(), nullable=True))
        if not _has_column(inspector, "bookings", "gst_amount"):
            batch_op.add_column(
                sa.Column("gst_amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00")
            )
        if not _has_column(inspector, "bookings", "service_amount"):
            batch_op.add_column(
                sa.Column("service_amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00")
            )


def downgrade():
    with op.batch_alter_table("bookings", schema=None) as batch_op:
        batch_op.drop_column("service_amount")
        batch_op.drop_column("gst_amount")
        batch_op.drop_column("invoice_generated_at")
        batch_op.drop_column("invoice_number")
