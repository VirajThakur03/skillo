from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.extensions import db
from app.models import Booking, BookingStatus, PaymentStatus, RoleEnum, Skill, User, VerificationStatus, WalletTransactionType
from app.services.wallet_service import credit


def test_payment_history_includes_wallet_entries(app, client, register_user, auth_headers):
    seeker, seeker_token = register_user(
        "seeker",
        name="History Seeker",
        email="history-seeker@example.com",
    )
    provider, _provider_token = register_user(
        "provider",
        name="History Provider",
        email="history-provider@example.com",
    )

    with app.app_context():
        seeker_record = db.session.get(User, seeker["id"])
        provider_record = db.session.get(User, provider["id"])
        provider_record.verification_status = VerificationStatus.completed
        provider_record.is_verified = True

        skill = Skill(
            provider_id=provider_record.id,
            title="Deep Cleaning",
            description="Apartment cleaning",
            price=1299,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()

        booking = Booking(
            seeker_id=seeker_record.id,
            provider_id=provider_record.id,
            skill_id=skill.id,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            duration_minutes=120,
            price=1299,
            amount_payable=1299,
            currency="INR",
            status=BookingStatus.COMPLETED,
            payment_status=PaymentStatus.CAPTURED,
            platform_fee_pct=Decimal("10.00"),
            platform_fee_amount=Decimal("129.90"),
            worker_earnings=Decimal("1169.10"),
            service_amount=Decimal("1145.72"),
            gst_amount=Decimal("23.38"),
        )
        db.session.add(booking)
        db.session.flush()

        credit(
            user_id=seeker_record.id,
            amount=Decimal("500.00"),
            txn_type=WalletTransactionType.CREDIT_TOPUP,
            description="Wallet Top-up (Test)",
            reference_type="topup",
        )
        db.session.commit()

    response = client.get(
        "/api/bookings/payment-history",
        headers=auth_headers(seeker_token),
    )

    assert response.status_code == 200
    payload = response.get_json()
    kinds = {item["kind"] for item in payload["items"]}
    assert "booking" in kinds
    assert "wallet" in kinds


def test_wallet_v2_contract_supports_filters_and_pending_earnings(app, client, register_user, auth_headers):
    seeker, _seeker_token = register_user(
        "seeker",
        name="Wallet Seeker",
        email="wallet-seeker@example.com",
    )
    provider, provider_token = register_user(
        "provider",
        name="Wallet Provider",
        email="wallet-provider@example.com",
    )

    with app.app_context():
        provider_record = db.session.get(User, provider["id"])
        provider_record.verification_status = VerificationStatus.completed
        provider_record.is_verified = True

        credit(
            user_id=provider_record.id,
            amount=Decimal("250.00"),
            txn_type=WalletTransactionType.CREDIT_TOPUP,
            description="Wallet Top-up (Contract Test)",
            reference_type="topup",
        )
        booking = Booking(
            seeker_id=seeker["id"],
            provider_id=provider_record.id,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            duration_minutes=60,
            price=Decimal("1000.00"),
            amount_payable=Decimal("1000.00"),
            currency="INR",
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.CAPTURED,
            worker_earnings=Decimal("900.00"),
            platform_fee_pct=Decimal("10.00"),
            platform_fee_amount=Decimal("100.00"),
            service_amount=Decimal("882.00"),
            gst_amount=Decimal("18.00"),
        )
        db.session.add(booking)
        db.session.commit()

    balance_response = client.get(
        "/api/wallet/v2/balance",
        headers=auth_headers(provider_token),
    )
    transactions_response = client.get(
        "/api/wallet/v2/transactions?page=1&type=CREDIT_TOPUP",
        headers=auth_headers(provider_token),
    )

    assert balance_response.status_code == 200
    balance_payload = balance_response.get_json()
    assert "balance" in balance_payload
    assert "pending_earnings" in balance_payload

    assert transactions_response.status_code == 200
    tx_payload = transactions_response.get_json()
    assert tx_payload["current_page"] == 1
    assert "total_pages" in tx_payload
    assert tx_payload["items"][0]["type"] == WalletTransactionType.CREDIT_TOPUP.value
