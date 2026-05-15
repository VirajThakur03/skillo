"""add marketplace PRD schema

Revision ID: c5d6e7f8a9b0
Revises: 79bcd690519a
Create Date: 2026-04-07 23:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c5d6e7f8a9b0"  # pragma: allowlist secret
down_revision = "79bcd690519a"  # pragma: allowlist secret
branch_labels = None
depends_on = None


REFUND_STATUS_VALUES = ("NONE", "PENDING", "PROCESSED", "FAILED")
CHANGE_REQUEST_TYPE_VALUES = ("RESCHEDULE", "CANCEL")
CHANGE_REQUEST_STATUS_VALUES = ("PENDING", "ACCEPTED", "REJECTED", "PROCESSING", "CANCELLED", "FAILED")
NOTIFICATION_CATEGORY_VALUES = ("BOOKING_UPDATE", "QUOTE_UPDATE", "PAYMENT_UPDATE", "CHAT_MENTION", "PROMOTION")
NOTIFICATION_PRIORITY_VALUES = ("LOW", "NORMAL", "HIGH", "CRITICAL")
NOTIFICATION_CHANNEL_VALUES = ("PUSH", "EMAIL", "WHATSAPP", "IN_APP")
NOTIFICATION_DELIVERY_STATUS_VALUES = ("QUEUED", "SENT", "DELIVERED", "FAILED", "SKIPPED")
QUOTE_REQUEST_STATUS_VALUES = ("OPEN", "WAITING_FOR_PROVIDER", "WAITING_FOR_SEEKER", "BOOKED", "CANCELLED", "EXPIRED", "CLOSED")
QUOTE_TARGET_STATUS_VALUES = ("PENDING_RESPONSE", "QUOTE_SENT", "NEEDS_INFO", "DECLINED", "CLOSED_OTHER_ACCEPTED", "EXPIRED")
PROVIDER_QUOTE_STATUS_VALUES = ("ACTIVE", "ACCEPTED", "SUPERSEDED", "EXPIRED", "DECLINED")
QUOTE_MESSAGE_TYPE_VALUES = ("SEEKER_REPLY", "PROVIDER_REPLY", "SYSTEM")
MEMBERSHIP_STATUS_VALUES = ("ACTIVE", "CANCELLED", "EXPIRED")
DISPUTE_STATUS_VALUES = ("OPEN", "UNDER_REVIEW", "RESOLVED", "REJECTED")
REFERRAL_REWARD_STATUS_VALUES = ("PENDING", "EARNED", "PAID")
PROMO_DISCOUNT_TYPE_VALUES = ("PERCENT", "FIXED")


def _dialect():
    return op.get_bind().dialect.name


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name):
    return table_name in _inspector().get_table_names()


def _has_column(table_name, column_name):
    if not _has_table(table_name):
        return False
    return column_name in {column["name"] for column in _inspector().get_columns(table_name)}


def _has_foreign_key(table_name, constraint_name=None, constrained_columns=None, referred_table=None):
    if not _has_table(table_name):
        return False
    foreign_keys = _inspector().get_foreign_keys(table_name)
    for foreign_key in foreign_keys:
        if constraint_name and foreign_key.get("name") == constraint_name:
            return True
        if constrained_columns and referred_table:
            if (
                list(foreign_key.get("constrained_columns") or []) == list(constrained_columns)
                and foreign_key.get("referred_table") == referred_table
            ):
                return True
    return False


def _create_table_if_missing(table_name, *args, **kwargs):
    if _has_table(table_name):
        return
    op.create_table(table_name, *args, **kwargs)


def _json_array_default():
    return sa.text("'[]'::json") if _dialect() == "postgresql" else sa.text("'[]'")


def _json_object_default():
    return sa.text("'{}'::json") if _dialect() == "postgresql" else sa.text("'{}'")


def _named_enum(name, values):
    if _dialect() == "postgresql":
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def _create_enum(name, values):
    if _dialect() != "postgresql":
        return
    value_sql = ", ".join(f"'{value}'" for value in values)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = '{name}'
            ) THEN
                CREATE TYPE {name} AS ENUM ({value_sql});
            END IF;
        END
        $$;
        """
    )


