"""ensure chat message schema

Revision ID: e4f1a9c2d7b3
Revises: b0cdf505e447
Create Date: 2026-04-27 22:00:00

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision = "e4f1a9c2d7b3"
down_revision = "b0cdf505e447"
branch_labels = None
depends_on = None


MESSAGE_TYPE_ENUM = sa.Enum("text", "image", "file", name="messagetype", create_type=False)


def _column_exists(table_name, column_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    try:
        columns = inspector.get_columns(table_name)
    except Exception:
        return False
    return any(column["name"] == column_name for column in columns)


def _index_exists(table_name, index_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    try:
        indexes = inspector.get_indexes(table_name)
    except Exception:
        return False
    return any(index["name"] == index_name for index in indexes)


def _ensure_postgres_enum():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_type
                    WHERE typname = 'messagetype'
                ) THEN
                    CREATE TYPE messagetype AS ENUM ('text', 'image', 'file');
                END IF;
            END
            $$;
            """
        )
    )


def upgrade():
    _ensure_postgres_enum()

    with op.batch_alter_table("messages", schema=None) as batch_op:
        if not _column_exists("messages", "message_type"):
            batch_op.add_column(
                sa.Column(
                    "message_type",
                    MESSAGE_TYPE_ENUM,
                    nullable=False,
                    server_default="text",
                )
            )
        if not _column_exists("messages", "delivered_at"):
            batch_op.add_column(sa.Column("delivered_at", sa.DateTime(), nullable=True))
        if not _column_exists("messages", "read_at"):
            batch_op.add_column(sa.Column("read_at", sa.DateTime(), nullable=True))
        if not _column_exists("messages", "is_deleted"):
            batch_op.add_column(
                sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false"))
            )
        if not _column_exists("messages", "deleted_at"):
            batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))

    if not _index_exists("messages", "ix_messages_room_created"):
        op.create_index("ix_messages_room_created", "messages", ["room", "created_at"], unique=False)


def downgrade():
    bind = op.get_bind()

    with op.batch_alter_table("messages", schema=None) as batch_op:
        if _index_exists("messages", "ix_messages_room_created"):
            batch_op.drop_index("ix_messages_room_created")
        if _column_exists("messages", "deleted_at"):
            batch_op.drop_column("deleted_at")
        if _column_exists("messages", "is_deleted"):
            batch_op.drop_column("is_deleted")
        if _column_exists("messages", "read_at"):
            batch_op.drop_column("read_at")
        if _column_exists("messages", "delivered_at"):
            batch_op.drop_column("delivered_at")
        if _column_exists("messages", "message_type"):
            batch_op.drop_column("message_type")

    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS messagetype")
