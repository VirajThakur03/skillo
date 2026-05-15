import hashlib
import hmac
import json
from decimal import Decimal

from app.extensions import db
from app.models import User, WalletTopup, WalletTransaction, WebhookEvent


def _signature(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def test_razorpay_wallet_topup_webhook_credits_wallet_once(app, client, register_user):
    user, _token = register_user(
        "seeker",
        name="Razorpay Wallet User",
        email="razorpay-wallet@example.com",
    )

    with app.app_context():
        app.config["RAZORPAY_WEBHOOK_SECRET"] = "test_webhook_secret"
        topup = WalletTopup(
            user_id=user["id"],
            provider="razorpay",
            topup_reference="topup_1_test",
            gateway_order_id="order_test_123",
            amount=Decimal("500.00"),
            currency="INR",
            status="PENDING",
        )
        db.session.add(topup)
        db.session.commit()

        payload = {
            "id": "evt_razorpay_topup_1",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_test_123",
                        "order_id": "order_test_123",
                        "amount": 50000,
                        "notes": {
                            "user_id": str(user["id"]),
                            "topup_id": "topup_1_test",
                        },
                    }
                }
            },
        }
        body = json.dumps(payload).encode()

    response = client.post(
        "/webhooks/razorpay",
        data=body,
        headers={"X-Razorpay-Signature": _signature("test_webhook_secret", body)},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"

    with app.app_context():
        updated = WalletTopup.query.filter_by(topup_reference="topup_1_test").first()
        assert updated is not None
        assert updated.status == "COMPLETED"
        assert updated.gateway_payment_id == "pay_test_123"
        user_record = db.session.get(User, user["id"])
        assert float(user_record.wallet_balance or 0) == 500.0
        assert WalletTransaction.query.filter_by(user_id=user["id"]).count() == 1
        assert WebhookEvent.query.filter_by(event_id="evt_razorpay_topup_1").count() == 1


def test_razorpay_wallet_topup_duplicate_webhook_does_not_double_credit(app, client, register_user):
    user, _token = register_user(
        "seeker",
        name="Razorpay Duplicate User",
        email="razorpay-duplicate@example.com",
    )

    with app.app_context():
        app.config["RAZORPAY_WEBHOOK_SECRET"] = "test_webhook_secret"
        topup = WalletTopup(
            user_id=user["id"],
            provider="razorpay",
            topup_reference="topup_dup_test",
            gateway_order_id="order_dup_123",
            amount=Decimal("300.00"),
            currency="INR",
            status="PENDING",
        )
        db.session.add(topup)
        db.session.commit()

        payload = {
            "id": "evt_razorpay_dup_1",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_dup_123",
                        "order_id": "order_dup_123",
                        "amount": 30000,
                        "notes": {
                            "user_id": str(user["id"]),
                            "topup_id": "topup_dup_test",
                        },
                    }
                }
            },
        }
        body = json.dumps(payload).encode()
        sig = _signature("test_webhook_secret", body)

    first = client.post("/webhooks/razorpay", data=body, headers={"X-Razorpay-Signature": sig})
    second = client.post("/webhooks/razorpay", data=body, headers={"X-Razorpay-Signature": sig})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.get_json()["status"] == "duplicate"

    with app.app_context():
        user_record = db.session.get(User, user["id"])
        assert float(user_record.wallet_balance or 0) == 300.0
        assert WalletTransaction.query.filter_by(user_id=user["id"]).count() == 1
