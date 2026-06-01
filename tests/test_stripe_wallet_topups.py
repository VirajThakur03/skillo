from datetime import datetime, timezone
from decimal import Decimal

from app.extensions import db
from app.models import User, WalletTopup, WalletTransaction, WebhookEvent


def test_wallet_topup_endpoint_supports_stripe_checkout(
    app,
    client,
    register_user,
    auth_headers,
    monkeypatch,
):
    user, token = register_user(
        "seeker",
        name="Stripe Wallet User",
        email="stripe-wallet-user@example.com",
    )

    class FakeSession:
        provider = "stripe"
        session_id = "cs_topup_test_123"
        checkout_url = "https://checkout.stripe.com/c/pay/cs_topup_test_123"
        payment_intent_id = "pi_topup_test_123"
        amount = Decimal("500.00")
        currency = "INR"

    monkeypatch.setattr(
        "app.routes.wallet.create_wallet_topup_checkout_session",
        lambda user, amount, success_url, cancel_url, topup_reference: FakeSession(),
    )

    app.config.update(
        PAYMENT_PROVIDER="stripe",
        PAYMENT_MODE="real",
        WALLET_TOPUP_PROVIDER="stripe",
    )

    response = client.post(
        "/api/wallet/v2/topup",
        json={"amount": 500},
        headers=auth_headers(token),
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["provider"] == "stripe"
    assert payload["checkout_url"].startswith("https://checkout.stripe.com/")

    with app.app_context():
        topup = WalletTopup.query.filter_by(user_id=user["id"]).first()
        assert topup is not None
        assert topup.status == "PENDING"
        assert topup.gateway_order_id == "cs_topup_test_123"
        assert topup.gateway_payment_id == "pi_topup_test_123"


def test_stripe_wallet_topup_webhook_credits_wallet_once(
    app,
    client,
    register_user,
    monkeypatch,
):
    user, _token = register_user(
        "seeker",
        name="Stripe Wallet Webhook User",
        email="stripe-wallet-webhook@example.com",
    )

    with app.app_context():
        topup = WalletTopup(
            user_id=user["id"],
            provider="stripe",
            topup_reference="topup_stripe_1",
            gateway_order_id="cs_topup_123",
            gateway_payment_id="pi_topup_123",
            amount=Decimal("500.00"),
            currency="INR",
            status="PENDING",
        )
        db.session.add(topup)
        db.session.commit()

    event = {
        "id": "evt_stripe_topup_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_topup_123",
                "payment_intent": "pi_topup_123",
                "amount_total": 50000,
                "metadata": {
                    "flow": "wallet_topup",
                    "topup_reference": "topup_stripe_1",
                    "user_id": str(user["id"]),
                },
            }
        },
    }

    monkeypatch.setattr(
        "app.routes.webhooks.construct_webhook_event",
        lambda payload, signature_header, secret: event,
    )
    app.config["STRIPE_WEBHOOK_SECRET"] = "whsec_test"  # pragma: allowlist secret

    response = client.post(
        "/webhooks/stripe",
        data=b"{}",
        headers={"Stripe-Signature": "t=1,v1=test"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"

    with app.app_context():
        topup = WalletTopup.query.filter_by(topup_reference="topup_stripe_1").first()
        assert topup is not None
        assert topup.status == "COMPLETED"
        assert topup.wallet_transaction_id is not None
        user_record = db.session.get(User, user["id"])
        assert float(user_record.wallet_balance or 0) == 500.0
        assert WalletTransaction.query.filter_by(user_id=user["id"]).count() == 1
        assert WebhookEvent.query.filter_by(event_id="evt_stripe_topup_1").count() == 1


def test_mock_wallet_topup_reconciliation_flow(app, client, register_user, auth_headers):
    user, token = register_user(
        "seeker",
        name="Mock Wallet User",
        email="mock-wallet-user@example.com",
    )

    app.config.update(
        PAYMENT_PROVIDER="mock",
        PAYMENT_MODE="mock",
        WALLET_TOPUP_PROVIDER="mock",
        ALLOW_MOCK_PAYMENTS=True,
    )

    # 1. Initialize PENDING top-up
    response = client.post(
        "/api/wallet/v2/topup",
        json={"amount": 750},
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    payload = response.get_json()
    assert payload["provider"] == "mock"
    topup_ref = payload["topup_reference"]

    with app.app_context():
        topup = WalletTopup.query.filter_by(topup_reference=topup_ref).first()
        assert topup is not None
        assert topup.status == "PENDING"
        assert float(topup.amount) == 750.0

    # 2. Complete top-up via /pay mock endpoint (Zero-Trust verification)
    pay_response = client.post(
        f"/api/wallet/v2/topup/{topup_ref}/pay",
        headers=auth_headers(token),
    )
    assert pay_response.status_code == 200
    assert pay_response.get_json()["status"] == "ok"

    with app.app_context():
        topup = WalletTopup.query.filter_by(topup_reference=topup_ref).first()
        assert topup is not None
        assert topup.status == "COMPLETED"
        user_record = db.session.get(User, user["id"])
        assert float(user_record.wallet_balance or 0) == 750.0
