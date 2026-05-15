from datetime import datetime, timedelta

from app.extensions import db
from app.models import Booking, BookingStatus, PaymentStatus, Review, Skill


def test_provider_can_save_private_booking_notes(
    app,
    client,
    register_user,
    auth_headers,
):
    seeker, _seeker_token = register_user(
        "seeker",
        name="Notes Seeker",
        email="notes-seeker@example.com",
    )
    provider, provider_token = register_user(
        "provider",
        name="Notes Provider",
        email="notes-provider@example.com",
    )

    with app.app_context():
        skill = Skill(
            provider_id=provider["id"],
            title="Painter",
            description="Interior paint work",
            price=1500,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()
        booking = Booking(
            seeker_id=seeker["id"],
            provider_id=provider["id"],
            skill_id=skill.id,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            duration_minutes=60,
            price=1500,
            currency="INR",
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.CAPTURED,
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

    response = client.patch(
        f"/api/bookings/{booking_id}/notes",
        headers=auth_headers(provider_token),
        json={"notes": "Bring paint swatches and masking tape."},
    )

    assert response.status_code == 200
    assert response.get_json()["notes"] == "Bring paint swatches and masking tape."


def test_provider_reply_to_review_is_single_use(
    app,
    client,
    register_user,
    auth_headers,
):
    seeker, _seeker_token = register_user(
        "seeker",
        name="Reply Seeker",
        email="reply-seeker@example.com",
    )
    provider, provider_token = register_user(
        "provider",
        name="Reply Provider",
        email="reply-provider@example.com",
    )

    with app.app_context():
        skill = Skill(
            provider_id=provider["id"],
            title="Carpenter",
            description="Furniture repair",
            price=1200,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()
        booking = Booking(
            seeker_id=seeker["id"],
            provider_id=provider["id"],
            skill_id=skill.id,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            duration_minutes=60,
            price=1200,
            currency="INR",
            status=BookingStatus.COMPLETED,
            payment_status=PaymentStatus.CAPTURED,
        )
        db.session.add(booking)
        db.session.flush()
        review = Review(
            booking_id=booking.id,
            seeker_id=seeker["id"],
            provider_id=provider["id"],
            rating=4.0,
            comment="Good work overall.",
        )
        db.session.add(review)
        db.session.commit()
        review_id = review.id

    first = client.post(
        f"/api/bookings/reviews/{review_id}/reply",
        headers=auth_headers(provider_token),
        json={"reply": "Thanks for the feedback. Happy to help again."},
    )
    assert first.status_code == 201
    assert first.get_json()["provider_reply"] == "Thanks for the feedback. Happy to help again."

    second = client.post(
        f"/api/bookings/reviews/{review_id}/reply",
        headers=auth_headers(provider_token),
        json={"reply": "Second reply should fail."},
    )
    assert second.status_code == 409
    assert second.get_json()["error"] == "reply already submitted"
