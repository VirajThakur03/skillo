"""add missing user runtime columns

Revision ID: 8d9e0f1a2b3c
Revises: 6c7d8e9f0a1b
Create Date: 2026-04-17 19:34:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "8d9e0f1a2b3c"  # pragma: allowlist secret
down_revision = "6c7d8e9f0a1b"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if "users" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    json_empty = sa.text("'[]'::json") if dialect == "postgresql" else sa.text("'[]'")
    timezone_default = sa.text("'UTC'::character varying") if dialect == "postgresql" else sa.text("'UTC'")
    false_default = sa.text("false")

    with op.batch_alter_table("users", schema=None) as batch_op:
        if "is_admin" not in existing_columns:
            batch_op.add_column(
                sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=false_default)
            )
        if "timezone" not in existing_columns:
            batch_op.add_column(
                sa.Column("timezone", sa.String(length=64), nullable=False, server_default=timezone_default)
            )
        if "service_areas" not in existing_columns:
            batch_op.add_column(
                sa.Column("service_areas", postgresql.JSON(astext_type=sa.Text()) if dialect == "postgresql" else sa.JSON(), nullable=False, server_default=json_empty)
            )
        if "portfolio_images" not in existing_columns:
            batch_op.add_column(
                sa.Column("portfolio_images", postgresql.JSON(astext_type=sa.Text()) if dialect == "postgresql" else sa.JSON(), nullable=False, server_default=json_empty)
            )
        if "certifications" not in existing_columns:
            batch_op.add_column(
                sa.Column("certifications", postgresql.JSON(astext_type=sa.Text()) if dialect == "postgresql" else sa.JSON(), nullable=False, server_default=json_empty)
            )
        if "specialties" not in existing_columns:
            batch_op.add_column(
                sa.Column("specialties", postgresql.JSON(astext_type=sa.Text()) if dialect == "postgresql" else sa.JSON(), nullable=False, server_default=json_empty)
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}

    with op.batch_alter_table("users", schema=None) as batch_op:
        if "specialties" in existing_columns:
            batch_op.drop_column("specialties")
        if "certifications" in existing_columns:
            batch_op.drop_column("certifications")
        if "portfolio_images" in existing_columns:
            batch_op.drop_column("portfolio_images")
        if "service_areas" in existing_columns:
            batch_op.drop_column("service_areas")
        if "timezone" in existing_columns:
            batch_op.drop_column("timezone")
        if "is_admin" in existing_columns:
            batch_op.drop_column("is_admin")
