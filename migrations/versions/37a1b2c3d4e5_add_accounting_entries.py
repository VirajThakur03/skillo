"""add accounting entries

Revision ID: 37a1b2c3d4e5
Revises: 26c7d8e9f0a1
Create Date: 2026-05-13 20:15:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "37a1b2c3d4e5"
down_revision = "26c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "accounting_entries" in inspector.get_table_names():
        return

    op.create_table(
        "accounting_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entry_group", sa.String(length=128), nullable=False),
        sa.Column("account_code", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="INR"),
        sa.Column("reference_type", sa.String(length=32), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("accounting_entries", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_accounting_entries_entry_group"), ["entry_group"], unique=False)
        batch_op.create_index(batch_op.f("ix_accounting_entries_account_code"), ["account_code"], unique=False)
        batch_op.create_index(batch_op.f("ix_accounting_entries_direction"), ["direction"], unique=False)
        batch_op.create_index(batch_op.f("ix_accounting_entries_reference_type"), ["reference_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_accounting_entries_reference_id"), ["reference_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_accounting_entries_created_at"), ["created_at"], unique=False)
        batch_op.create_index("ix_accounting_entries_group_account", ["entry_group", "account_code"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "accounting_entries" not in inspector.get_table_names():
        return

    with op.batch_alter_table("accounting_entries", schema=None) as batch_op:
        batch_op.drop_index("ix_accounting_entries_group_account")
        batch_op.drop_index(batch_op.f("ix_accounting_entries_created_at"))
        batch_op.drop_index(batch_op.f("ix_accounting_entries_reference_id"))
        batch_op.drop_index(batch_op.f("ix_accounting_entries_reference_type"))
        batch_op.drop_index(batch_op.f("ix_accounting_entries_direction"))
        batch_op.drop_index(batch_op.f("ix_accounting_entries_account_code"))
        batch_op.drop_index(batch_op.f("ix_accounting_entries_entry_group"))

    op.drop_table("accounting_entries")
