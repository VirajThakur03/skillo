"""add reviews table for seeker feedback per booking

Revision ID: b7a1c2d3e4f5
Revises: ec34e6b07788
Create Date: 2026-04-11

"""
from alembic import op
import sqlalchemy as sa


revision = "b7a1c2d3e4f5"
down_revision = "ec34e6b07788"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "reviews" not in inspector.get_table_names():
        op.create_table(
            "reviews",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("booking_id", sa.Integer(), nullable=False),
            sa.Column("seeker_id", sa.Integer(), nullable=False),
            sa.Column("provider_id", sa.Integer(), nullable=False),
            sa.Column("rating", sa.Float(), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("punctuality_rating", sa.Float(), nullable=True),
            sa.Column("quality_rating", sa.Float(), nullable=True),
            sa.Column("communication_rating", sa.Float(), nullable=True),
            sa.Column("value_rating", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
            sa.ForeignKeyConstraint(["provider_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["seeker_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    indexes = {index["name"] for index in inspector.get_indexes("reviews")}
    booking_index = op.f("ix_reviews_booking_id")
    provider_index = op.f("ix_reviews_provider_id")
    seeker_index = op.f("ix_reviews_seeker_id")
    if booking_index not in indexes:
        op.create_index(booking_index, "reviews", ["booking_id"], unique=True)
    if provider_index not in indexes:
        op.create_index(provider_index, "reviews", ["provider_id"], unique=False)
    if seeker_index not in indexes:
        op.create_index(seeker_index, "reviews", ["seeker_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_reviews_seeker_id"), table_name="reviews")
    op.drop_index(op.f("ix_reviews_provider_id"), table_name="reviews")
    op.drop_index(op.f("ix_reviews_booking_id"), table_name="reviews")
    op.drop_table("reviews")
