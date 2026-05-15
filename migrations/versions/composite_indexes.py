"""add_composite_indexes

Revision ID: composite_indexes
Revises: a1b2c3d4e5f6
Create Date: 2026-04-23 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'composite_indexes'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

def upgrade():
    op.create_index('ix_bookings_seeker_status', 'bookings', ['seeker_id', 'status'])
    op.create_index('ix_bookings_provider_status', 'bookings', ['provider_id', 'status'])
    op.create_index('ix_messages_room_created', 'messages', ['room', 'created_at'])
    op.create_index('ix_skills_provider_active', 'skills', ['provider_id', 'is_active'])

def downgrade():
    op.drop_index('ix_bookings_seeker_status', table_name='bookings')
    op.drop_index('ix_bookings_provider_status', table_name='bookings')
    op.drop_index('ix_messages_room_created', table_name='messages')
    op.drop_index('ix_skills_provider_active', table_name='skills')
