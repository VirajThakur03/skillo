from datetime import datetime, timedelta

from app.extensions import db
from app.models import Booking, BookingStatus, KycStatus, User, VerificationStatus
from app.services.provider_metrics import format_response_time


def _create_provider_with_skill(client, auth_headers, register_user, *, email, phone, title):
    provider, token = register_user(
        "provider",
        name="Metrics Provider",
        email=email,
    )
    response = client.post(
        "/api/provider/profile",
        headers=auth_headers(token),
        json={
            "name": "Metrics Provider",
            "phone": phone,
            "skill": title,
            "price": 800,
            "location": "Pune",
            "description": "Fast and reliable help",
        },
    )
    assert response.status_code == 200, response.get_json()
    return provider, token, response.get_json()["skill_id"]


def test_format_response_time_values():
    assert format_response_time(None) is None
    assert format_response_time(-1) is None
    assert format_response_time(0) == "< 1 min"
    assert format_response_time(59) == "< 1 min"
    assert format_response_time(450) == "~7 min"
    assert format_response_time(3600) == "~1 hr"
    assert format_response_time(90000) == "> 1 day"


def test_search_provider_metrics_are_kyc_gated(app, client, auth_headers, register_user):
    approved_provider, _, approved_skill_id = _create_provider_with_skill(
        client,
        auth_headers,
        register_user,
        email="approved-metrics@example.com",
        phone="9999999901",
        title="Plumber Pro",
    )
    rejected_provider, _, _ = _create_provider_with_skill(
        client,
        auth_headers,
        register_user,
        email="rejected-metrics@example.com",
        phone="9999999902",
        title="Plumber Basic",
    )

    with app.app_context():
        approved_record = db.session.get(User, approved_provider["id"])
        approved_record.avg_response_seconds = 450
        approved_record.is_verified = True
        approved_record.verification_status = VerificationStatus.completed
        approved_record.kyc_status = KycStatus.approved

        rejected_record = db.session.get(User, rejected_provider["id"])
        rejected_record.avg_response_seconds = 450
        rejected_record.is_verified = True
        rejected_record.verification_status = VerificationStatus.completed
        rejected_record.kyc_status = KycStatus.rejected

        for status in (
            BookingStatus.CONFIRMED,
            BookingStatus.CONFIRMED,
            BookingStatus.CONFIRMED,
            BookingStatus.CONFIRMED,
            BookingStatus.CONFIRMED,
            BookingStatus.CONFIRMED,
            BookingStatus.CONFIRMED,
            BookingStatus.CONFIRMED,
            BookingStatus.CONFIRMED,
            BookingStatus.DECLINED,
        ):
            db.session.add(
                Booking(
                    seeker_id=approved_record.id,
                    provider_id=approved_record.id,
                    skill_id=approved_skill_id,
                    scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
                    duration_minutes=60,
                    price=800,
                    status=status,
                )
            )
        db.session.commit()

    response = client.get("/api/search/providers?q=Plumber")
    assert response.status_code == 200

    items = response.get_json()["items"]
    approved_item = next(item for item in items if item["provider_id"] == approved_provider["id"])
    rejected_item = next(item for item in items if item["provider_id"] == rejected_provider["id"])

    assert approved_item["response_label"] == "~7 min"
    assert approved_item["acceptance_rate"] == 90.0
    assert rejected_item["response_label"] is None
    assert rejected_item["acceptance_rate"] is None
