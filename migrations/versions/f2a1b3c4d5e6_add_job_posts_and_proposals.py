"""add job posts and proposals

Revision ID: f2a1b3c4d5e6
Revises: e4f1a9c2d7b3
Create Date: 2026-04-28 16:21:00

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "f2a1b3c4d5e6"
down_revision = "e4f1a9c2d7b3"
branch_labels = None
depends_on = None


JOB_POST_STATUS_VALUES = ("OPEN", "PROVIDER_FOUND", "CANCELLED", "EXPIRED", "BOOKED")
JOB_PROPOSAL_STATUS_VALUES = ("ACTIVE", "WITHDRAWN", "SELECTED", "REJECTED")


def _dialect():
    return op.get_bind().dialect.name


def _inspector():
    return inspect(op.get_bind())


def _table_exists(table_name):
    return table_name in _inspector().get_table_names()


def _column_exists(table_name, column_name):
    if not _table_exists(table_name):
        return False
    return column_name in {column["name"] for column in _inspector().get_columns(table_name)}


def _foreign_key_exists(table_name, constraint_name):
    if not _table_exists(table_name):
        return False
    return any((fk.get("name") or "") == constraint_name for fk in _inspector().get_foreign_keys(table_name))


def _index_exists(table_name, index_name):
    if not _table_exists(table_name):
        return False
    return any((idx.get("name") or "") == index_name for idx in _inspector().get_indexes(table_name))


def _named_enum(name, values):
    if _dialect() == "postgresql":
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)

def _ensure_postgres_enums():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'jobpoststatus') THEN
                CREATE TYPE jobpoststatus AS ENUM ('OPEN', 'PROVIDER_FOUND', 'CANCELLED', 'EXPIRED', 'BOOKED');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'jobproposalstatus') THEN
                CREATE TYPE jobproposalstatus AS ENUM ('ACTIVE', 'WITHDRAWN', 'SELECTED', 'REJECTED');
            END IF;
        END
        $$;
    """))

def upgrade():
    _ensure_postgres_enums()

    if not _table_exists("job_posts"):
        op.create_table(
            "job_posts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("seeker_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("budget_min", sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column("budget_max", sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column("currency", sa.String(length=10), nullable=True, server_default="INR"),
            sa.Column("location_text", sa.String(length=255), nullable=True),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("scheduled_for", sa.DateTime(), nullable=True),
            sa.Column("status", _named_enum("jobpoststatus", JOB_POST_STATUS_VALUES), nullable=False, server_default="OPEN"),
            sa.Column("selected_provider_id", sa.Integer(), nullable=True),
            sa.Column("selected_at", sa.DateTime(), nullable=True),
            sa.Column("provider_found_visible_until", sa.DateTime(), nullable=True),
            sa.Column("cancel_allowed_until", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["seeker_id"], ["users.id"], name="fk_job_posts_seeker"),
            sa.ForeignKeyConstraint(["selected_provider_id"], ["users.id"], name="fk_job_posts_provider"),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists("job_posts", "ix_job_posts_status"):
        op.create_index("ix_job_posts_status", "job_posts", ["status"], unique=False)
    if not _index_exists("job_posts", "ix_job_posts_created_at"):
        op.create_index("ix_job_posts_created_at", "job_posts", ["created_at"], unique=False)

    if not _table_exists("job_proposals"):
        op.create_table(
            "job_proposals",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_post_id", sa.Integer(), nullable=False),
            sa.Column("provider_id", sa.Integer(), nullable=False),
            sa.Column("cover_message", sa.Text(), nullable=True),
            sa.Column("quoted_amount", sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column("estimated_duration_minutes", sa.Integer(), nullable=True, server_default="60"),
            sa.Column("available_from", sa.DateTime(), nullable=True),
            sa.Column("status", _named_enum("jobproposalstatus", JOB_PROPOSAL_STATUS_VALUES), nullable=False, server_default="ACTIVE"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["job_post_id"], ["job_posts.id"], name="fk_job_proposals_job_post"),
            sa.ForeignKeyConstraint(["provider_id"], ["users.id"], name="fk_job_proposals_provider"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("job_post_id", "provider_id", name="uq_job_proposal_provider"),
        )
    if not _index_exists("job_proposals", "ix_job_proposals_status"):
        op.create_index("ix_job_proposals_status", "job_proposals", ["status"], unique=False)

    if not _column_exists("bookings", "job_post_id"):
        op.add_column("bookings", sa.Column("job_post_id", sa.Integer(), nullable=True))
    if not _foreign_key_exists("bookings", "fk_bookings_job_post"):
        op.create_foreign_key("fk_bookings_job_post", "bookings", "job_posts", ["job_post_id"], ["id"])
    with op.batch_alter_table("bookings", schema=None) as batch_op:
        batch_op.alter_column("skill_id", existing_type=sa.INTEGER(), nullable=True)

def downgrade():
    with op.batch_alter_table("bookings", schema=None) as batch_op:
        batch_op.alter_column("skill_id", existing_type=sa.INTEGER(), nullable=False)
    op.drop_constraint("fk_bookings_job_post", "bookings", type_="foreignkey")
    op.drop_column("bookings", "job_post_id")
    
    op.drop_table("job_proposals")
    op.drop_table("job_posts")
    
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS jobpoststatus")
        op.execute("DROP TYPE IF EXISTS jobproposalstatus")
