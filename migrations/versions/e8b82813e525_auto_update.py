"""auto update

Revision ID: e8b82813e525
Revises: e308fb3b1730
Create Date: 2025-12-07 07:30:08.131625
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e8b82813e525"
down_revision = "e308fb3b1730"
branch_labels = None
depends_on = None


def upgrade():
    # ================================
    # BOOKINGS: monetization + tracking
    # ================================
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("platform_fee_pct", sa.Numeric(5, 2), nullable=True))
        batch_op.add_column(sa.Column("platform_fee_amount", sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(sa.Column("worker_earnings", sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(sa.Column("referral_credit_used", sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(sa.Column("worker_latitude", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("worker_longitude", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("worker_last_seen_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("distance_km", sa.Float(), nullable=True))

    # ==========================================
    # USERS: video verification + wallet + boost
    # ==========================================
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("verification_video_filename", sa.String(512), nullable=True)
        )

        # IMPORTANT: reuse existing enum type
        verification_enum = sa.Enum(
            "pending",
            "verified",
            "rejected",
            name="verificationstatus",
            create_type=False,   # 🔥 CRITICAL
        )

        batch_op.add_column(
            sa.Column(
                "verification_video_status",
                verification_enum,
                nullable=False,
                server_default="pending",
            )
        )

        batch_op.add_column(sa.Column("referral_code", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("referred_by_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("wallet_balance", sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(sa.Column("badges", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("completed_jobs", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("avg_response_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("is_featured", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("featured_until", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("boost_until", sa.DateTime(), nullable=True))

        batch_op.create_index(
            "ix_users_referral_code",
            ["referral_code"],
            unique=True,
        )

        batch_op.create_foreign_key(
            "fk_users_referred_by",
            "users",
            ["referred_by_id"],
            ["id"],
        )

    # 🔥 REMOVE DEFAULT AFTER DATA IS SAFE
    op.execute(
        "ALTER TABLE users ALTER COLUMN verification_video_status DROP DEFAULT"
    )


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_referred_by", type_="foreignkey")
        batch_op.drop_index("ix_users_referral_code")
        batch_op.drop_column("boost_until")
        batch_op.drop_column("featured_until")
        batch_op.drop_column("is_featured")
        batch_op.drop_column("avg_response_seconds")
        batch_op.drop_column("completed_jobs")
        batch_op.drop_column("badges")
        batch_op.drop_column("wallet_balance")
        batch_op.drop_column("referred_by_id")
        batch_op.drop_column("referral_code")
        batch_op.drop_column("verification_video_status")
        batch_op.drop_column("verification_video_filename")

    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_column("distance_km")
        batch_op.drop_column("worker_last_seen_at")
        batch_op.drop_column("worker_longitude")
        batch_op.drop_column("worker_latitude")
        batch_op.drop_column("referral_credit_used")
        batch_op.drop_column("worker_earnings")
        batch_op.drop_column("platform_fee_amount")
        batch_op.drop_column("platform_fee_pct")
