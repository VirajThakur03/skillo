# app/models.py
from datetime import datetime
import enum
from .extensions import db


# ====================
# ENUMS (MATCH DB)
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


class VerificationStatus(enum.Enum):
    pending = "pending"
    verified = "verified"
    rejected = "rejected"


# ====================
# USER
# ====================

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, index=True, nullable=False)
    phone = db.Column(db.String(30), unique=True, index=True, nullable=True)

    password_hash = db.Column(db.String(128), nullable=False)

    role = db.Column(
        db.Enum(
            RoleEnum,
            name="roleenum",
            # values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=RoleEnum.SEEKER,
    )

    bio = db.Column(db.Text, nullable=True)

    # 📍 Location
    location = db.Column(db.String(255), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    rating = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ✅ Document verification
    verification_status = db.Column(
        db.Enum(
            VerificationStatus,
            name="verificationstatus",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=VerificationStatus.pending,
    )

    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    document_filename = db.Column(db.String(512), nullable=True)
    document_type = db.Column(db.String(100), nullable=True)
    verification_notes = db.Column(db.Text, nullable=True)

    # ✅ Video verification
    verification_video_filename = db.Column(db.String(512), nullable=True)
    verification_video_status = db.Column(
        db.Enum(
            VerificationStatus,
            name="verificationstatus",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=VerificationStatus.pending,
    )

    # 💰 Referral & Wallet
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

    # 🏆 Gamification
    badges = db.Column(db.JSON, nullable=True)
    completed_jobs = db.Column(db.Integer, default=0)
    avg_response_seconds = db.Column(db.Integer, default=0)

    # 🚀 Featured / Boost
    is_featured = db.Column(db.Boolean, default=False)
    featured_until = db.Column(db.DateTime, nullable=True)
    boost_until = db.Column(db.DateTime, nullable=True)

    # Relationships
    skills = db.relationship(
        "Skill",
        back_populates="provider",
        cascade="all, delete-orphan",
    )

    messages = db.relationship(
        "Message",
        back_populates="sender",
        cascade="all, delete-orphan",
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
    availability = db.Column(db.JSON, nullable=True)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    provider = db.relationship("User", back_populates="skills")


# ====================
# BOOKING
# ====================

class Booking(db.Model):
    __tablename__ = "bookings"

    id = db.Column(db.Integer, primary_key=True)

    seeker_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=False)

    scheduled_at = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer, default=60)

    price = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(10), default="INR")

    status = db.Column(
        db.Enum(
            BookingStatus,
            name="bookingstatus",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=BookingStatus.PENDING,
    )

    payment_status = db.Column(
        db.Enum(
            PaymentStatus,
            name="paymentstatus",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=PaymentStatus.NONE,
    )

    payment_intent_id = db.Column(db.String(100), nullable=True)
    payment_ref = db.Column(db.String(100), nullable=True)

    # 💰 Monetization
    platform_fee_pct = db.Column(db.Numeric(5, 2), default=5.00)
    platform_fee_amount = db.Column(db.Numeric(10, 2), default=0.00)
    worker_earnings = db.Column(db.Numeric(10, 2), default=0.00)
    referral_credit_used = db.Column(db.Numeric(10, 2), default=0.00)

    # 📍 Tracking
    worker_latitude = db.Column(db.Float, nullable=True)
    worker_longitude = db.Column(db.Float, nullable=True)
    worker_last_seen_at = db.Column(db.DateTime, nullable=True)
    distance_km = db.Column(db.Float, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    seeker = db.relationship("User", foreign_keys=[seeker_id])
    provider = db.relationship("User", foreign_keys=[provider_id])
    skill = db.relationship("Skill", foreign_keys=[skill_id])


# ====================
# MESSAGE (CHAT)
# ====================

class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(255), index=True, nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship("User", back_populates="messages")
