"""Add is_accepting_bookings column to users

Revision ID: a1b2c3d4e5f6
Revises: d2f4c6b8a1e0
Create Date: 2026-04-23 12:19:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'd2f4c6b8a1e0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('is_accepting_bookings', sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('is_accepting_bookings')
