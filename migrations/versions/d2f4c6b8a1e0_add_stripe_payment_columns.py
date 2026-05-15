"""add stripe payment columns

Revision ID: d2f4c6b8a1e0
Revises: b1c2d3e4f5a6
Create Date: 2026-04-19 14:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d2f4c6b8a1e0"  # pragma: allowlist secret
down_revision = "b1c2d3e4f5a6"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("payment_provider", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("payment_checkout_session_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("promo_discount_amount", sa.Numeric(10, 2), nullable=True, server_default="0.00"))
        batch_op.add_column(sa.Column("amount_payable", sa.Numeric(10, 2), nullable=True, server_default="0.00"))


def downgrade():
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_column("amount_payable")
        batch_op.drop_column("promo_discount_amount")
        batch_op.drop_column("payment_checkout_session_id")
        batch_op.drop_column("payment_provider")
