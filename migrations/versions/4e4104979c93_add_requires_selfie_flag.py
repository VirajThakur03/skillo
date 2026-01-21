"""add requires_selfie flag

Revision ID: 4e4104979c93
Revises: 2770b0e5f934
Create Date: 2026-01-21 09:34:00.785352

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4e4104979c93'
down_revision = '2770b0e5f934'
branch_labels = None
depends_on = None


def upgrade():
    # 1️⃣ Add column as nullable with default
    op.add_column(
        'users',
        sa.Column(
            'requires_selfie',
            sa.Boolean(),
            nullable=True,
            server_default=sa.false()
        )
    )

    # 2️⃣ Backfill existing rows
    op.execute(
        "UPDATE users SET requires_selfie = FALSE WHERE requires_selfie IS NULL"
    )

    # 3️⃣ Enforce NOT NULL
    op.alter_column(
        'users',
        'requires_selfie',
        nullable=False,
        server_default=None
    )


def downgrade():
    op.drop_column('users', 'requires_selfie')
