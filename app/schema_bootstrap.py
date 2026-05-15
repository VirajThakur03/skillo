from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError, ProgrammingError

from .extensions import db


POSTGRES_ENUMS = {
    "roleenum": ("SEEKER", "PROVIDER"),
    "bookingstatus": ("PENDING", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "DECLINED"),
    "paymentstatus": ("NONE", "AUTHORIZED", "CAPTURED", "REFUNDED", "CASH_COLLECTED"),
    "verificationstatus": ("pending", "document_verified", "face_verified", "completed", "rejected"),
    "refundstatus": ("NONE", "PENDING", "PROCESSED", "FAILED"),
    "wallettransactiontype": ("CREDIT_REFERRAL", "CREDIT_REFUND", "CREDIT_PROMO", "CREDIT_EARNING", "CREDIT_TOPUP", "DEBIT_BOOKING", "DEBIT_WITHDRAWAL", "DEBIT_COMMISSION", "DEBIT_SUBSCRIPTION"),
    "paymentmethod": ("ONLINE", "CASH", "WALLET"),
    "changerequesttype": ("RESCHEDULE", "CANCEL"),
    "changerequeststatus": ("PENDING", "ACCEPTED", "REJECTED", "PROCESSING", "CANCELLED", "FAILED"),
    "notificationcategory": ("BOOKING_UPDATE", "QUOTE_UPDATE", "PAYMENT_UPDATE", "CHAT_MENTION", "PROMOTION"),
    "notificationpriority": ("LOW", "NORMAL", "HIGH", "CRITICAL"),
    "notificationchannel": ("PUSH", "EMAIL", "WHATSAPP", "IN_APP"),
    "notificationdeliverystatus": ("QUEUED", "SENT", "DELIVERED", "FAILED", "SKIPPED"),
    "messagetype": ("text", "image", "file"),
    "quoterequeststatus": ("OPEN", "WAITING_FOR_PROVIDER", "WAITING_FOR_SEEKER", "BOOKED", "CANCELLED", "EXPIRED", "CLOSED"),
    "quotetargetstatus": ("PENDING_RESPONSE", "QUOTE_SENT", "NEEDS_INFO", "DECLINED", "CLOSED_OTHER_ACCEPTED", "EXPIRED"),
    "providerquotestatus": ("ACTIVE", "ACCEPTED", "SUPERSEDED", "EXPIRED", "DECLINED"),
    "quotemessagetype": ("SEEKER_REPLY", "PROVIDER_REPLY", "SYSTEM"),
    "membershipstatus": ("ACTIVE", "CANCELLED", "EXPIRED"),
    "disputestatus": ("OPEN", "UNDER_REVIEW", "RESOLVED", "REJECTED"),
    "referralrewardstatus": ("PENDING", "EARNED", "PAID"),
    "promodiscounttype": ("PERCENT", "FIXED"),
    "jobpoststatus": ("OPEN", "PROVIDER_FOUND", "CANCELLED", "EXPIRED", "BOOKED"),
    "jobproposalstatus": ("ACTIVE", "WITHDRAWN", "SELECTED", "REJECTED"),
    "kycstatus": ("pending", "documents_submitted", "under_review", "approved", "rejected", "suspended"),
}


