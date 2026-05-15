from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import AuditLog, Booking, BookingStatus, Skill, User


def test_admin_can_search_users_and_bookings(app, client, register_user, auth_headers):
    admin, admin_token = register_user("seeker", email="ops-admin@example.com")
    seeker, _ = register_user("seeker", email="search-seeker@example.com")
    provider, _ = register_user("provider", email="search-provider@example.com")

    with app.app_context():
        admin_user = User.query.filter_by(email=admin["email"]).first()
        admin_user.is_admin = True
        seeker_user = User.query.filter_by(email=seeker["email"]).first()
        provider_user = User.query.filter_by(email=provider["email"]).first()
        provider_user.phone = "9876543210"
        provider_user.location = "Pune"

        skill = Skill(
            provider_id=provider_user.id,
            title="Pipe Repair",
            description="Fix leaking pipes",
            price=999,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()

        booking = Booking(
            seeker_id=seeker_user.id,
            provider_id=provider_user.id,
            skill_id=skill.id,
            scheduled_at=(datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None),
            duration_minutes=60,
            price=999,
            status=BookingStatus.CONFIRMED,
        )
        db.session.add(booking)
        db.session.flush()

        AuditLog.record(
            "booking.created",
            actor_id=seeker_user.id,
            actor_role="SEEKER",
            target_type="booking",
            target_id=booking.id,
            metadata={"booking_id": booking.id},
        )
        db.session.commit()
        provider_id = provider_user.id
        seeker_id = seeker_user.id
        booking_id = booking.id

    user_search = client.get(
        "/api/ops/admin/users/search?q=search&limit=20",
        headers=auth_headers(admin_token),
    )
    assert user_search.status_code == 200
    user_items = user_search.get_json()["items"]
    assert any(item["id"] == provider_id for item in user_items)
    provider_item = next(item for item in user_items if item["id"] == provider_id)
    assert provider_item["phone_masked"].endswith("43210")

    user_detail = client.get(
        f"/api/ops/admin/users/{seeker_id}",
        headers=auth_headers(admin_token),
    )
    assert user_detail.status_code == 200
    user_detail_data = user_detail.get_json()
    assert user_detail_data["user"]["id"] == seeker_id
    assert len(user_detail_data["recent_bookings"]) == 1

    booking_search = client.get(
        "/api/ops/admin/bookings/search?q=pipe&status=CONFIRMED&limit=20",
        headers=auth_headers(admin_token),
    )
    assert booking_search.status_code == 200
    booking_items = booking_search.get_json()["items"]
    assert any(item["id"] == booking_id for item in booking_items)

    booking_detail = client.get(
        f"/api/ops/admin/bookings/{booking_id}",
        headers=auth_headers(admin_token),
    )
    assert booking_detail.status_code == 200
    booking_detail_data = booking_detail.get_json()
    assert booking_detail_data["booking"]["id"] == booking_id
    assert booking_detail_data["audit_log"][0]["event_type"] == "booking.created"


def test_non_admin_cannot_use_admin_search(client, register_user, auth_headers):
    seeker, seeker_token = register_user("seeker", email="plain-user@example.com")
    response = client.get(
        "/api/ops/admin/users/search?q=plain&limit=20",
        headers=auth_headers(seeker_token),
    )
    assert response.status_code == 403
