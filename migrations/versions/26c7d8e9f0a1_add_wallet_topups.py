"""add wallet topups

Revision ID: 26c7d8e9f0a1
Revises: 25b8a5ad1038
Create Date: 2026-05-13 14:20:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "26c7d8e9f0a1"
down_revision = "25b8a5ad1038"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if bind.dialect.name == "postgresql":
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_type WHERE typname = 'wallettransactiontype'
                ) THEN
                    CREATE TYPE wallettransactiontype AS ENUM (
                        'CREDIT_REFERRAL',
                        'CREDIT_REFUND',
                        'CREDIT_PROMO',
                        'CREDIT_EARNING',
                        'CREDIT_TOPUP',
                        'DEBIT_BOOKING',
                        'DEBIT_WITHDRAWAL',
                        'DEBIT_COMMISSION',
                        'DEBIT_SUBSCRIPTION'
                    );
                END IF;
            END
            $$;
            """
        )

    if "wallet_transactions" not in inspector.get_table_names():
        wallet_txn_values = (
            "CREDIT_REFERRAL",
            "CREDIT_REFUND",
            "CREDIT_PROMO",
            "CREDIT_EARNING",
            "CREDIT_TOPUP",
            "DEBIT_BOOKING",
            "DEBIT_WITHDRAWAL",
            "DEBIT_COMMISSION",
            "DEBIT_SUBSCRIPTION",
        )
        wallet_txn_type = (
            postgresql.ENUM(*wallet_txn_values, name="wallettransactiontype", create_type=False)
            if bind.dialect.name == "postgresql"
            else sa.Enum(
                *wallet_txn_values,
                name="wallettransactiontype",
            )
        )
        op.create_table(
            "wallet_transactions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("txn_type", wallet_txn_type, nullable=False),
            sa.Column("amount", sa.Numeric(10, 2), nullable=False),
            sa.Column("balance_after", sa.Numeric(10, 2), nullable=False),
            sa.Column("reference_type", sa.String(length=32), nullable=True),
            sa.Column("reference_id", sa.Integer(), nullable=True),
            sa.Column("description", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("wallet_transactions", schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f("ix_wallet_transactions_user_id"),
                ["user_id"],
                unique=False,
            )
            batch_op.create_index(
                batch_op.f("ix_wallet_transactions_created_at"),
                ["created_at"],
                unique=False,
            )

    if "wallet_topups" in inspector.get_table_names():
        return

    op.create_table(
        "wallet_topups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="razorpay"),
        sa.Column("topup_reference", sa.String(length=128), nullable=False),
        sa.Column("gateway_order_id", sa.String(length=128), nullable=True),
        sa.Column("gateway_payment_id", sa.String(length=128), nullable=True),
        sa.Column("wallet_transaction_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("failure_reason", sa.String(length=255), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["wallet_transaction_id"], ["wallet_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("wallet_topups", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_wallet_topups_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_wallet_topups_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_wallet_topups_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_wallet_topups_wallet_transaction_id"), ["wallet_transaction_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_wallet_topups_topup_reference"), ["topup_reference"], unique=True)
        batch_op.create_index(batch_op.f("ix_wallet_topups_gateway_order_id"), ["gateway_order_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_wallet_topups_gateway_payment_id"), ["gateway_payment_id"], unique=True)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "wallet_topups" not in inspector.get_table_names():
        return

    with op.batch_alter_table("wallet_topups", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_wallet_topups_gateway_payment_id"))
        batch_op.drop_index(batch_op.f("ix_wallet_topups_gateway_order_id"))
        batch_op.drop_index(batch_op.f("ix_wallet_topups_topup_reference"))
        batch_op.drop_index(batch_op.f("ix_wallet_topups_wallet_transaction_id"))
        batch_op.drop_index(batch_op.f("ix_wallet_topups_created_at"))
        batch_op.drop_index(batch_op.f("ix_wallet_topups_status"))
        batch_op.drop_index(batch_op.f("ix_wallet_topups_user_id"))

    op.drop_table("wallet_topups")
