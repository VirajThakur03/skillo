"""add verification fields to users

Revision ID: e308fb3b1730
Revises: 1a0db1b0ed7f
Create Date: 2025-12-06 12:00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e308fb3b1730"
down_revision = "1a0db1b0ed7f"
branch_labels = None
depends_on = None


# Define PostgreSQL ENUM
verification_status_enum = postgresql.ENUM(
    "pending",
    "verified",
    "rejected",
    name="verificationstatus",
)


def upgrade():
    bind = op.get_bind()

    # Create enum type if it doesn't exist
    verification_status_enum.create(bind, checkfirst=True)

    # Add columns
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "verification_status",
                verification_status_enum,
                nullable=False,
                server_default="pending",
            )
        )
        batch_op.add_column(
            sa.Column(
                "is_verified",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch_op.add_column(sa.Column("document_filename", sa.String(512), nullable=True))
        batch_op.add_column(sa.Column("document_type", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("verification_notes", sa.Text(), nullable=True))

    # Remove defaults after applying
    op.alter_column("users", "verification_status", server_default=None)
    op.alter_column("users", "is_verified", server_default=None)


def downgrade():
    bind = op.get_bind()

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("verification_notes")
        batch_op.drop_column("document_type")
        batch_op.drop_column("document_filename")
        batch_op.drop_column("is_verified")
        batch_op.drop_column("verification_status")

    verification_status_enum.drop(bind, checkfirst=True)
