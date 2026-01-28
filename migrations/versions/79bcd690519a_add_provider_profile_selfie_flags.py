"""add provider profile + selfie flags + extend verificationstatus enum

Revision ID: 79bcd690519a
Revises: 4e4104979c93
Create Date: 2026-01-23 16:00:02.238799
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "79bcd690519a"
down_revision = "4e4104979c93"
branch_labels = None
depends_on = None


def upgrade():
    # -------------------------------------------------
    # 1️⃣ EXTEND verificationstatus ENUM (PERMANENT)
    # -------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumlabel = 'document_verified'
            ) THEN
                ALTER TYPE verificationstatus ADD VALUE 'document_verified';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumlabel = 'face_verified'
            ) THEN
                ALTER TYPE verificationstatus ADD VALUE 'face_verified';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumlabel = 'completed'
            ) THEN
                ALTER TYPE verificationstatus ADD VALUE 'completed';
            END IF;
        END
        $$;
        """
    )

    # -------------------------------------------------
    # 2️⃣ ADD provider profile completion flag (SAFE)
    # -------------------------------------------------
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_provider_profile_complete",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),  # 🔥 prevents NOT NULL crash
            )
        )

    # -------------------------------------------------
    # 3️⃣ CLEAN DEFAULT (OPTIONAL BUT RECOMMENDED)
    # -------------------------------------------------
    # Keeps DB clean after existing rows are filled
    op.alter_column(
        "users",
        "is_provider_profile_complete",
        server_default=None
    )


def downgrade():
    # ⚠️ Enum values CANNOT be safely removed in Postgres
    # So we only rollback the column
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("is_provider_profile_complete")
