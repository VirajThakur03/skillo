"""add provider cancellation policy fields

Revision ID: 3f4a5b6c7d8e
Revises: ec34e6b07788
Create Date: 2026-04-16 17:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "3f4a5b6c7d8e"  # pragma: allowlist secret
down_revision = "ec34e6b07788"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def _has_column(inspector, table_name, column_name):
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    with op.batch_alter_table("users", schema=None) as batch_op:
        if not _has_column(inspector, "users", "cancellation_cutoff_hours"):
            batch_op.add_column(
                sa.Column(
                    "cancellation_cutoff_hours",
                    sa.Integer(),
                    nullable=False,
                    server_default="2",
                )
            )
        if not _has_column(inspector, "users", "cancellation_fee_pct"):
            batch_op.add_column(
                sa.Column(
                    "cancellation_fee_pct",
                    sa.Integer(),
                    nullable=False,
                    server_default="20",
                )
            )
        if not _has_column(inspector, "users", "cancellation_policy_text"):
            batch_op.add_column(
                sa.Column("cancellation_policy_text", sa.Text(), nullable=True)
            )


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("cancellation_policy_text")
        batch_op.drop_column("cancellation_fee_pct")
        batch_op.drop_column("cancellation_cutoff_hours")
