from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.extensions import db
from app.models import (
    AccountingEntry,
    MembershipStatus,
    RoleEnum,
    SubscriptionPlan,
    User,
    UserSubscription,
    WalletTransactionType,
)
from app.runtime_checks import validate_runtime_config
from app.services.booking_service import calculate_booking_fees
from app.services.wallet_service import credit


def test_calculate_booking_fees_applies_membership_discount_and_igst(app):
    with app.app_context():
        seeker = User(
            name="GST Seeker",
            email="gst-seeker@example.com",
            password_hash="x",
            role=RoleEnum.SEEKER,
            gstin="29AAACS1234A1Z5",
            location="Bengaluru, Karnataka",
        )
        provider = User(
            name="GST Provider",
            email="gst-provider@example.com",
            password_hash="x",
            role=RoleEnum.PROVIDER,
            gstin="27AAACP1234P1Z5",
            location="Mumbai, Maharashtra",
        )
        db.session.add_all([seeker, provider])
        db.session.flush()

        plan = SubscriptionPlan(
            slug="pro-provider",
            name="Pro Provider",
            audience="PROVIDER",
            price=Decimal("499.00"),
            billing_period="monthly",
            benefits=["Reduced fee"],
            reduced_fee_pct=Decimal("7.00"),
            active=True,
        )
        db.session.add(plan)
        db.session.flush()

        subscription = UserSubscription(
            user_id=provider.id,
            plan_id=plan.id,
            status=MembershipStatus.ACTIVE,
            started_at=datetime.now(timezone.utc),
            ends_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.session.add(subscription)
        db.session.commit()

        fees = calculate_booking_fees(
            Decimal("1000.00"),
            Decimal("1000.00"),
            provider=provider.id,
            seeker=seeker,
        )

    assert fees["platform_fee_pct"] == Decimal("7.00")
    assert fees["platform_fee_amount"] == Decimal("70.00")
    assert fees["igst_amount"] == Decimal("12.60")
    assert fees["cgst_amount"] == Decimal("0.00")
    assert fees["sgst_amount"] == Decimal("0.00")
    assert fees["tax_mode"] == "igst"


def test_validate_runtime_config_requires_stripe_wallet_secrets_in_production(app, monkeypatch):
    with app.app_context():
        app.config.update(
            ENV="production",
            DEBUG=False,
            TESTING=False,
            ALLOW_UNSAFE_WERKZEUG=False,
            ALLOW_MOCK_PAYMENTS=False,
            PAYMENT_MODE="real",
            PAYMENT_PROVIDER="stripe",
            STRIPE_SECRET_KEY="sk_live_test",  # pragma: allowlist secret
            STRIPE_WEBHOOK_SECRET="",
            STRIPE_API_MODE="live",
            FEATURE_WALLET=True,
            WALLET_TOPUP_PROVIDER="stripe",
            REDIS_URL="redis://example/0",
            SOCKETIO_MESSAGE_QUEUE="redis://example/1",
            CHAT_ATTACHMENT_SCAN_MODE="basic",
            CHAT_ATTACHMENT_REQUIRE_SCAN=True,
            STORAGE_BACKEND="s3",
        )

        monkeypatch.setattr("app.runtime_checks._assert_redis_connectivity", lambda url, label: None)

        try:
            validate_runtime_config(app)
            assert False, "validate_runtime_config should require Stripe wallet webhook secret"
        except RuntimeError as exc:
            assert "STRIPE_WEBHOOK_SECRET" in str(exc)


def test_wallet_credit_posts_balanced_accounting_entries(app):
    with app.app_context():
        user = User(
            name="Ledger User",
            email="ledger-user@example.com",
            password_hash="x",
            role=RoleEnum.SEEKER,
        )
        db.session.add(user)
        db.session.commit()

        txn = credit(
            user_id=user.id,
            amount=Decimal("500.00"),
            txn_type=WalletTransactionType.CREDIT_TOPUP,
            description="Wallet Top-up",
            reference_type="topup",
            reference_id=42,
        )
        db.session.commit()

        entries = AccountingEntry.query.filter_by(
            entry_group=f"wallet_txn:{txn.id}"
        ).all()

    assert len(entries) == 2
    debit_total = sum(
        Decimal(item.amount or 0)
        for item in entries
        if item.direction == "DEBIT"
    )
    credit_total = sum(
        Decimal(item.amount or 0)
        for item in entries
        if item.direction == "CREDIT"
    )
    assert debit_total == Decimal("500.00")
    assert credit_total == Decimal("500.00")
