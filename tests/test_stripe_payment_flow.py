from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.extensions import db
from app.models import Booking, BookingStatus, PaymentStatus, Skill, WebhookEvent


def test_create_payment_session(client, register_user, auth_headers, monkeypatch):
    seeker, seeker_token = register_user("seeker", email="stripe-seeker@example.com")
    provider, _provider_token = register_user("provider", email="stripe-provider@example.com")

    with client.application.app_context():
        skill = Skill(
            provider_id=provider["id"],
            title="Electrician",
            description="Electrical repair",
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
            scheduled_at=(datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None),
            duration_minutes=60,
            price=Decimal("1200.00"),
            amount_payable=Decimal("900.00"),
            currency="INR",
            status=BookingStatus.PENDING,
            payment_status=PaymentStatus.NONE,
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

    class FakeSession:
        provider = "stripe"
        session_id = "cs_test_123"
        checkout_url = "https://checkout.stripe.com/test-session"
        payment_intent_id = "pi_test_123"
        amount = Decimal("900.00")
        currency = "INR"

    monkeypatch.setattr(
        "app.routes.bookings.create_checkout_session",
        lambda booking, success_url, cancel_url: FakeSession(),
    )

    client.application.config["PAYMENT_PROVIDER"] = "stripe"
    client.application.config["PAYMENT_MODE"] = "real"
    client.application.config["PAYMENT_SUCCESS_URL"] = "https://example.test/track/{booking_id}"
    client.application.config["PAYMENT_CANCEL_URL"] = "https://example.test/booking/{skill_id}?provider={provider_id}"

    response = client.post(
        f"/api/bookings/{booking_id}/payment-session",
        headers=auth_headers(seeker_token),
    )
    assert response.status_code == 201
    payload = response.get_json()
    assert payload["provider"] == "stripe"
    assert payload["checkout_url"].startswith("https://checkout.stripe.com/")


def test_stripe_webhook_marks_booking_confirmed(client, register_user, monkeypatch):
    seeker, _seeker_token = register_user("seeker", email="webhook-seeker@example.com")
    provider, _provider_token = register_user("provider", email="webhook-provider@example.com")

    with client.application.app_context():
        skill = Skill(
            provider_id=provider["id"],
            title="Plumber",
            description="Pipe repair",
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
            scheduled_at=(datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None),
            duration_minutes=60,
            price=Decimal("1500.00"),
            amount_payable=Decimal("1500.00"),
            currency="INR",
            status=BookingStatus.PENDING,
            payment_status=PaymentStatus.NONE,
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

    event = {
        "id": "evt_test_123",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_test_123",
                "latest_charge": "ch_test_123",
                "metadata": {"booking_id": str(booking_id)},
            }
        },
    }

    monkeypatch.setattr(
        "app.routes.webhooks.construct_webhook_event",
        lambda payload, signature_header, secret: event,
    )

    client.application.config["STRIPE_WEBHOOK_SECRET"] = "whsec_test"

    response = client.post(
        "/webhooks/stripe",
        data=b"{}",
        headers={"Stripe-Signature": "t=1,v1=test"},
    )
    assert response.status_code == 200

    with client.application.app_context():
        booking = db.session.get(Booking, booking_id)
        assert booking.payment_status == PaymentStatus.CAPTURED
        assert booking.status == BookingStatus.CONFIRMED
        assert booking.payment_ref == "ch_test_123"


def test_stripe_webhook_duplicate_delivery_is_harmless(client, register_user, monkeypatch):
    seeker, _ = register_user("seeker", email="webhook-dup-seeker@example.com")
    provider, _ = register_user("provider", email="webhook-dup-provider@example.com")

    with client.application.app_context():
        skill = Skill(
            provider_id=provider["id"],
            title="Painter",
            description="Wall painting",
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
            scheduled_at=(datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None),
            duration_minutes=60,
            price=Decimal("900.00"),
            amount_payable=Decimal("900.00"),
            currency="INR",
            status=BookingStatus.PENDING,
            payment_status=PaymentStatus.NONE,
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

    event = {
        "id": "evt_dup_123",
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_dup_123", "latest_charge": "ch_dup_123", "metadata": {"booking_id": str(booking_id)}}},
    }
    monkeypatch.setattr("app.routes.webhooks.construct_webhook_event", lambda payload, signature_header, secret: event)
    client.application.config["STRIPE_WEBHOOK_SECRET"] = "whsec_test"

    first = client.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "t=1,v1=test"})
    second = client.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "t=1,v1=test"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.get_json()["status"] == "duplicate"

    with client.application.app_context():
        assert WebhookEvent.query.filter_by(event_id="evt_dup_123").count() == 1


def test_stripe_webhook_marks_payment_failed_and_refunded(client, register_user, monkeypatch):
    seeker, _ = register_user("seeker", email="webhook-fail-seeker@example.com")
    provider, _ = register_user("provider", email="webhook-fail-provider@example.com")

    with client.application.app_context():
        skill = Skill(
            provider_id=provider["id"],
            title="Tutor",
            description="Math tutor",
            price=2000,
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
            price=Decimal("2000.00"),
            amount_payable=Decimal("2000.00"),
            currency="INR",
            status=BookingStatus.PENDING,
            payment_status=PaymentStatus.NONE,
            payment_intent_id="pi_fail_123",
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

    events = [
        {
            "id": "evt_fail_123",
            "type": "payment_intent.payment_failed",
            "data": {"object": {"id": "pi_fail_123", "metadata": {"booking_id": str(booking_id)}}},
        },
        {
            "id": "evt_refund_123",
            "type": "charge.refunded",
            "data": {"object": {"id": "ch_refund_123", "payment_intent": "pi_fail_123", "metadata": {"booking_id": str(booking_id)}}},
        },
    ]
    iterator = iter(events)
    monkeypatch.setattr("app.routes.webhooks.construct_webhook_event", lambda payload, signature_header, secret: next(iterator))
    client.application.config["STRIPE_WEBHOOK_SECRET"] = "whsec_test"

    failed = client.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "t=1,v1=test"})
    refunded = client.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "t=1,v1=test"})
    assert failed.status_code == 200
    assert refunded.status_code == 200

    with client.application.app_context():
        booking = db.session.get(Booking, booking_id)
        assert booking.payment_status == PaymentStatus.REFUNDED
