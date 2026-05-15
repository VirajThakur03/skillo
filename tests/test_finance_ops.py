from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.extensions import db
from app.models import (
    Booking,
    BookingStatus,
    PaymentStatus,
    RoleEnum,
    User,
    WalletTopup,
    WalletTransactionType,
)
from app.services.wallet_service import credit


def test_admin_finance_endpoints_expose_reconciliation_state(
    app,
    client,
    register_user,
    auth_headers,
):
    admin, admin_token = register_user(
        "seeker",
        name="Finance Admin",
        email="finance-admin@example.com",
    )
    seeker, _ = register_user(
        "seeker",
        name="Finance Seeker",
        email="finance-seeker@example.com",
    )

    with app.app_context():
        admin_user = User.query.filter_by(email=admin["email"]).first()
        admin_user.is_admin = True

        seeker_user = User.query.filter_by(email=seeker["email"]).first()
        credit(
            user_id=seeker_user.id,
            amount=Decimal("250.00"),
            txn_type=WalletTransactionType.CREDIT_TOPUP,
            description="Finance Top-up",
            reference_type="topup",
            reference_id=1,
        )

        stale_topup = WalletTopup(
            user_id=seeker_user.id,
            provider="stripe",
            topup_reference="stale_topup_1",
            amount=Decimal("300.00"),
            currency="INR",
            status="PENDING",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=45),
            updated_at=datetime.now(timezone.utc) - timedelta(minutes=45),
        )
        booking = Booking(
            seeker_id=seeker_user.id,
            provider_id=admin_user.id,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            duration_minutes=60,
            price=Decimal("800.00"),
            amount_payable=Decimal("800.00"),
            currency="INR",
            status=BookingStatus.COMPLETED,
            payment_status=PaymentStatus.CAPTURED,
            platform_fee_amount=Decimal("80.00"),
            worker_earnings=Decimal("705.60"),
            gst_amount=Decimal("14.40"),
            service_amount=Decimal("705.60"),
        )
        db.session.add_all([stale_topup, booking])
        db.session.commit()

    summary_response = client.get(
        "/api/ops/admin/finance/summary",
        headers=auth_headers(admin_token),
    )
    assert summary_response.status_code == 200
    summary = summary_response.get_json()
    assert summary["wallet_liability_total"] >= 250.0
    assert summary["pending_topups"]["count"] >= 1
    assert summary["ledger"]["entries"] >= 2

    reconcile_response = client.get(
        "/api/ops/admin/finance/reconciliation",
        headers=auth_headers(admin_token),
    )
    assert reconcile_response.status_code == 200
    reconciliation = reconcile_response.get_json()
    assert reconciliation["summary"]["stale_pending_topups"] >= 1
    assert reconciliation["summary"]["completed_bookings_missing_invoice"] >= 1
    assert reconciliation["summary"]["unbalanced_entry_groups"] == 0
