"""add stripe columns to users

Revision ID: add_stripe_to_users
Revises: composite_indexes
Create Date: 2026-04-25 07:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_stripe_to_users'
down_revision = 'composite_indexes'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('stripe_account_id', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('stripe_onboarding_complete', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_index(batch_op.f('ix_users_stripe_account_id'), ['stripe_account_id'], unique=True)


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_stripe_account_id'))
        batch_op.drop_column('stripe_onboarding_complete')
        batch_op.drop_column('stripe_account_id')
