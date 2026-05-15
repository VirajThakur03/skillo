from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import Booking, BookingStatus, PaymentStatus, Skill


def test_chat_message_triggers_notification_hook(
    app,
    client,
    register_user,
    auth_headers,
    monkeypatch,
):
    seeker, seeker_token = register_user(
        "seeker",
        name="Notify Seeker",
        email="notify-seeker@example.com",
    )
    provider, _provider_token = register_user(
        "provider",
        name="Notify Provider",
        email="notify-provider@example.com",
    )

    with app.app_context():
        skill = Skill(
            provider_id=provider["id"],
            title="Cleaner",
            description="Home cleaning",
            price=900,
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
            price=900,
            currency="INR",
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.CAPTURED,
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

    calls = []

    def fake_notify(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr("app.routes.chat.notify_new_chat_message", fake_notify)

    response = client.post(
        f"/api/chat/room/booking_{booking_id}",
        headers=auth_headers(seeker_token),
        json={"content": "Please call before arrival."},
    )

    assert response.status_code == 201
    assert len(calls) == 1
    assert calls[0]["recipient_id"] == provider["id"]
    assert calls[0]["conversation_id"] == f"booking_{booking_id}"


def test_booking_payment_triggers_status_notification_hook(
    app,
    client,
    register_user,
    auth_headers,
    monkeypatch,
):
    seeker, seeker_token = register_user(
        "seeker",
        name="Payment Seeker",
        email="payment-seeker@example.com",
    )
    provider, _provider_token = register_user(
        "provider",
        name="Payment Provider",
        email="payment-provider@example.com",
    )

    with app.app_context():
        skill = Skill(
            provider_id=provider["id"],
            title="Plumber",
            description="Pipe repair",
            price=1100,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()
        booking = Booking(
            seeker_id=seeker["id"],
            provider_id=provider["id"],
            skill_id=skill.id,
            scheduled_at=(datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None),
            duration_minutes=60,
            price=1100,
            currency="INR",
            status=BookingStatus.PENDING,
            payment_status=PaymentStatus.NONE,
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

    calls = []

    def fake_notify(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr("app.routes.bookings.notify_booking_status_change", fake_notify)

    response = client.post(
        f"/api/bookings/{booking_id}/pay",
        headers=auth_headers(seeker_token),
        json={"payment_ref": "PAY-NOTIFY-1"},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0]["new_status"] == "confirmed"
    assert calls[0]["changed_by_role"] == "seeker"
