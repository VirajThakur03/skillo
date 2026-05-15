from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app import create_app
from app.extensions import bcrypt, db
from app.models import (
    Booking,
    BookingStatus,
    KycDocument,
    KycStatus,
    Message,
    PaymentStatus,
    RoleEnum,
    Skill,
    User,
    VerificationStatus,
)


app = create_app()


def upsert_user(*, email, defaults):
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(email=email, **defaults)
        user.set_password("password123", bcrypt)
        db.session.add(user)
    else:
        for key, value in defaults.items():
            setattr(user, key, value)
    return user


def upsert_skill(*, provider, title, price, location, description):
    skill = Skill.query.filter_by(provider_id=provider.id, title=title).first()
    if not skill:
        skill = Skill(provider_id=provider.id, title=title)
        db.session.add(skill)
    skill.description = description
    skill.price = Decimal(price)
    skill.currency = "INR"
    skill.location = location
    skill.is_active = True
    return skill


def upsert_booking(*, seeker, provider, skill, status, payment_status, offset_days):
    booking = Booking.query.filter_by(
        seeker_id=seeker.id,
        provider_id=provider.id,
        skill_id=skill.id,
        status=status,
    ).first()
    if not booking:
        booking = Booking(
            seeker_id=seeker.id,
            provider_id=provider.id,
            skill_id=skill.id,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=offset_days),
            duration_minutes=60,
            price=skill.price,
            currency="INR",
            status=status,
            payment_status=payment_status,
            platform_fee_pct=Decimal("5.00"),
            platform_fee_amount=Decimal(skill.price) * Decimal("0.05"),
            worker_earnings=Decimal(skill.price) * Decimal("0.95"),
        )
        db.session.add(booking)
    return booking


def ensure_kyc_doc(provider, doc_type):
    existing = KycDocument.query.filter_by(provider_id=provider.id, doc_type=doc_type).first()
    if not existing:
        db.session.add(
            KycDocument(
                provider_id=provider.id,
                doc_type=doc_type,
                file_url=f"seed/kyc/{provider.id}/{doc_type}.jpg",
            )
        )


with app.app_context():
    seeker1 = upsert_user(
        email="seeker1@test.com",
        defaults={
            "name": "Aarav Seeker",
            "phone": "+919999000001",
            "role": RoleEnum.SEEKER,
            "location": "Koregaon Park, Pune",
            "latitude": 18.5362,
            "longitude": 73.8930,
        },
    )
    seeker2 = upsert_user(
        email="seeker2@test.com",
        defaults={
            "name": "Mira Seeker",
            "phone": "+919999000002",
            "role": RoleEnum.SEEKER,
            "location": "Baner, Pune",
            "latitude": 18.5590,
            "longitude": 73.7868,
        },
    )
    provider_plumber = upsert_user(
        email="provider.plumber@test.com",
        defaults={
            "name": "Ravi Plumber",
            "phone": "+919999000010",
            "role": RoleEnum.PROVIDER,
            "location": "Koregaon Park, Pune",
            "latitude": 18.5365,
            "longitude": 73.8934,
            "verification_status": VerificationStatus.completed,
            "is_verified": True,
            "kyc_status": KycStatus.approved,
            "is_provider_profile_complete": True,
            "gstin": "27ABCDE1234F1Z5",
            "rating": 4.8,
        },
    )
    provider_cleaner = upsert_user(
        email="provider.cleaner@test.com",
        defaults={
            "name": "Nisha Cleaner",
            "phone": "+919999000011",
            "role": RoleEnum.PROVIDER,
            "location": "Aundh, Pune",
            "latitude": 18.5610,
            "longitude": 73.8079,
            "verification_status": VerificationStatus.completed,
            "is_verified": True,
            "kyc_status": KycStatus.approved,
            "is_provider_profile_complete": True,
            "rating": 4.6,
        },
    )
    provider_unverified = upsert_user(
        email="provider.unverified@test.com",
        defaults={
            "name": "Pending Provider",
            "phone": "+919999000012",
            "role": RoleEnum.PROVIDER,
            "location": "Pimpri, Pune",
            "latitude": 18.6298,
            "longitude": 73.7997,
            "verification_status": VerificationStatus.pending,
            "is_verified": False,
            "kyc_status": KycStatus.pending,
            "is_provider_profile_complete": True,
        },
    )

    db.session.commit()

    plumbing = upsert_skill(
        provider=provider_plumber,
        title="Plumbing Repair",
        price="499.00",
        location="Pune",
        description="Leak fixes, tap replacement, and bathroom plumbing.",
    )
    cleaning = upsert_skill(
        provider=provider_cleaner,
        title="Home Cleaning",
        price="899.00",
        location="Pune",
        description="Deep cleaning for 1BHK and 2BHK homes.",
    )
    pending_skill = upsert_skill(
        provider=provider_unverified,
        title="Plumbing Repair",
        price="399.00",
        location="Pune",
        description="Should stay hidden until KYC approval.",
    )

    db.session.commit()

    completed_booking = upsert_booking(
        seeker=seeker1,
        provider=provider_plumber,
        skill=plumbing,
        status=BookingStatus.COMPLETED,
        payment_status=PaymentStatus.CAPTURED,
        offset_days=-3,
    )
    confirmed_booking = upsert_booking(
        seeker=seeker2,
        provider=provider_cleaner,
        skill=cleaning,
        status=BookingStatus.CONFIRMED,
        payment_status=PaymentStatus.CAPTURED,
        offset_days=1,
    )
    cancelled_booking = upsert_booking(
        seeker=seeker1,
        provider=provider_cleaner,
        skill=cleaning,
        status=BookingStatus.CANCELLED,
        payment_status=PaymentStatus.REFUNDED,
        offset_days=-1,
    )
    pending_booking = upsert_booking(
        seeker=seeker2,
        provider=provider_plumber,
        skill=plumbing,
        status=BookingStatus.PENDING,
        payment_status=PaymentStatus.NONE,
        offset_days=2,
    )

    db.session.commit()

    if not Message.query.filter_by(room=f"booking_{completed_booking.id}").first():
        db.session.add(
            Message(
                room=f"booking_{completed_booking.id}",
                sender_id=seeker1.id,
                content="Hi Ravi, please bring a replacement washer if needed.",
            )
        )
        db.session.add(
            Message(
                room=f"booking_{completed_booking.id}",
                sender_id=provider_plumber.id,
                content="Sure, I will carry the plumbing kit with me.",
            )
        )

    for provider in (provider_plumber, provider_cleaner):
        for doc_type in ("id_front", "id_back", "selfie", "bank_proof"):
            ensure_kyc_doc(provider, doc_type)

    db.session.commit()

    print("Seed complete")
    print(
        {
            "seekers": [seeker1.email, seeker2.email],
            "providers": [
                provider_plumber.email,
                provider_cleaner.email,
                provider_unverified.email,
            ],
            "skills": [plumbing.title, cleaning.title, pending_skill.title],
            "bookings": [
                completed_booking.id,
                confirmed_booking.id,
                cancelled_booking.id,
                pending_booking.id,
            ],
        }
    )
