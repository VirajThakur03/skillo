"""add missing booking runtime columns

Revision ID: af10b20c30d4
Revises: 9e0f1a2b3c4d
Create Date: 2026-04-17 19:52:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "af10b20c30d4"  # pragma: allowlist secret
down_revision = "9e0f1a2b3c4d"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "bookings" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("bookings")}
    falsey_default = sa.text("0.00")

    with op.batch_alter_table("bookings", schema=None) as batch_op:
        if "original_scheduled_at" not in existing_columns:
            batch_op.add_column(sa.Column("original_scheduled_at", sa.DateTime(), nullable=True))
        if "quote_request_id" not in existing_columns:
            batch_op.add_column(sa.Column("quote_request_id", sa.Integer(), nullable=True))
        if "refund_status" not in existing_columns:
            batch_op.add_column(
                sa.Column("refund_status", sa.Enum("NONE", "PENDING", "PROCESSED", "FAILED", name="refundstatus", create_type=False), nullable=False, server_default=sa.text("'NONE'"))
            )
        if "worker_last_seen_at" not in existing_columns:
            batch_op.add_column(sa.Column("worker_last_seen_at", sa.DateTime(), nullable=True))
        if "platform_fee_pct" not in existing_columns:
            batch_op.add_column(sa.Column("platform_fee_pct", sa.Numeric(5, 2), nullable=True, server_default=sa.text("5.00")))
        if "platform_fee_amount" not in existing_columns:
            batch_op.add_column(sa.Column("platform_fee_amount", sa.Numeric(10, 2), nullable=True, server_default=falsey_default))
        if "worker_earnings" not in existing_columns:
            batch_op.add_column(sa.Column("worker_earnings", sa.Numeric(10, 2), nullable=True, server_default=falsey_default))
        if "referral_credit_used" not in existing_columns:
            batch_op.add_column(sa.Column("referral_credit_used", sa.Numeric(10, 2), nullable=True, server_default=falsey_default))
        if "distance_km" not in existing_columns:
            batch_op.add_column(sa.Column("distance_km", sa.Float(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "bookings" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("bookings")}

    with op.batch_alter_table("bookings", schema=None) as batch_op:
        if "distance_km" in existing_columns:
            batch_op.drop_column("distance_km")
        if "referral_credit_used" in existing_columns:
            batch_op.drop_column("referral_credit_used")
        if "worker_earnings" in existing_columns:
            batch_op.drop_column("worker_earnings")
        if "platform_fee_amount" in existing_columns:
            batch_op.drop_column("platform_fee_amount")
        if "platform_fee_pct" in existing_columns:
            batch_op.drop_column("platform_fee_pct")
        if "worker_last_seen_at" in existing_columns:
            batch_op.drop_column("worker_last_seen_at")
        if "refund_status" in existing_columns:
            batch_op.drop_column("refund_status")
        if "quote_request_id" in existing_columns:
            batch_op.drop_column("quote_request_id")
        if "original_scheduled_at" in existing_columns:
            batch_op.drop_column("original_scheduled_at")
