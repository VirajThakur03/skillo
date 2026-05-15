import json
import time
import hmac
import hashlib
from datetime import datetime, timezone

from app.models import (
    Booking,
    BookingStatus,
    PaymentStatus,
    WalletTopup,
    User,
    WebhookEvent,
)
from app.extensions import db


def generate_stripe_signature(payload, secret):
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def generate_razorpay_signature(payload, secret):
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def test_stripe_wallet_topup_webhook(client, app, register_user):
    seeker, _ = register_user("seeker")

    with app.app_context():
        # Create pending topup
        topup = WalletTopup(
            user_id=seeker["id"],
            provider="stripe",
            topup_reference="test_topup_123",
            amount=500.0,
            currency="INR",
            status="PENDING",
        )
        db.session.add(topup)
        db.session.commit()

        # Payload
        payload_dict = {
            "id": "evt_test_123",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "payment_intent": "pi_test_123",
                    "amount_total": 50000,
                    "metadata": {
                        "topup_reference": "test_topup_123",
                        "user_id": str(seeker["id"]),
                    }
                }
            }
        }
        payload_str = json.dumps(payload_dict)
        secret = "test_secret"
        client.application.config["STRIPE_WEBHOOK_SECRET"] = secret
        client.application.config["PAYMENT_PROVIDER"] = "stripe"
        signature = generate_stripe_signature(payload_str, secret)

        response = client.post(
            "/webhooks/stripe",
            data=payload_str,
            headers={"Stripe-Signature": signature, "Content-Type": "application/json"}
        )
        
        assert response.status_code == 200
        assert response.json["status"] == "ok"
        
        db.session.refresh(topup)
        assert topup.status == "COMPLETED"
        assert topup.gateway_payment_id == "pi_test_123"
        
        # Duplicate event
        response2 = client.post(
            "/webhooks/stripe",
            data=payload_str,
            headers={"Stripe-Signature": signature, "Content-Type": "application/json"}
        )
        assert response2.status_code == 200
        assert response2.json["status"] == "duplicate"


def test_stripe_booking_webhook(client, app, register_user):
    seeker, _ = register_user("seeker")
    provider, _ = register_user("provider")

    with app.app_context():
        from app.models import Skill
        skill = Skill(
            provider_id=provider["id"],
            title="Test Skill",
            description="Test Skill Description",
            price=1000.0,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()

        booking = Booking(
            seeker_id=seeker["id"],
            provider_id=provider["id"],
            skill_id=skill.id,
            status=BookingStatus.PENDING,
            payment_status=PaymentStatus.NONE,
            price=1000.0,
            amount_payable=1000.0,
            scheduled_at=datetime.now(timezone.utc),
            duration_minutes=60,
        )
        db.session.add(booking)
        db.session.commit()

        payload_dict = {
            "id": "evt_test_456",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_test_456",
                    "latest_charge": "ch_test_456",
                    "metadata": {
                        "booking_id": str(booking.id),
                    }
                }
            }
        }
        payload_str = json.dumps(payload_dict)
        secret = "test_secret"
        client.application.config["STRIPE_WEBHOOK_SECRET"] = secret
        client.application.config["PAYMENT_PROVIDER"] = "stripe"
        signature = generate_stripe_signature(payload_str, secret)

        response = client.post(
            "/webhooks/stripe",
            data=payload_str,
            headers={"Stripe-Signature": signature, "Content-Type": "application/json"}
        )
        
        assert response.status_code == 200
        assert response.json["status"] == "ok"
        
        db.session.refresh(booking)
        assert booking.status == BookingStatus.CONFIRMED
        assert booking.payment_status == PaymentStatus.CAPTURED
        assert booking.payment_intent_id == "pi_test_456"


def test_razorpay_webhook(client, app):
    payload_dict = {
        "event": "payment.captured",
        "id": "evt_rzp_123",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_123",
                    "amount": 100000,
                    "currency": "INR",
                }
            }
        }
    }
    payload_str = json.dumps(payload_dict)
    secret = "test_secret"
    client.application.config["RAZORPAY_WEBHOOK_SECRET"] = secret
    signature = generate_razorpay_signature(payload_str, secret)

    response = client.post(
        "/webhooks/razorpay",
        data=payload_str,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"}
    )
    
    assert response.status_code == 200
