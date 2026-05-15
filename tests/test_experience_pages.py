from datetime import UTC, datetime, timedelta

from app.extensions import db
from app.models import (
    Booking,
    BookingStatus,
    PaymentStatus,
    RefundStatus,
    Review,
    RoleEnum,
    Skill,
    User,
    VerificationStatus,
)


def _seed_provider_directory():
    seeker = User(
        name="Seeker User",
        email="seeker-pages@example.com",
        phone="9111111111",
        password_hash="x",
        role=RoleEnum.SEEKER,
        location="Mumbai",
    )
    provider = User(
        name="Amit Repairs",
        email="provider-pages@example.com",
        phone="9222222222",
        password_hash="x",
        role=RoleEnum.PROVIDER,
        location="Andheri, Mumbai",
        bio="Fast home repair specialist",
        timezone="Asia/Kolkata",
        service_areas=["Andheri", "Bandra"],
        specialties=["AC service", "Leak fixes"],
        certifications=["Trade License", "OEM Training"],
        portfolio_images=["https://example.com/portfolio-1.jpg"],
        rating=4.8,
        completed_jobs=27,
        is_verified=True,
        verification_status=VerificationStatus.completed,
        is_provider_profile_complete=True,
    )
    db.session.add_all([seeker, provider])
    db.session.flush()

    skill = Skill(
        provider_id=provider.id,
        title="AC repair",
        description="Inspection, repair, and maintenance for split and window AC units.",
        price=1200,
        currency="INR",
        location="Andheri, Mumbai",
        tags="repair, same day, verified",
        is_active=True,
    )
    db.session.add(skill)
    db.session.flush()

    starts_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1)
    booking = Booking(
        seeker_id=seeker.id,
        provider_id=provider.id,
        skill_id=skill.id,
        scheduled_at=starts_at,
        original_scheduled_at=starts_at,
        duration_minutes=60,
        price=1200,
        currency="INR",
        status=BookingStatus.COMPLETED,
        payment_status=PaymentStatus.CAPTURED,
        refund_status=RefundStatus.NONE,
        worker_earnings=1200,
    )
    db.session.add(booking)
    db.session.flush()

    review = Review(
        booking_id=booking.id,
        seeker_id=seeker.id,
        provider_id=provider.id,
        rating=4.5,
        punctuality_rating=4.0,
        quality_rating=5.0,
        communication_rating=4.5,
        value_rating=4.0,
        comment="Arrived on time and fixed the issue quickly.",
    )
    db.session.add(review)
    db.session.commit()

    return skill.id


def test_updated_experience_pages_render(client, app):
    with app.app_context():
        skill_id = _seed_provider_directory()

    pages = [
        ("/home", b"Service Discovery"),
        ("/notifications", b"Delivery settings"),
        ("/quote-requests", b"Send a custom scope to up to three providers"),
        ("/provider/profile", b"Portfolio links"),
        (f"/providers?skill_id={skill_id}", b"Compare nearby providers before you book."),
        (f"/skill/{skill_id}", b"Request Quote"),
    ]

    for path, expected in pages:
        response = client.get(path)
        assert response.status_code == 200
        assert expected in response.data
