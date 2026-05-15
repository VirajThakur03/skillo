from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.extensions import db
from app.models import Booking, BookingStatus, PaymentStatus, Skill


class SmokeConfig:
    ENV = "development"
    FLASK_ENV = "development"
    TESTING = True
    SECRET_KEY = os.getenv("SMOKE_SECRET_KEY", "smoke-secret-key-1234567890-AB")
    JWT_SECRET_KEY = os.getenv("SMOKE_JWT_SECRET_KEY", "smoke-jwt-secret-key-1234567890-AB")
    SQLALCHEMY_DATABASE_URI = "sqlite:///smoke_verify.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = "tmp_uploads"
    PAYMENT_PROVIDER = "stripe"
    PAYMENT_MODE = "real"
    ALLOW_MOCK_PAYMENTS = True
    RATELIMIT_ENABLED = False
    RATELIMIT_STORAGE_URI = "memory://"
    SOCKETIO_MESSAGE_QUEUE = None
    SOCKETIO_CORS_ALLOWED_ORIGINS = "*"
    CORS_ALLOWED_ORIGINS = ""
    ALLOW_UNSAFE_WERKZEUG = True
    PAYMENT_SUCCESS_URL = "https://example.test/track/{booking_id}"
    PAYMENT_CANCEL_URL = "https://example.test/booking/{skill_id}?provider={provider_id}"
    STRIPE_SECRET_KEY = "sk_test_123"
    STRIPE_WEBHOOK_SECRET = "whsec_test"


class FakeStripeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(
            {
                "id": "cs_smoke_123",
                "url": "https://checkout.stripe.com/c/pay/cs_smoke_123",
                "payment_intent": "pi_smoke_123",
            }
        ).encode("utf-8")


def _register(client, name, email, role):
    response = client.post(
        "/api/auth/register",
        json={
            "name": name,
            "email": email,
            "password": "secret123",
            "role": role,
        },
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def main():
    app = create_app(SmokeConfig)
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

    seeker = _register(client, "Smoke Seeker", "smoke-seeker@example.com", "seeker")
    provider = _register(client, "Smoke Provider", "smoke-provider@example.com", "provider")

    login = client.post(
        "/api/auth/login",
        json={"email": "smoke-seeker@example.com", "password": "secret123"},
    )
    assert login.status_code == 200, login.get_json()
    refresh = client.post(
        "/api/auth/refresh",
        headers={"Authorization": "Bearer " + login.get_json()["refresh_token"]},
    )
    assert refresh.status_code == 200, refresh.get_json()

    reset_request = client.post(
        "/api/auth/password-reset/request",
        json={"email": "smoke-seeker@example.com"},
    )
    assert reset_request.status_code == 202, reset_request.get_json()
    reset_token = reset_request.get_json()["reset_token"]
    reset_confirm = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": reset_token, "password": "newsecret456"},
    )
    assert reset_confirm.status_code == 200, reset_confirm.get_json()

    with app.app_context():
        skill = Skill(
            provider_id=provider["user"]["id"],
            title="Electrician",
            description="Smoke verification service",
            price=Decimal("1200.00"),
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()
        booking = Booking(
            seeker_id=seeker["user"]["id"],
            provider_id=provider["user"]["id"],
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

    seeker_token = seeker["access_token"]
    with patch("app.services.payments.urlopen", return_value=FakeStripeResponse()):
        payment_session = client.post(
            f"/api/bookings/{booking_id}/payment-session",
            headers={"Authorization": "Bearer " + seeker_token},
        )
    assert payment_session.status_code == 201, payment_session.get_json()
    assert payment_session.get_json()["checkout_url"].startswith("https://checkout.stripe.com/")

    from app.routes import webhooks as webhook_routes

    def fake_construct(payload, signature_header, secret):
        return {
            "id": "evt_smoke_123",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_smoke_123",
                    "latest_charge": "ch_smoke_123",
                    "metadata": {"booking_id": str(booking_id)},
                }
            },
        }

    webhook_routes.construct_webhook_event = fake_construct
    webhook_response = client.post(
        "/webhooks/stripe",
        data=b"{}",
        headers={"Stripe-Signature": "t=1,v1=test"},
    )
    assert webhook_response.status_code == 200, webhook_response.get_json()

    final_booking = client.get(
        f"/api/bookings/{booking_id}",
        headers={"Authorization": "Bearer " + seeker_token},
    )
    assert final_booking.status_code == 200, final_booking.get_json()
    final_payload = final_booking.get_json()
    assert final_payload["status"] == "CONFIRMED", final_payload
    assert final_payload["payment_status"] == "CAPTURED", final_payload
    assert final_payload["payment_ref"] == "ch_smoke_123", final_payload

    print("smoke verification passed")


if __name__ == "__main__":
    main()
