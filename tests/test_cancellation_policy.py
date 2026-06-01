from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import Booking, BookingStatus, PaymentStatus, User


def test_booking_cancel_preview_and_cancel_response(
    app,
    client,
    auth_headers,
    register_user,
):
    with app.app_context():
        provider, _provider_token = register_user(
            "provider",
            name="Policy Provider",
            email="policy-provider@example.com",
        )
        seeker, seeker_token = register_user(
            "seeker",
            name="Policy Seeker",
            email="policy-seeker@example.com",
        )

        provider_record = db.session.get(User, provider["id"])
        provider_record.cancellation_cutoff_hours = 2
        provider_record.cancellation_fee_pct = 20

        booking = Booking(
            seeker_id=seeker["id"],
            provider_id=provider["id"],
            skill_id=1,
            scheduled_at=(datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None),
            duration_minutes=60,
            price=1000,
            currency="INR",
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.CAPTURED,
        )
        db.session.add(booking)
        db.session.commit()

        preview_response = client.get(
            f"/api/bookings/{booking.id}/change-policy-preview",
            headers=auth_headers(seeker_token),
        )
        assert preview_response.status_code == 200
        preview_data = preview_response.get_json()
        assert preview_data["cancellation_policy"]["cutoff_hours"] == 2
        assert preview_data["cancellation_policy"]["fee_percent"] == 20
        assert preview_data["fee_amount"] >= 0
        assert preview_data["refund_amount"] >= 0

        cancel_response = client.post(
            f"/api/bookings/{booking.id}/cancel",
            headers=auth_headers(seeker_token),
            json={"reason_code": "PLANS_CHANGED"},
        )
        assert cancel_response.status_code == 200
        cancel_data = cancel_response.get_json()
        assert cancel_data["status"] == "CANCELLED"
        assert cancel_data["refund_status"] == "PROCESSED"
        assert cancel_data["fee_charged"] >= 0
        assert cancel_data["refund_amount"] >= 0
        assert cancel_data["policy_applied"]


def test_booking_cancel_with_promo_refunds_payable_only(
    app,
    client,
    auth_headers,
    register_user,
):
    with app.app_context():
        provider, _provider_token = register_user(
            "provider",
            name="Policy Provider 2",
            email="policy-provider2@example.com",
        )
        seeker, seeker_token = register_user(
            "seeker",
            name="Policy Seeker 2",
            email="policy-seeker2@example.com",
        )

        provider_record = db.session.get(User, provider["id"])
        provider_record.cancellation_cutoff_hours = 2
        provider_record.cancellation_fee_pct = 20

        booking = Booking(
            seeker_id=seeker["id"],
            provider_id=provider["id"],
            skill_id=1,
            scheduled_at=(datetime.now(timezone.utc) + timedelta(hours=12)).replace(tzinfo=None),
            duration_minutes=60,
            price=1000,
            promo_discount_amount=200,
            amount_payable=800,
            currency="INR",
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.CAPTURED,
        )
        db.session.add(booking)
        db.session.commit()

        # Free cancellation preview (12 hours before start, cutoff is 2 hours)
        preview_response = client.get(
            f"/api/bookings/{booking.id}/change-policy-preview",
            headers=auth_headers(seeker_token),
        )
        assert preview_response.status_code == 200
        preview_data = preview_response.get_json()
        # Refund amount should be capped at (price - promo_discount) = 1000 - 200 = 800
        assert preview_data["refund_amount"] == 800.0

        # Execute cancellation
        cancel_response = client.post(
            f"/api/bookings/{booking.id}/cancel",
            headers=auth_headers(seeker_token),
            json={"reason_code": "PLANS_CHANGED"},
        )
        assert cancel_response.status_code == 200
        cancel_data = cancel_response.get_json()
        assert cancel_data["status"] == "CANCELLED"
        assert cancel_data["refund_status"] == "PROCESSED"
        assert cancel_data["refund_amount"] == 800.0

