from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import Booking, BookingStatus, KycStatus, User, VerificationStatus


def _create_provider_with_skill(client, auth_headers, register_user, *, email, phone):
    provider, provider_token = register_user(
        "provider",
        name="Calendar Provider",
        email=email,
    )
    profile_response = client.post(
        "/api/provider/profile",
        headers=auth_headers(provider_token),
        json={
            "name": "Calendar Provider",
            "phone": phone,
            "skill": "Plumber",
            "price": 650,
            "location": "Pune",
            "description": "Slot-aware provider",
        },
    )
    assert profile_response.status_code == 200, profile_response.get_json()
    skill_id = profile_response.get_json()["skill_id"]

    with db.session.no_autoflush:
        provider_record = db.session.get(User, provider["id"])
        provider_record.is_verified = True
        provider_record.verification_status = VerificationStatus.completed
        provider_record.kyc_status = KycStatus.approved
        provider_record.timezone = "Asia/Kolkata"
        db.session.commit()

    return provider, provider_token, skill_id


def test_public_availability_week_start_returns_slot_shape(
    app,
    client,
    auth_headers,
    register_user,
):
    with app.app_context():
        provider, _, skill_id = _create_provider_with_skill(
            client,
            auth_headers,
            register_user,
            email="calendar-provider@example.com",
            phone="9999999912",
        )

        response = client.get(
            f"/api/availability/providers/{provider['id']}?skill_id={skill_id}&week_start=2026-04-20"
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["provider_id"] == provider["id"]
        assert payload["timezone"] == "Asia/Kolkata"
        assert len(payload["slots"]) > 0
        assert {"date", "time", "available", "instant_book", "start_at", "end_at"} <= set(payload["slots"][0].keys())


def test_booking_requires_timezone_and_rejects_taken_slot(
    app,
    client,
    auth_headers,
    register_user,
):
    with app.app_context():
        provider, _, skill_id = _create_provider_with_skill(
            client,
            auth_headers,
            register_user,
            email="calendar-provider-2@example.com",
            phone="9999999913",
        )
        seeker, seeker_token = register_user(
            "seeker",
            name="Calendar Seeker",
            email="calendar-seeker@example.com",
        )

        naive_attempt = client.post(
            "/api/bookings",
            headers=auth_headers(seeker_token),
            json={
                "skill_id": skill_id,
                "provider_id": provider["id"],
                "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0).isoformat(),
                "duration_minutes": 60,
            },
        )
        assert naive_attempt.status_code == 400
        assert naive_attempt.get_json()["error"] == "scheduled_at must include a timezone offset"

        taken_start = datetime.now(timezone.utc) + timedelta(hours=5)
        taken_start = taken_start.replace(minute=0, second=0, microsecond=0)

        db.session.add(
            Booking(
                seeker_id=seeker["id"],
                provider_id=provider["id"],
                skill_id=skill_id,
                scheduled_at=taken_start.astimezone(timezone.utc).replace(tzinfo=None),
                duration_minutes=60,
                price=650,
                status=BookingStatus.CONFIRMED,
            )
        )
        db.session.commit()

        conflict_attempt = client.post(
            "/api/bookings",
            headers=auth_headers(seeker_token),
            json={
                "skill_id": skill_id,
                "provider_id": provider["id"],
                "scheduled_at": taken_start.isoformat(),
                "duration_minutes": 60,
            },
        )
        assert conflict_attempt.status_code == 409
        assert conflict_attempt.get_json()["error"] == "slot_taken"