def _drop_enum(name):
    if _dialect() == "postgresql":
        op.execute(f"DROP TYPE IF EXISTS {name}")


def upgrade():
    for name, values in (
        ("refundstatus", REFUND_STATUS_VALUES),
        ("changerequesttype", CHANGE_REQUEST_TYPE_VALUES),
        ("changerequeststatus", CHANGE_REQUEST_STATUS_VALUES),
        ("notificationcategory", NOTIFICATION_CATEGORY_VALUES),
        ("notificationpriority", NOTIFICATION_PRIORITY_VALUES),
        ("notificationchannel", NOTIFICATION_CHANNEL_VALUES),
        ("notificationdeliverystatus", NOTIFICATION_DELIVERY_STATUS_VALUES),
        ("quoterequeststatus", QUOTE_REQUEST_STATUS_VALUES),
        ("quotetargetstatus", QUOTE_TARGET_STATUS_VALUES),
        ("providerquotestatus", PROVIDER_QUOTE_STATUS_VALUES),
        ("quotemessagetype", QUOTE_MESSAGE_TYPE_VALUES),
        ("membershipstatus", MEMBERSHIP_STATUS_VALUES),
        ("disputestatus", DISPUTE_STATUS_VALUES),
        ("referralrewardstatus", REFERRAL_REWARD_STATUS_VALUES),
        ("promodiscounttype", PROMO_DISCOUNT_TYPE_VALUES),
    ):
        _create_enum(name, values)

    with op.batch_alter_table("users", schema=None) as batch_op:
        if not _has_column("users", "is_admin"):
            batch_op.add_column(sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()))
        if not _has_column("users", "timezone"):
            batch_op.add_column(sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"))
        if not _has_column("users", "service_areas"):
            batch_op.add_column(sa.Column("service_areas", sa.JSON(), nullable=False, server_default=_json_array_default()))
        if not _has_column("users", "portfolio_images"):
            batch_op.add_column(sa.Column("portfolio_images", sa.JSON(), nullable=False, server_default=_json_array_default()))
        if not _has_column("users", "certifications"):
            batch_op.add_column(sa.Column("certifications", sa.JSON(), nullable=False, server_default=_json_array_default()))
        if not _has_column("users", "specialties"):
            batch_op.add_column(sa.Column("specialties", sa.JSON(), nullable=False, server_default=_json_array_default()))

    _create_table_if_missing(
        "favorite_providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seeker_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["seeker_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seeker_id", "provider_id", name="uq_favorite_provider"),
    )
    _create_table_if_missing(
        "provider_availability_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=True),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_minute_local", sa.Integer(), nullable=False),
        sa.Column("end_minute_local", sa.Integer(), nullable=False),
        sa.Column("buffer_before_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buffer_after_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_notice_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("max_advance_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "provider_blackouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("reason_code", sa.String(length=32), nullable=False, server_default="OTHER"),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "provider_instant_book_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("instant_book_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("slot_duration_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("slot_hold_minutes", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("enabled_skill_ids", sa.JSON(), nullable=False, server_default=_json_array_default()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id"),
    )
    _create_table_if_missing(
        "booking_change_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=True),
        sa.Column("free_cancel_until_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("partial_fee_until_hours", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("partial_fee_percent", sa.Numeric(precision=5, scale=2), nullable=False, server_default="10.00"),
        sa.Column("partial_fee_min_amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="100.00"),
        sa.Column("late_fee_percent", sa.Numeric(precision=5, scale=2), nullable=False, server_default="25.00"),
        sa.Column("late_fee_min_amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="250.00"),
        sa.Column("max_reschedules", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id"),
    )
    _create_table_if_missing(
        "quote_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seeker_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=True),
        sa.Column("service_title", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("address_text", sa.String(length=255), nullable=True),
        sa.Column("preferred_window_start", sa.DateTime(), nullable=True),
        sa.Column("preferred_window_end", sa.DateTime(), nullable=True),
        sa.Column("budget_min", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("budget_max", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("attachments", sa.JSON(), nullable=False, server_default=_json_array_default()),
        sa.Column("status", _named_enum("quoterequeststatus", QUOTE_REQUEST_STATUS_VALUES), nullable=False, server_default="OPEN"),
        sa.Column("accepted_provider_quote_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["seeker_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("bookings", schema=None) as batch_op:
        if not _has_column("bookings", "quote_request_id"):
            batch_op.add_column(sa.Column("quote_request_id", sa.Integer(), nullable=True))
        if not _has_column("bookings", "original_scheduled_at"):
            batch_op.add_column(sa.Column("original_scheduled_at", sa.DateTime(), nullable=True))
        if not _has_column("bookings", "reschedule_count"):
            batch_op.add_column(sa.Column("reschedule_count", sa.Integer(), nullable=False, server_default="0"))
        if not _has_column("bookings", "refund_status"):
            batch_op.add_column(sa.Column("refund_status", _named_enum("refundstatus", REFUND_STATUS_VALUES), nullable=False, server_default="NONE"))
        if not _has_column("bookings", "eta_minutes"):
            batch_op.add_column(sa.Column("eta_minutes", sa.Integer(), nullable=True))
        if not _has_column("bookings", "arrived_at"):
            batch_op.add_column(sa.Column("arrived_at", sa.DateTime(), nullable=True))
        if not _has_column("bookings", "started_at"):
            batch_op.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
        if not _has_column("bookings", "completed_at"):
            batch_op.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
        if not _has_column("bookings", "cancelled_at"):
            batch_op.add_column(sa.Column("cancelled_at", sa.DateTime(), nullable=True))
        if not _has_column("bookings", "cancelled_by_user_id"):
            batch_op.add_column(sa.Column("cancelled_by_user_id", sa.Integer(), nullable=True))
        if not _has_column("bookings", "cancellation_fee_amount"):
            batch_op.add_column(sa.Column("cancellation_fee_amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"))
        if not _has_foreign_key(
            "bookings",
            constraint_name="fk_bookings_quote_request_id",
            constrained_columns=["quote_request_id"],
            referred_table="quote_requests",
        ):
            batch_op.create_foreign_key("fk_bookings_quote_request_id", "quote_requests", ["quote_request_id"], ["id"])
        if not _has_foreign_key(
            "bookings",
            constraint_name="fk_bookings_cancelled_by_user_id",
            constrained_columns=["cancelled_by_user_id"],
            referred_table="users",
        ):
            batch_op.create_foreign_key("fk_bookings_cancelled_by_user_id", "users", ["cancelled_by_user_id"], ["id"])
    op.execute("UPDATE bookings SET original_scheduled_at = scheduled_at WHERE original_scheduled_at IS NULL")

    _create_table_if_missing(
        "booking_change_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("request_type", _named_enum("changerequesttype", CHANGE_REQUEST_TYPE_VALUES), nullable=False),
        sa.Column("initiated_by_user_id", sa.Integer(), nullable=False),
        sa.Column("status", _named_enum("changerequeststatus", CHANGE_REQUEST_STATUS_VALUES), nullable=False, server_default="PENDING"),
        sa.Column("reason_code", sa.String(length=32), nullable=False, server_default="OTHER"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("proposed_start_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("fee_amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"),
        sa.Column("refund_amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"),
        sa.Column("goodwill_credit_amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.ForeignKeyConstraint(["initiated_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "booking_timeline_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=_json_object_default()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("messages", schema=None) as batch_op:
        if not _has_column("messages", "attachment_url"):
            batch_op.add_column(sa.Column("attachment_url", sa.String(length=512), nullable=True))
        if not _has_column("messages", "summary_tag"):
            batch_op.add_column(sa.Column("summary_tag", sa.String(length=255), nullable=True))
        if not _has_column("messages", "read_by"):
            batch_op.add_column(sa.Column("read_by", sa.JSON(), nullable=False, server_default=_json_array_default()))

    _create_table_if_missing(
        "reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("seeker_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("punctuality_rating", sa.Float(), nullable=True),
        sa.Column("quality_rating", sa.Float(), nullable=True),
        sa.Column("communication_rating", sa.Float(), nullable=True),
        sa.Column("value_rating", sa.Float(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["seeker_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_id"),
    )
    _create_table_if_missing(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), nullable=False),
        sa.Column("category", _named_enum("notificationcategory", NOTIFICATION_CATEGORY_VALUES), nullable=False),
        sa.Column("priority", _named_enum("notificationpriority", NOTIFICATION_PRIORITY_VALUES), nullable=False, server_default="NORMAL"),
        sa.Column("title", sa.String(length=140), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("deep_link", sa.String(length=255), nullable=True),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "notification_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("push_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("whatsapp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("category_channels", sa.JSON(), nullable=False, server_default=_json_object_default()),
        sa.Column("quiet_hours_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("quiet_start_local", sa.String(length=5), nullable=True),
        sa.Column("quiet_end_local", sa.String(length=5), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    _create_table_if_missing(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=False),
        sa.Column("channel", _named_enum("notificationchannel", NOTIFICATION_CHANNEL_VALUES), nullable=False),
        sa.Column("status", _named_enum("notificationdeliverystatus", NOTIFICATION_DELIVERY_STATUS_VALUES), nullable=False, server_default="QUEUED"),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("provider_message_id", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=_json_object_default()),
        sa.Column("attempted_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "quote_request_provider_targets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("quote_request_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("target_status", _named_enum("quotetargetstatus", QUOTE_TARGET_STATUS_VALUES), nullable=False, server_default="PENDING_RESPONSE"),
        sa.Column("first_notified_at", sa.DateTime(), nullable=True),
        sa.Column("response_due_at", sa.DateTime(), nullable=True),
        sa.Column("closed_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["quote_request_id"], ["quote_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("quote_request_id", "provider_id", name="uq_quote_target"),
    )
    _create_table_if_missing(
        "provider_quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("quote_request_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="INR"),
        sa.Column("total_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("line_items", sa.JSON(), nullable=False, server_default=_json_array_default()),
        sa.Column("estimated_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("earliest_available_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("status", _named_enum("providerquotestatus", PROVIDER_QUOTE_STATUS_VALUES), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["quote_request_id"], ["quote_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("quote_request_id", "provider_id", "revision_number", name="uq_provider_quote_revision"),
    )
    _create_table_if_missing(
        "quote_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("quote_request_id", sa.Integer(), nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("message_type", _named_enum("quotemessagetype", QUOTE_MESSAGE_TYPE_VALUES), nullable=False, server_default="SYSTEM"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False, server_default=_json_array_default()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["quote_request_id"], ["quote_requests.id"]),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "search_query_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("query_text", sa.String(length=140), nullable=True),
        sa.Column("filters", sa.JSON(), nullable=False, server_default=_json_object_default()),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicked_provider_id", sa.Integer(), nullable=True),
        sa.Column("booked_provider_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["booked_provider_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["clicked_provider_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "booking_disputes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("opened_by_user_id", sa.Integer(), nullable=False),
        sa.Column("assigned_admin_id", sa.Integer(), nullable=True),
        sa.Column("status", _named_enum("disputestatus", DISPUTE_STATUS_VALUES), nullable=False, server_default="OPEN"),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="OTHER"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=_json_array_default()),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("refund_amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["assigned_admin_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.ForeignKeyConstraint(["opened_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "referral_rewards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referrer_user_id", sa.Integer(), nullable=False),
        sa.Column("referred_user_id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=True),
        sa.Column("status", _named_enum("referralrewardstatus", REFERRAL_REWARD_STATUS_VALUES), nullable=False, server_default="PENDING"),
        sa.Column("reward_amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.ForeignKeyConstraint(["referred_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "promo_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=140), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("discount_type", _named_enum("promodiscounttype", PROMO_DISCOUNT_TYPE_VALUES), nullable=False, server_default="PERCENT"),
        sa.Column("discount_value", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"),
        sa.Column("max_discount_amount", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("min_order_amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("usage_limit", sa.Integer(), nullable=True),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("first_booking_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    _create_table_if_missing(
        "promo_redemptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("promo_code_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=True),
        sa.Column("discount_amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.ForeignKeyConstraint(["promo_code_id"], ["promo_codes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "subscription_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("audience", sa.String(length=20), nullable=False, server_default="SEEKER"),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"),
        sa.Column("billing_period", sa.String(length=20), nullable=False, server_default="monthly"),
        sa.Column("benefits", sa.JSON(), nullable=False, server_default=_json_array_default()),
        sa.Column("priority_support", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reduced_fee_pct", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("loyalty_credit", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    _create_table_if_missing(
        "user_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("status", _named_enum("membershipstatus", MEMBERSHIP_STATUS_VALUES), nullable=False, server_default="ACTIVE"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["subscription_plans.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "fraud_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("booking_id", sa.Integer(), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="low"),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "chat_insights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("room", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("extracted_address", sa.String(length=255), nullable=True),
        sa.Column("extracted_time", sa.String(length=120), nullable=True),
        sa.Column("quick_replies", sa.JSON(), nullable=False, server_default=_json_array_default()),
        sa.Column("pinned_summary", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "ai_job_intake_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("parsed_payload", sa.JSON(), nullable=False, server_default=_json_object_default()),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    for table in (
        "ai_job_intake_logs",
        "chat_insights",
        "fraud_flags",
        "user_subscriptions",
        "subscription_plans",
        "promo_redemptions",
        "promo_codes",
        "referral_rewards",
        "booking_disputes",
        "search_query_logs",
        "quote_messages",
        "provider_quotes",
        "quote_request_provider_targets",
        "notification_deliveries",
        "notification_preferences",
        "notifications",
        "reviews",
    ):
        op.drop_table(table)

    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.drop_column("read_by")
        batch_op.drop_column("summary_tag")
        batch_op.drop_column("attachment_url")

    for table in (
        "booking_timeline_events",
        "booking_change_requests",
    ):
        op.drop_table(table)

    with op.batch_alter_table("bookings", schema=None) as batch_op:
        batch_op.drop_constraint("fk_bookings_cancelled_by_user_id", type_="foreignkey")
        batch_op.drop_constraint("fk_bookings_quote_request_id", type_="foreignkey")
        batch_op.drop_column("cancellation_fee_amount")
        batch_op.drop_column("cancelled_by_user_id")
        batch_op.drop_column("cancelled_at")
        batch_op.drop_column("completed_at")
        batch_op.drop_column("started_at")
        batch_op.drop_column("arrived_at")
        batch_op.drop_column("eta_minutes")
        batch_op.drop_column("refund_status")
        batch_op.drop_column("reschedule_count")
        batch_op.drop_column("original_scheduled_at")
        batch_op.drop_column("quote_request_id")

    for table in (
        "quote_requests",
        "booking_change_policies",
        "provider_instant_book_settings",
        "provider_blackouts",
        "provider_availability_rules",
        "favorite_providers",
    ):
        op.drop_table(table)

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("specialties")
        batch_op.drop_column("certifications")
        batch_op.drop_column("portfolio_images")
        batch_op.drop_column("service_areas")
        batch_op.drop_column("timezone")
        batch_op.drop_column("is_admin")

    for name in (
        "promodiscounttype",
        "referralrewardstatus",
        "disputestatus",
        "membershipstatus",
        "quotemessagetype",
        "providerquotestatus",
        "quotetargetstatus",
        "quoterequeststatus",
        "notificationdeliverystatus",
        "notificationchannel",
        "notificationpriority",
        "notificationcategory",
        "changerequeststatus",
        "changerequesttype",
        "refundstatus",
    ):
        _drop_enum(name)
