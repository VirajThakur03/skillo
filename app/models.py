# app/models.py

from datetime import datetime, timezone
import enum
import uuid

from sqlalchemy.dialects.postgresql import JSON
from .extensions import db


def _utc_now():
    """Returns a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)



# ====================
# ENUMS (MATCH DB EXACTLY)
# ====================

class RoleEnum(enum.Enum):
    SEEKER = "SEEKER"
    PROVIDER = "PROVIDER"


class BookingStatus(enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DECLINED = "DECLINED"


class PaymentStatus(enum.Enum):
    NONE = "NONE"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"
    CASH_COLLECTED = "CASH_COLLECTED"


class VerificationStatus(enum.Enum):
    pending = "pending"
    document_verified = "document_verified"
    face_verified = "face_verified"
    completed = "completed"
    rejected = "rejected"


class KycStatus(enum.Enum):
    pending = "pending"
    documents_submitted = "documents_submitted"
    under_review = "under_review"
    approved = "approved"
    rejected = "rejected"
    suspended = "suspended"


class PromoDiscountType(enum.Enum):
    PERCENT = "PERCENT"
    FIXED = "FIXED"


class ReferralRewardStatus(enum.Enum):
    PENDING = "PENDING"
    EARNED = "EARNED"
    PAID = "PAID"


class RefundStatus(enum.Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class WalletTransactionType(enum.Enum):
    CREDIT_REFERRAL = "CREDIT_REFERRAL"
    CREDIT_REFUND = "CREDIT_REFUND"
    CREDIT_PROMO = "CREDIT_PROMO"
    CREDIT_EARNING = "CREDIT_EARNING"
    CREDIT_TOPUP = "CREDIT_TOPUP"
    DEBIT_BOOKING = "DEBIT_BOOKING"
    DEBIT_WITHDRAWAL = "DEBIT_WITHDRAWAL"
    DEBIT_COMMISSION = "DEBIT_COMMISSION"
    DEBIT_SUBSCRIPTION = "DEBIT_SUBSCRIPTION"


class PaymentMethod(enum.Enum):
    ONLINE = "ONLINE"
    CASH = "CASH"
    WALLET = "WALLET"


class QuoteRequestStatus(enum.Enum):
    OPEN = "OPEN"
    WAITING_FOR_PROVIDER = "WAITING_FOR_PROVIDER"
    WAITING_FOR_SEEKER = "WAITING_FOR_SEEKER"
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class NotificationCategory(enum.Enum):
    BOOKING_UPDATE = "BOOKING_UPDATE"
    QUOTE_UPDATE = "QUOTE_UPDATE"
    PAYMENT_UPDATE = "PAYMENT_UPDATE"
    CHAT_MENTION = "CHAT_MENTION"
    PROMOTION = "PROMOTION"


class NotificationPriority(enum.Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class JobPostStatus(enum.Enum):
    OPEN = "OPEN"
    PROVIDER_FOUND = "PROVIDER_FOUND"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    BOOKED = "BOOKED"


class JobProposalStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"


class NotificationChannel(enum.Enum):
    PUSH = "PUSH"
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    IN_APP = "IN_APP"


class NotificationDeliveryStatus(enum.Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class QuoteTargetStatus(enum.Enum):
    PENDING_RESPONSE = "PENDING_RESPONSE"
    QUOTE_SENT = "QUOTE_SENT"
    NEEDS_INFO = "NEEDS_INFO"
    DECLINED = "DECLINED"
    CLOSED_OTHER_ACCEPTED = "CLOSED_OTHER_ACCEPTED"
    EXPIRED = "EXPIRED"


class ProviderQuoteStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    DECLINED = "DECLINED"


class QuoteMessageType(enum.Enum):
    SEEKER_REPLY = "SEEKER_REPLY"
    PROVIDER_REPLY = "PROVIDER_REPLY"
    SYSTEM = "SYSTEM"


class MessageType(enum.Enum):
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"


class MembershipStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class DisputeStatus(enum.Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


# ====================
# USER
# ====================

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    # --------------------
    # BASIC INFO
    # --------------------
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, index=True, nullable=False)
    phone = db.Column(db.String(30), unique=True, index=True, nullable=True)

    password_hash = db.Column(db.String(128), nullable=False)

    role = db.Column(
        db.Enum(RoleEnum, name="roleenum", create_type=False),
        nullable=False,
        default=RoleEnum.SEEKER,
    )

    is_provider_profile_complete = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )
    
    is_email_verified = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    is_accepting_bookings = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    created_at = db.Column(db.DateTime, default=_utc_now)

    # --------------------
    # TRUST / GAMIFICATION
    # --------------------
    trust_score = db.Column(db.Integer, default=0, nullable=False)
    completed_jobs = db.Column(db.Integer, default=0, nullable=False)
    badges = db.Column(JSON, default=list, nullable=True)
    avg_response_seconds = db.Column(db.Integer, default=0)

    # --------------------
    # PROFILE
    # --------------------
    bio = db.Column(db.Text, nullable=True)

    location = db.Column(db.String(255), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    rating = db.Column(db.Float, default=0.0)
    gstin = db.Column(db.String(32), nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    timezone = db.Column(db.String(64), nullable=False, default="UTC")
    service_areas = db.Column(JSON, default=list, nullable=False)
    portfolio_images = db.Column(JSON, default=list, nullable=False)
    certifications = db.Column(JSON, default=list, nullable=False)
    specialties = db.Column(JSON, default=list, nullable=False)
    cancellation_cutoff_hours = db.Column(db.Integer, nullable=False, default=2)
    cancellation_fee_pct = db.Column(db.Integer, nullable=False, default=20)
    cancellation_policy_text = db.Column(db.Text, nullable=True)

    # --------------------
    # VERIFICATION (SINGLE SOURCE OF TRUTH)
    # --------------------
    verification_status = db.Column(
        db.Enum(
            VerificationStatus,
            name="verificationstatus",
            create_type=False,
        ),
        nullable=False,
        default=VerificationStatus.pending,
    )

    is_verified = db.Column(db.Boolean, default=False, nullable=False)

    # --------------------
    # DOCUMENT
    # --------------------
    document_filename = db.Column(db.String(512), nullable=True)
    document_type = db.Column(db.String(100), nullable=True)

    # --------------------
    # VERIFICATION FLOW FLAGS
    # --------------------
    requires_selfie = db.Column(db.Boolean, default=False, nullable=False)


    # --------------------
    # SELFIE (OPTION B FALLBACK)
    # --------------------
    selfie_filename = db.Column(db.String(512), nullable=True)

    # --------------------
    # FACE VIDEO
    # --------------------
    verification_video_filename = db.Column(db.String(512), nullable=True)

    verification_notes = db.Column(db.Text, nullable=True)

    kyc_status = db.Column(
        db.Enum(KycStatus, name="kycstatus", create_type=False),
        nullable=False,
        default=KycStatus.pending,
    )
    kyc_submitted_at = db.Column(db.DateTime, nullable=True)
    kyc_approved_at = db.Column(db.DateTime, nullable=True)
    kyc_rejected_at = db.Column(db.DateTime, nullable=True)
    kyc_rejection_reason = db.Column(db.Text, nullable=True)
    kyc_approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # --------------------
    # REFERRAL & WALLET
    # --------------------
    referral_code = db.Column(db.String(20), unique=True, index=True, nullable=True)
    referred_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    wallet_balance = db.Column(db.Numeric(10, 2), default=0.00)

    referrer = db.relationship(
        "User",
        remote_side=[id],
        foreign_keys=[referred_by_id],
        backref="referrals",
        uselist=False,
    )

    # --------------------
    # FEATURED / BOOST
    # --------------------
    is_featured = db.Column(db.Boolean, default=False)
    featured_until = db.Column(db.DateTime, nullable=True)
    boost_until = db.Column(db.DateTime, nullable=True)

    # --------------------
    # STRIPE CONNECT / PAYOUTS
    # --------------------
    stripe_account_id = db.Column(db.String(120), unique=True, index=True, nullable=True)
    stripe_onboarding_complete = db.Column(db.Boolean, default=False, nullable=False)

    # --------------------
    # RELATIONSHIPS
    # --------------------
    profile_photo_url = db.Column(db.String(512), nullable=True)

    skills = db.relationship(
        "Skill",
        back_populates="provider",
        cascade="all, delete-orphan",
    )

    reviews_received = db.relationship(
        "Review",
        backref="provider",
        cascade="all, delete-orphan",
        foreign_keys="Review.provider_id",
    )

    messages = db.relationship(
        "Message",
        back_populates="sender",
        cascade="all, delete-orphan",
    )
    kyc_documents = db.relationship(
        "KycDocument",
        back_populates="provider",
        cascade="all, delete-orphan",
        foreign_keys="KycDocument.provider_id",
    )
    approved_kyc_providers = db.relationship(
        "User",
        foreign_keys=[kyc_approved_by],
        backref="kyc_approvals",
        remote_side=[id],
    )

    # --------------------
    # AUTH METHODS
    # --------------------
    def set_password(self, password, bcrypt):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password, bcrypt):
        return bcrypt.check_password_hash(self.password_hash, password)


# ====================
# SKILL
# ====================

class Skill(db.Model):
    __tablename__ = "skills"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    currency = db.Column(db.String(10), default="INR")

    location = db.Column(db.String(255), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    tags = db.Column(db.String(255), nullable=True)
    availability = db.Column(JSON, nullable=True)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utc_now)

    provider = db.relationship("User", back_populates="skills")


# ====================
# BOOKING
# ====================

class Booking(db.Model):
    __tablename__ = "bookings"

    id = db.Column(db.Integer, primary_key=True)

    seeker_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=True)
    job_post_id = db.Column(db.Integer, db.ForeignKey("job_posts.id"), nullable=True)

    scheduled_at = db.Column(db.DateTime, nullable=False)
    original_scheduled_at = db.Column(db.DateTime, nullable=True)
    duration_minutes = db.Column(db.Integer, default=60)

    price = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(10), default="INR")

    status = db.Column(
        db.Enum(BookingStatus, name="bookingstatus", create_type=False),
        nullable=False,
        default=BookingStatus.PENDING,
    )

    payment_status = db.Column(
        db.Enum(PaymentStatus, name="paymentstatus", create_type=False),
        nullable=False,
        default=PaymentStatus.NONE,
    )

    payment_provider = db.Column(db.String(32), nullable=True)
    payment_intent_id = db.Column(db.String(100), nullable=True)
    payment_checkout_session_id = db.Column(db.String(128), nullable=True)
    payment_ref = db.Column(db.String(100), nullable=True)
    quote_request_id = db.Column(db.Integer, db.ForeignKey("quote_requests.id"), nullable=True)
    invoice_number = db.Column(db.String(50), nullable=True)
    invoice_url = db.Column(db.String(1024), nullable=True)
    invoice_generated_at = db.Column(db.DateTime, nullable=True)
    gst_amount = db.Column(db.Numeric(10, 2), default=0.00)
    service_amount = db.Column(db.Numeric(10, 2), default=0.00)
    provider_notes = db.Column(db.Text, nullable=True)
    refund_status = db.Column(
        db.Enum(RefundStatus, name="refundstatus", create_type=False),
        nullable=False,
        default=RefundStatus.NONE,
    )

    # 💰 Monetization
    platform_fee_pct = db.Column(db.Numeric(5, 2), default=10.00)
    platform_fee_amount = db.Column(db.Numeric(10, 2), default=0.00)
    worker_earnings = db.Column(db.Numeric(10, 2), default=0.00)
    referral_credit_used = db.Column(db.Numeric(10, 2), default=0.00)
    promo_discount_amount = db.Column(db.Numeric(10, 2), default=0.00)
    amount_payable = db.Column(db.Numeric(10, 2), default=0.00)

    # 📍 Tracking
    worker_latitude = db.Column(db.Float, nullable=True)
    worker_longitude = db.Column(db.Float, nullable=True)
    worker_last_seen_at = db.Column(db.DateTime, nullable=True)
    distance_km = db.Column(db.Float, nullable=True)
    cancellation_reason = db.Column(db.String(255), nullable=True)

    # 💵 Cash Payment
    payment_method = db.Column(db.String(32), default="online")
    cash_collected_at = db.Column(db.DateTime, nullable=True)
    cash_collected_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # 💸 Refund Details
    refund_amount = db.Column(db.Numeric(10, 2), default=0.00)
    refund_ref = db.Column(db.String(100), nullable=True)
    refund_initiated_at = db.Column(db.DateTime, nullable=True)
    refund_completed_at = db.Column(db.DateTime, nullable=True)
    refund_reason = db.Column(db.String(255), nullable=True)

    # 🧾 GST Breakdown
    cgst_amount = db.Column(db.Numeric(10, 2), default=0.00)
    sgst_amount = db.Column(db.Numeric(10, 2), default=0.00)
    igst_amount = db.Column(db.Numeric(10, 2), default=0.00)
    sac_code = db.Column(db.String(20), default="998599")

    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(
        db.DateTime,
        default=_utc_now,
        onupdate=_utc_now,
    )

    seeker = db.relationship("User", foreign_keys=[seeker_id])
    provider = db.relationship("User", foreign_keys=[provider_id])
    skill = db.relationship("Skill", foreign_keys=[skill_id])


# ====================
# MESSAGE (CHAT)
# ====================

class Message(db.Model):
    __tablename__ = "messages"
    __table_args__ = (
        db.Index("ix_messages_room_created", "room", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(255), index=True, nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    content = db.Column(db.Text, nullable=False)
    message_type = db.Column(
        db.Enum(MessageType, name="messagetype", values_callable=lambda obj: [e.value for e in obj], create_type=False),
        nullable=False,
        default=MessageType.TEXT,
    )
    created_at = db.Column(db.DateTime, default=_utc_now)
    delivered_at = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)

    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)

    sender = db.relationship("User", back_populates="messages")


class Review(db.Model):
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False, unique=True, index=True)
    seeker_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    rating = db.Column(db.Float, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    punctuality_rating = db.Column(db.Float, nullable=True)
    quality_rating = db.Column(db.Float, nullable=True)
    communication_rating = db.Column(db.Float, nullable=True)
    value_rating = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)
    provider_reply = db.Column(db.Text, nullable=True)
    provider_replied_at = db.Column(db.DateTime, nullable=True)


class FavoriteProvider(db.Model):
    __tablename__ = "favorite_providers"
    __table_args__ = (
        db.UniqueConstraint("seeker_id", "provider_id", name="uq_favorite_provider"),
    )

    id = db.Column(db.Integer, primary_key=True)
    seeker_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now, nullable=True)


class KycDocument(db.Model):
    __tablename__ = "kyc_documents"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    doc_type = db.Column(db.String(50), nullable=False)
    file_url = db.Column(db.String(1024), nullable=False)
    created_at = db.Column(db.DateTime, default=_utc_now, nullable=False)

    provider = db.relationship("User", back_populates="kyc_documents", foreign_keys=[provider_id])


# ====================
# WEBHOOK EVENT (IDEMPOTENCY)
# ====================

class WebhookEvent(db.Model):
    __tablename__ = "webhook_events"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(128), unique=True, index=True, nullable=False)
    provider = db.Column(db.String(32), nullable=False)
    processed_at = db.Column(db.DateTime, default=_utc_now, nullable=False)


class WalletTopup(db.Model):
    __tablename__ = "wallet_topups"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    provider = db.Column(db.String(32), nullable=False, default="razorpay")
    topup_reference = db.Column(db.String(128), nullable=False, unique=True, index=True)
    gateway_order_id = db.Column(db.String(128), nullable=True, unique=True, index=True)
    gateway_payment_id = db.Column(db.String(128), nullable=True, unique=True, index=True)
    wallet_transaction_id = db.Column(db.Integer, db.ForeignKey("wallet_transactions.id"), nullable=True, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    currency = db.Column(db.String(10), nullable=False, default="INR")
    status = db.Column(db.String(24), nullable=False, default="PENDING", index=True)
    failure_reason = db.Column(db.String(255), nullable=True)
    metadata_json = db.Column("metadata", JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, default=_utc_now, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    failed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", foreign_keys=[user_id], backref="wallet_topups")
    wallet_transaction = db.relationship("WalletTransaction", foreign_keys=[wallet_transaction_id], backref="topup_records")


class AccountingEntry(db.Model):
    __tablename__ = "accounting_entries"
    __table_args__ = (
        db.Index("ix_accounting_entries_group_account", "entry_group", "account_code"),
    )

    id = db.Column(db.Integer, primary_key=True)
    entry_group = db.Column(db.String(128), nullable=False, index=True)
    account_code = db.Column(db.String(64), nullable=False, index=True)
    direction = db.Column(db.String(10), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(10), nullable=False, default="INR")
    reference_type = db.Column(db.String(32), nullable=True, index=True)
    reference_id = db.Column(db.Integer, nullable=True, index=True)
    description = db.Column(db.String(255), nullable=False)
    metadata_json = db.Column("metadata", JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, default=_utc_now, nullable=False, index=True)


class ConsentRecord(db.Model):
    __tablename__ = "consent_records"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    consent_type = db.Column(db.String(64), nullable=False)
    version = db.Column(db.String(32), nullable=False)
    accepted_at = db.Column(db.DateTime, default=_utc_now, nullable=False)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)

    user = db.relationship("User", backref="consent_records", foreign_keys=[user_id])


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(80), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    actor_role = db.Column(db.String(20), nullable=True)
    target_type = db.Column(db.String(50), nullable=True, index=True)
    target_id = db.Column(db.Integer, nullable=True, index=True)
    metadata_json = db.Column("metadata", JSON, nullable=False, default=dict)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now, nullable=False, index=True)

    actor = db.relationship("User", foreign_keys=[actor_id])

    @classmethod
    def record(
        cls,
        event_type,
        actor_id=None,
        actor_role=None,
        target_type=None,
        target_id=None,
        metadata=None,
        request=None,
    ):
        entry = cls(
            event_type=event_type,
            actor_id=actor_id,
            actor_role=actor_role,
            target_type=target_type,
            target_id=target_id,
            metadata_json=metadata or {},
            ip_address=request.headers.get("X-Forwarded-For", request.remote_addr) if request else None,
        )
        db.session.add(entry)
        return entry


class PromoCode(db.Model):
    __tablename__ = "promo_codes"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, index=True, nullable=False)
    title = db.Column(db.String(140), nullable=False)
    description = db.Column(db.Text, nullable=True)
    discount_type = db.Column(
        db.Enum(PromoDiscountType, name="promodiscounttype", create_type=False),
        nullable=False,
        default=PromoDiscountType.PERCENT,
    )
    discount_value = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    max_discount_amount = db.Column(db.Numeric(10, 2), nullable=True)
    min_order_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    active = db.Column(db.Boolean, nullable=False, default=True)
    usage_limit = db.Column(db.Integer, nullable=True)
    used_count = db.Column(db.Integer, nullable=False, default=0)
    city = db.Column(db.String(120), nullable=True)
    first_booking_only = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=_utc_now)
    expires_at = db.Column(db.DateTime, nullable=True)


class PromoRedemption(db.Model):
    __tablename__ = "promo_redemptions"

    id = db.Column(db.Integer, primary_key=True)
    promo_code_id = db.Column(db.Integer, db.ForeignKey("promo_codes.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=True, index=True)
    discount_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    created_at = db.Column(db.DateTime, default=_utc_now)

    promo_code = db.relationship("PromoCode", backref="redemptions")
    user = db.relationship("User", backref="promo_redemptions", foreign_keys=[user_id])
    booking = db.relationship("Booking", backref="promo_redemptions", foreign_keys=[booking_id])


class ReferralReward(db.Model):
    __tablename__ = "referral_rewards"

    id = db.Column(db.Integer, primary_key=True)
    referrer_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    referred_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=True, index=True)
    status = db.Column(
        db.Enum(ReferralRewardStatus, name="referralrewardstatus", create_type=False),
        nullable=False,
        default=ReferralRewardStatus.PENDING,
    )
    reward_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now, index=True)
    paid_at = db.Column(db.DateTime, nullable=True)

    referrer = db.relationship("User", foreign_keys=[referrer_user_id], backref="referral_rewards_sent")
    referred_user = db.relationship("User", foreign_keys=[referred_user_id], backref="referral_rewards_received")
    booking = db.relationship("Booking", foreign_keys=[booking_id], backref="referral_rewards")


class QuoteRequest(db.Model):
    __tablename__ = "quote_requests"

    id = db.Column(db.Integer, primary_key=True)
    seeker_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=True)
    service_title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    address_text = db.Column(db.String(255), nullable=True)
    preferred_window_start = db.Column(db.DateTime, nullable=True)
    preferred_window_end = db.Column(db.DateTime, nullable=True)
    budget_min = db.Column(db.Numeric(10, 2), nullable=True)
    budget_max = db.Column(db.Numeric(10, 2), nullable=True)
    attachments = db.Column(JSON, default=list, nullable=False)
    status = db.Column(
        db.Enum(QuoteRequestStatus, name="quoterequeststatus", create_type=False),
        nullable=False,
        default=QuoteRequestStatus.OPEN,
    )
    accepted_provider_quote_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)
    deleted_at = db.Column(db.DateTime, nullable=True)

    seeker = db.relationship("User", foreign_keys=[seeker_id], backref="quote_requests")
    skill = db.relationship("Skill", foreign_keys=[skill_id], backref="quote_requests")


class QuoteRequestProviderTarget(db.Model):
    __tablename__ = "quote_request_provider_targets"

    id = db.Column(db.Integer, primary_key=True)
    quote_request_id = db.Column(db.Integer, db.ForeignKey("quote_requests.id"), nullable=False, index=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    target_status = db.Column(
        db.Enum(QuoteTargetStatus, name="quotetargetstatus", create_type=False),
        nullable=False,
        default=QuoteTargetStatus.PENDING_RESPONSE,
    )
    first_notified_at = db.Column(db.DateTime, nullable=True)
    response_due_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now)

    quote_request = db.relationship("QuoteRequest", foreign_keys=[quote_request_id], backref="targets")
    provider = db.relationship("User", foreign_keys=[provider_id], backref="quote_targets")


class ProviderQuote(db.Model):
    __tablename__ = "provider_quotes"

    id = db.Column(db.Integer, primary_key=True)
    quote_request_id = db.Column(db.Integer, db.ForeignKey("quote_requests.id"), nullable=False, index=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    revision_number = db.Column(db.Integer, nullable=False, default=1)
    currency = db.Column(db.String(10), nullable=False, default="INR")
    total_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    line_items = db.Column(JSON, default=list, nullable=False)
    estimated_duration_minutes = db.Column(db.Integer, nullable=False, default=60)
    earliest_available_at = db.Column(db.DateTime, nullable=True)
    note = db.Column(db.Text, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(
        db.Enum(ProviderQuoteStatus, name="providerquotestatus", create_type=False),
        nullable=False,
        default=ProviderQuoteStatus.ACTIVE,
    )
    created_at = db.Column(db.DateTime, default=_utc_now)

    quote_request = db.relationship("QuoteRequest", foreign_keys=[quote_request_id], backref="quotes")
    provider = db.relationship("User", foreign_keys=[provider_id], backref="provider_quotes")


class QuoteMessage(db.Model):
    __tablename__ = "quote_messages"

    id = db.Column(db.Integer, primary_key=True)
    quote_request_id = db.Column(db.Integer, db.ForeignKey("quote_requests.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    message_type = db.Column(
        db.Enum(QuoteMessageType, name="quotemessagetype", create_type=False),
        nullable=False,
        default=QuoteMessageType.SYSTEM,
    )
    body = db.Column(db.Text, nullable=False)
    attachments = db.Column(JSON, default=list, nullable=False)
    created_at = db.Column(db.DateTime, default=_utc_now)

    quote_request = db.relationship("QuoteRequest", foreign_keys=[quote_request_id], backref="messages")
    sender = db.relationship("User", foreign_keys=[sender_id], backref="quote_messages")


class SubscriptionPlan(db.Model):
    __tablename__ = "subscription_plans"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(40), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    audience = db.Column(db.String(20), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    billing_period = db.Column(db.String(20), nullable=False, default="monthly")
    benefits = db.Column(JSON, default=list, nullable=False)
    priority_support = db.Column(db.Boolean, nullable=False, default=False)
    reduced_fee_pct = db.Column(db.Numeric(5, 2), nullable=True)
    loyalty_credit = db.Column(db.Numeric(10, 2), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=_utc_now)


class UserSubscription(db.Model):
    __tablename__ = "user_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("subscription_plans.id"), nullable=False, index=True)
    status = db.Column(
        db.Enum(MembershipStatus, name="membershipstatus", create_type=False),
        nullable=False,
        default=MembershipStatus.ACTIVE,
    )
    started_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now)

    user = db.relationship("User", foreign_keys=[user_id], backref="subscriptions")
    plan = db.relationship("SubscriptionPlan", foreign_keys=[plan_id], backref="subscriptions")


class BookingDispute(db.Model):
    __tablename__ = "booking_disputes"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False, index=True)
    opened_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    assigned_admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    status = db.Column(
        db.Enum(DisputeStatus, name="disputestatus", create_type=False),
        nullable=False,
        default=DisputeStatus.OPEN,
    )
    category = db.Column(db.String(64), nullable=False)
    description = db.Column(db.Text, nullable=False)
    evidence = db.Column(JSON, default=list, nullable=False)
    resolution_notes = db.Column(db.Text, nullable=True)
    refund_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    created_at = db.Column(db.DateTime, default=_utc_now, index=True)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)

    booking = db.relationship("Booking", foreign_keys=[booking_id], backref="disputes")
    opened_by = db.relationship("User", foreign_keys=[opened_by_user_id], backref="opened_disputes")
    assigned_admin = db.relationship("User", foreign_keys=[assigned_admin_id], backref="assigned_disputes")


class FraudFlag(db.Model):
    __tablename__ = "fraud_flags"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=True, index=True)
    severity = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=_utc_now, index=True)

    user = db.relationship("User", foreign_keys=[user_id], backref="fraud_flags")
    booking = db.relationship("Booking", foreign_keys=[booking_id], backref="fraud_flags")


class SearchQueryLog(db.Model):
    __tablename__ = "search_query_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    session_id = db.Column(db.String(64), nullable=False, index=True)
    query_text = db.Column(db.String(140), nullable=True, index=True)
    filters = db.Column(JSON, default=dict, nullable=False)
    result_count = db.Column(db.Integer, nullable=False, default=0)
    clicked_provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    booked_provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=_utc_now, index=True)


class AIJobIntakeLog(db.Model):
    __tablename__ = "ai_job_intake_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    raw_text = db.Column(db.Text, nullable=False)
    parsed_payload = db.Column(JSON, default=dict, nullable=False)
    confidence = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=_utc_now)

    user = db.relationship("User", foreign_keys=[user_id], backref="ai_job_intake_logs")


class ChatInsight(db.Model):
    __tablename__ = "chat_insights"

    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(255), nullable=False, unique=True, index=True)
    summary = db.Column(db.Text, nullable=True)
    extracted_address = db.Column(db.String(255), nullable=True)
    extracted_time = db.Column(db.String(120), nullable=True)
    quick_replies = db.Column(JSON, default=list, nullable=False)
    pinned_summary = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)


class ProviderInstantBookSetting(db.Model):
    __tablename__ = "provider_instant_book_settings"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True)
    instant_book_enabled = db.Column(db.Boolean, nullable=False, default=False)
    slot_duration_minutes = db.Column(db.Integer, nullable=False, default=60)
    slot_hold_minutes = db.Column(db.Integer, nullable=False, default=5)
    enabled_skill_ids = db.Column(JSON, default=list, nullable=False)
    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)

    provider = db.relationship("User", foreign_keys=[provider_id], backref="instant_book_setting")


class ProviderAvailabilityRule(db.Model):
    __tablename__ = "provider_availability_rules"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=True, index=True)
    weekday = db.Column(db.Integer, nullable=False, index=True)
    start_minute_local = db.Column(db.Integer, nullable=False)
    end_minute_local = db.Column(db.Integer, nullable=False)
    buffer_before_minutes = db.Column(db.Integer, nullable=False, default=0)
    buffer_after_minutes = db.Column(db.Integer, nullable=False, default=0)
    min_notice_minutes = db.Column(db.Integer, nullable=False, default=60)
    max_advance_days = db.Column(db.Integer, nullable=False, default=30)
    enabled = db.Column(db.Boolean, nullable=False, default=True, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)

    provider = db.relationship("User", foreign_keys=[provider_id], backref="availability_rules")
    skill = db.relationship("Skill", foreign_keys=[skill_id], backref="availability_rules")


class ProviderBlackout(db.Model):
    __tablename__ = "provider_blackouts"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    start_at = db.Column(db.DateTime, nullable=False, index=True)
    end_at = db.Column(db.DateTime, nullable=False, index=True)
    reason_code = db.Column(db.String(32), nullable=False, default="OTHER")
    note = db.Column(db.String(255), nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)

    provider = db.relationship("User", foreign_keys=[provider_id], backref="availability_blackouts")


class BookingChangePolicy(db.Model):
    __tablename__ = "booking_change_policies"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, unique=True, index=True)
    free_cancel_until_hours = db.Column(db.Integer, nullable=False, default=24)
    partial_fee_until_hours = db.Column(db.Integer, nullable=False, default=2)
    partial_fee_percent = db.Column(db.Numeric(5, 2), nullable=False, default=10.00)
    partial_fee_min_amount = db.Column(db.Numeric(10, 2), nullable=False, default=100.00)
    late_fee_percent = db.Column(db.Numeric(5, 2), nullable=False, default=25.00)
    late_fee_min_amount = db.Column(db.Numeric(10, 2), nullable=False, default=250.00)
    max_reschedules = db.Column(db.Integer, nullable=False, default=2)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)

    provider = db.relationship("User", foreign_keys=[provider_id], backref="booking_change_policy")


class BookingTimelineEvent(db.Model):
    __tablename__ = "booking_timeline_events"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False, index=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    event_type = db.Column(db.String(64), nullable=False, index=True)
    payload = db.Column(JSON, default=dict, nullable=False)
    created_at = db.Column(db.DateTime, default=_utc_now, index=True)

    booking = db.relationship("Booking", foreign_keys=[booking_id], backref="timeline_events")
    actor = db.relationship("User", foreign_keys=[actor_user_id], backref="booking_timeline_actions")


class NotificationPreference(db.Model):
    __tablename__ = "notification_preferences"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True)
    push_enabled = db.Column(db.Boolean, nullable=False, default=True)
    email_enabled = db.Column(db.Boolean, nullable=False, default=True)
    whatsapp_enabled = db.Column(db.Boolean, nullable=False, default=False)
    category_channels = db.Column(JSON, default=dict, nullable=False)
    quiet_hours_enabled = db.Column(db.Boolean, nullable=False, default=False)
    quiet_start_local = db.Column(db.String(5), nullable=True)
    quiet_end_local = db.Column(db.String(5), nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)

    user = db.relationship("User", foreign_keys=[user_id], backref="notification_preference")


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    recipient_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    category = db.Column(
        db.Enum(NotificationCategory, name="notificationcategory", create_type=False),
        nullable=False,
        default=NotificationCategory.BOOKING_UPDATE,
    )
    priority = db.Column(
        db.Enum(NotificationPriority, name="notificationpriority", create_type=False),
        nullable=False,
        default=NotificationPriority.NORMAL,
    )
    title = db.Column(db.String(140), nullable=False)
    body = db.Column(db.Text, nullable=False)
    deep_link = db.Column(db.String(255), nullable=True)
    entity_type = db.Column(db.String(64), nullable=True)
    entity_id = db.Column(db.Integer, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=_utc_now, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)

    recipient = db.relationship("User", foreign_keys=[recipient_user_id], backref="notifications")

    __table_args__ = (
        db.Index(
            "idx_notifications_user_read_created",
            "recipient_user_id",
            "read_at",
            "deleted_at",
            "created_at",
        ),
    )


class NotificationDelivery(db.Model):
    __tablename__ = "notification_deliveries"

    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, db.ForeignKey("notifications.id"), nullable=False, index=True)
    channel = db.Column(
        db.Enum(NotificationChannel, name="notificationchannel", create_type=False),
        nullable=False,
    )
    status = db.Column(
        db.Enum(NotificationDeliveryStatus, name="notificationdeliverystatus", create_type=False),
        nullable=False,
        default=NotificationDeliveryStatus.QUEUED,
    )
    template_key = db.Column(db.String(64), nullable=False, default="generic")
    template_version = db.Column(db.Integer, nullable=False, default=1)
    provider_message_id = db.Column(db.String(128), nullable=True)
    error_code = db.Column(db.String(64), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    retry_count = db.Column(db.Integer, nullable=False, default=0)
    payload = db.Column(JSON, default=dict, nullable=False)
    attempted_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)

    notification = db.relationship("Notification", foreign_keys=[notification_id], backref="deliveries")


def generate_deleted_email():
    return f"deleted-{uuid.uuid4().hex}@deleted.local"


class TokenBlocklist(db.Model):
    __tablename__ = "token_blocklist"
    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(36), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=_utc_now, nullable=False)

# ====================
# JOB POSTS & PROPOSALS
# ====================

class JobPost(db.Model):
    __tablename__ = "job_posts"

    id = db.Column(db.Integer, primary_key=True)
    seeker_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    budget_min = db.Column(db.Numeric(10, 2), nullable=True)
    budget_max = db.Column(db.Numeric(10, 2), nullable=True)
    currency = db.Column(db.String(10), default="INR")
    
    location_text = db.Column(db.String(255), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    
    scheduled_for = db.Column(db.DateTime, nullable=True)
    
    status = db.Column(
        db.Enum(JobPostStatus, name="jobpoststatus", create_type=False),
        nullable=False,
        default=JobPostStatus.OPEN,
    )
    
    selected_provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    selected_at = db.Column(db.DateTime, nullable=True)
    
    provider_found_visible_until = db.Column(db.DateTime, nullable=True)
    cancel_allowed_until = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)
    closed_at = db.Column(db.DateTime, nullable=True)

    seeker = db.relationship("User", foreign_keys=[seeker_id], backref="job_posts")
    selected_provider = db.relationship("User", foreign_keys=[selected_provider_id])
    proposals = db.relationship("JobProposal", back_populates="job_post", cascade="all, delete-orphan")


class JobProposal(db.Model):
    __tablename__ = "job_proposals"

    id = db.Column(db.Integer, primary_key=True)
    job_post_id = db.Column(db.Integer, db.ForeignKey("job_posts.id"), nullable=False)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    
    cover_message = db.Column(db.Text, nullable=True)
    quoted_amount = db.Column(db.Numeric(10, 2), nullable=False)
    estimated_duration_minutes = db.Column(db.Integer, default=60)
    available_from = db.Column(db.DateTime, nullable=True)
    
    status = db.Column(
        db.Enum(JobProposalStatus, name="jobproposalstatus", create_type=False),
        nullable=False,
        default=JobProposalStatus.ACTIVE,
    )
    
    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)

    job_post = db.relationship("JobPost", back_populates="proposals")
    provider = db.relationship("User", backref="job_proposals")

    __table_args__ = (
        db.UniqueConstraint("job_post_id", "provider_id", name="uq_job_proposal_provider"),
    )


# ====================
# WALLET TRANSACTIONS
# ====================

class WalletTransaction(db.Model):
    __tablename__ = "wallet_transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    txn_type = db.Column(
        db.Enum(WalletTransactionType, name="wallettransactiontype", create_type=False),
        nullable=False,
    )
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    balance_after = db.Column(db.Numeric(10, 2), nullable=False)
    reference_type = db.Column(db.String(32), nullable=True)
    reference_id = db.Column(db.Integer, nullable=True)
    description = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=_utc_now, index=True)

    user = db.relationship("User", foreign_keys=[user_id], backref="wallet_transactions")
