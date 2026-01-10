"""add lat lon and messages

Revision ID: 1a0db1b0ed7f
Revises: 1c7d4119b019
Create Date: 2025-12-05 17:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "1a0db1b0ed7f"
down_revision = "1c7d4119b019"
branch_labels = None
depends_on = None


def upgrade():
    # Messages table
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("room", sa.String(length=255), nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_messages_room"), ["room"], unique=False)

    # Add lat/lon to skills
    with op.batch_alter_table("skills", schema=None) as batch_op:
        batch_op.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("longitude", sa.Float(), nullable=True))

    # Add lat/lon to users
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("longitude", sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("longitude")
        batch_op.drop_column("latitude")

    with op.batch_alter_table("skills", schema=None) as batch_op:
        batch_op.drop_column("longitude")
        batch_op.drop_column("latitude")

    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_messages_room"))

    op.drop_table("messages")