def _column_specs(dialect):
    refund_type = "refundstatus" if dialect == "postgresql" else "VARCHAR(32)"
    message_type = "messagetype" if dialect == "postgresql" else "VARCHAR(20)"
    json_array_default = "JSON DEFAULT '[]'::json NOT NULL" if dialect == "postgresql" else "JSON DEFAULT '[]' NOT NULL"
    return {
        "users": {
            "avg_response_seconds": "avg_response_seconds INTEGER DEFAULT 0",
            "is_admin": "is_admin BOOLEAN DEFAULT FALSE NOT NULL",
            "timezone": "timezone VARCHAR(64) DEFAULT 'UTC' NOT NULL",
            "service_areas": f"service_areas {json_array_default}",
            "portfolio_images": f"portfolio_images {json_array_default}",
            "certifications": f"certifications {json_array_default}",
            "specialties": f"specialties {json_array_default}",
            "rating": "rating FLOAT DEFAULT 0.0",
            "referral_code": "referral_code VARCHAR(20)",
            "referred_by_id": "referred_by_id INTEGER",
            "wallet_balance": "wallet_balance NUMERIC(10,2) DEFAULT 0.00",
            "is_featured": "is_featured BOOLEAN DEFAULT FALSE",
            "featured_until": "featured_until TIMESTAMP",
            "boost_until": "boost_until TIMESTAMP",
            "profile_photo_url": "profile_photo_url VARCHAR(512)",
        },
        "bookings": {
            "payment_provider": "payment_provider VARCHAR(32)",
            "quote_request_id": "quote_request_id INTEGER",
            "original_scheduled_at": "original_scheduled_at TIMESTAMP",
            "duration_minutes": "duration_minutes INTEGER DEFAULT 60",
            "payment_checkout_session_id": "payment_checkout_session_id VARCHAR(128)",
            "reschedule_count": "reschedule_count INTEGER DEFAULT 0 NOT NULL",
            "refund_status": f"refund_status {refund_type} DEFAULT 'NONE' NOT NULL",
            "platform_fee_pct": "platform_fee_pct NUMERIC(5,2) DEFAULT 5.00",
            "platform_fee_amount": "platform_fee_amount NUMERIC(10,2) DEFAULT 0.00",
            "job_post_id": "job_post_id INTEGER",
            "worker_earnings": "worker_earnings NUMERIC(10,2) DEFAULT 0.00",
            "referral_credit_used": "referral_credit_used NUMERIC(10,2) DEFAULT 0.00",
            "promo_discount_amount": "promo_discount_amount NUMERIC(10,2) DEFAULT 0.00",
            "amount_payable": "amount_payable NUMERIC(10,2) DEFAULT 0.00",
            "cancellation_fee_amount": "cancellation_fee_amount NUMERIC(10,2) DEFAULT 0.00",
            "worker_last_seen_at": "worker_last_seen_at TIMESTAMP",
            "distance_km": "distance_km FLOAT",
            "eta_minutes": "eta_minutes INTEGER",
            "arrived_at": "arrived_at TIMESTAMP",
            "started_at": "started_at TIMESTAMP",
            "completed_at": "completed_at TIMESTAMP",
            "cancelled_at": "cancelled_at TIMESTAMP",
            "cancelled_by_user_id": "cancelled_by_user_id INTEGER",
            "payment_method": "payment_method VARCHAR(32) DEFAULT 'online'",
            "cash_collected_at": "cash_collected_at TIMESTAMP",
            "cash_collected_by": "cash_collected_by INTEGER",
            "refund_amount": "refund_amount NUMERIC(10,2) DEFAULT 0.00",
            "refund_ref": "refund_ref VARCHAR(100)",
            "refund_initiated_at": "refund_initiated_at TIMESTAMP",
            "refund_completed_at": "refund_completed_at TIMESTAMP",
            "refund_reason": "refund_reason VARCHAR(255)",
            "cgst_amount": "cgst_amount NUMERIC(10,2) DEFAULT 0.00",
            "sgst_amount": "sgst_amount NUMERIC(10,2) DEFAULT 0.00",
            "igst_amount": "igst_amount NUMERIC(10,2) DEFAULT 0.00",
            "sac_code": "sac_code VARCHAR(20) DEFAULT '998599'",
        },
        "messages": {
            "message_type": f"message_type {message_type} DEFAULT 'text' NOT NULL",
            "delivered_at": "delivered_at TIMESTAMP",
            "read_at": "read_at TIMESTAMP",
            "is_deleted": "is_deleted BOOLEAN DEFAULT FALSE NOT NULL",
            "deleted_at": "deleted_at TIMESTAMP",
            "attachment_url": "attachment_url VARCHAR(512)",
            "summary_tag": "summary_tag VARCHAR(255)",
            "read_by": f"read_by {json_array_default}",
        },
        "reviews": {
            "punctuality_rating": "punctuality_rating FLOAT",
            "quality_rating": "quality_rating FLOAT",
            "communication_rating": "communication_rating FLOAT",
            "value_rating": "value_rating FLOAT",
        },
    }


def _ensure_postgres_enums():
    for enum_name, values in POSTGRES_ENUMS.items():
        values_sql = ", ".join(f"'{value}'" for value in values)
        db.session.execute(
            text(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_type
                        WHERE typname = '{enum_name}'
                    ) THEN
                        CREATE TYPE {enum_name} AS ENUM ({values_sql});
                    END IF;
                END
                $$;
                """
            )
        )
    db.session.commit()


def _ensure_missing_columns():
    inspector = inspect(db.engine)
    specs = _column_specs(db.engine.dialect.name)
    for table_name, columns in specs.items():
        if table_name not in inspector.get_table_names():
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, ddl in columns.items():
            if column_name in existing:
                continue
            db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))
    db.session.commit()


def _ensure_missing_indexes():
    inspector = inspect(db.engine)
    # Messages: ix_messages_room_created
    if "messages" in inspector.get_table_names():
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("messages")}
        if "ix_messages_room_created" not in existing_indexes:
            db.session.execute(text("CREATE INDEX ix_messages_room_created ON messages (room, created_at)"))
    db.session.commit()


def ensure_runtime_schema(app):
    if not app.config.get("AUTO_SYNC_SCHEMA", True):
        return

    try:
        if db.engine.dialect.name == "postgresql":
            _ensure_postgres_enums()
        db.create_all()
        _ensure_missing_columns()
        _ensure_missing_indexes()
    except (OperationalError, ProgrammingError) as exc:
        db.session.rollback()
        app.logger.warning("Schema bootstrap skipped: %s", exc)
