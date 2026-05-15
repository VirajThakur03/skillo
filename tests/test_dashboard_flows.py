from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.extensions import db
import pytest

from app.models import Booking, BookingStatus, KycStatus, Skill, User, VerificationStatus


def test_provider_dashboard_allows_pending_kyc_with_notice(app, client, register_user, auth_headers):
    provider_data, provider_token = register_user(
        "provider",
        name="Dashboard Provider",
        email="dashboard-provider@example.com",
    )

    with app.app_context():
        provider = db.session.get(User, provider_data["id"])
        provider.verification_status = VerificationStatus.completed
        provider.is_verified = True
        provider.kyc_status = KycStatus.pending
        provider.wallet_balance = Decimal("150.00")
        db.session.commit()

    response = client.get(
        "/api/provider/dashboard",
        headers=auth_headers(provider_token),
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["provider"]["kyc_blocked"] is True
    assert payload["provider"]["kyc_status"] == "pending"
    assert "pending" in payload["provider"]["kyc_notice"].lower()


@pytest.mark.parametrize(
    ("kyc_status", "expected_status", "notice_expected"),
    [
        (KycStatus.pending, 200, True),
        (KycStatus.documents_submitted, 200, True),
        (KycStatus.under_review, 200, True),
        (KycStatus.approved, 200, False),
        (KycStatus.rejected, 200, True),
        (KycStatus.suspended, 403, False),
    ],
)
def test_provider_dashboard_handles_all_kyc_states(
    app,
    client,
    register_user,
    auth_headers,
    kyc_status,
    expected_status,
    notice_expected,
):
    provider_data, provider_token = register_user(
        "provider",
        name=f"KYC {kyc_status.value}",
        email=f"kyc-{kyc_status.value}@example.com",
    )

    with app.app_context():
        provider = db.session.get(User, provider_data["id"])
        provider.verification_status = VerificationStatus.completed
        provider.is_verified = True
        provider.kyc_status = kyc_status
        provider.kyc_rejection_reason = "Please re-upload your document." if kyc_status == KycStatus.rejected else None
        db.session.commit()

    response = client.get("/api/provider/dashboard", headers=auth_headers(provider_token))
    assert response.status_code == expected_status

    payload = response.get_json()
    if expected_status == 200:
        assert payload["provider"]["kyc_status"] == kyc_status.value
        assert bool(payload["provider"]["kyc_notice"]) is notice_expected
    else:
        assert payload["status"] == kyc_status.value


def test_seeker_my_bookings_returns_rows_without_dashboard_crash(app, client, register_user, auth_headers):
    seeker_data, seeker_token = register_user(
        "seeker",
        name="Bookings Seeker",
        email="bookings-seeker@example.com",
    )
    provider_data, _provider_token = register_user(
        "provider",
        name="Bookings Provider",
        email="bookings-provider@example.com",
    )

    with app.app_context():
        provider = db.session.get(User, provider_data["id"])
        provider.verification_status = VerificationStatus.completed
        provider.is_verified = True
        provider.kyc_status = KycStatus.approved

        skill = Skill(
            provider_id=provider.id,
            title="AC Repair",
            description="Cooling issue fix",
            price=Decimal("899.00"),
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()

        booking = Booking(
            seeker_id=seeker_data["id"],
            provider_id=provider.id,
            skill_id=skill.id,
            scheduled_at=(datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None),
            duration_minutes=60,
            price=Decimal("899.00"),
            amount_payable=Decimal("899.00"),
            currency="INR",
            status=BookingStatus.CANCELLED,
            cancellation_reason="provider_unavailable",
        )
        db.session.add(booking)
        db.session.commit()

    response = client.get(
        "/api/bookings/my",
        headers=auth_headers(seeker_token),
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert len(payload) == 1
    assert payload[0]["skill"] == "AC Repair"
    assert payload[0]["provider"] == "Bookings Provider"
    assert payload[0]["cancellation_reason"] == "provider_unavailable"
