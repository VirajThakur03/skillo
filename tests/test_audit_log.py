from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import AuditLog, Booking, BookingStatus, RoleEnum, Skill, User


def _seed_skill(app, provider_email, seeker_email):
    with app.app_context():
        provider = User.query.filter_by(email=provider_email).first()
        seeker = User.query.filter_by(email=seeker_email).first()
        skill = Skill(
            provider_id=provider.id,
            title="Audit Plumbing",
            description="Leak fix",
            price=1200,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.commit()
        return provider.id, seeker.id, skill.id


def test_login_failure_records_audit_entry(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "missing@example.com", "password": "wrongpass"},
    )
    assert response.status_code == 401

    with client.application.app_context():
        entry = AuditLog.query.filter_by(event_type="user.login_failed").order_by(AuditLog.id.desc()).first()
        assert entry is not None
        assert entry.actor_role == "anonymous"
        assert entry.metadata_json["reason"] == "bad_password"


def test_booking_create_and_duplicate_block_are_audited(app, client, register_user, auth_headers):
    provider, _ = register_user("provider", email="audit-provider@example.com")
    seeker, seeker_token = register_user("seeker", email="audit-seeker@example.com")
    provider_id, seeker_id, skill_id = _seed_skill(app, provider["email"], seeker["email"])

    scheduled_at = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0).isoformat()

    create_response = client.post(
        "/api/bookings",
        headers=auth_headers(seeker_token),
        json={
            "skill_id": skill_id,
            "provider_id": provider_id,
            "scheduled_at": scheduled_at,
            "duration_minutes": 60,
        },
    )
    assert create_response.status_code == 201
    booking_id = create_response.get_json()["id"]

    with app.app_context():
        created_entry = AuditLog.query.filter_by(event_type="booking.created", target_id=booking_id).first()
        assert created_entry is not None
        assert created_entry.actor_id == seeker_id
        assert created_entry.metadata_json["booking_id"] == booking_id

    duplicate_response = client.post(
        "/api/bookings",
        headers=auth_headers(seeker_token),
        json={
            "skill_id": skill_id,
            "provider_id": provider_id,
            "scheduled_at": scheduled_at,
            "duration_minutes": 60,
        },
    )
    assert duplicate_response.status_code == 409

    with app.app_context():
        duplicate_entry = AuditLog.query.filter_by(event_type="booking.duplicate_blocked").order_by(AuditLog.id.desc()).first()
        assert duplicate_entry is not None
        assert duplicate_entry.actor_id == seeker_id
        assert duplicate_entry.metadata_json["conflicting_booking_id"] == booking_id


def test_dispute_and_kyc_events_are_audited(app, client, register_user, auth_headers, image_upload):
    admin, admin_token = register_user("seeker", email="admin@example.com")
    provider, provider_token = register_user("provider", email="kyc-provider@example.com")
    seeker, seeker_token = register_user("seeker", email="dispute-seeker@example.com")
    provider_id, _, skill_id = _seed_skill(app, provider["email"], seeker["email"])

    with app.app_context():
        app.config["ADMIN_EMAIL"] = admin["email"]
        booking = Booking(
            seeker_id=User.query.filter_by(email=seeker["email"]).first().id,
            provider_id=provider_id,
            skill_id=skill_id,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            duration_minutes=60,
            price=1200,
            status=BookingStatus.CONFIRMED,
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

    kyc_response = client.post(
        "/api/kyc/upload",
        headers=auth_headers(provider_token),
        data={
            "doc_type": "id_front",
            "file": image_upload("kyc-front.jpg"),
        },
    )
    assert kyc_response.status_code == 200

    with app.app_context():
        kyc_entry = AuditLog.query.filter_by(event_type="kyc.document_uploaded").order_by(AuditLog.id.desc()).first()
        assert kyc_entry is not None
        assert kyc_entry.actor_id == provider_id
        assert kyc_entry.metadata_json["doc_type"] == "id_front"

    approve_response = client.post(
        f"/api/admin/kyc/{provider_id}/approve",
        headers=auth_headers(admin_token),
    )
    assert approve_response.status_code == 200

    with app.app_context():
        approve_entry = AuditLog.query.filter_by(event_type="kyc.approved", target_id=provider_id).order_by(AuditLog.id.desc()).first()
        assert approve_entry is not None
        assert approve_entry.actor_id == admin["id"]

    dispute_response = client.post(
        "/api/ops/disputes",
        headers=auth_headers(seeker_token),
        json={
            "booking_id": booking_id,
            "category": "QUALITY",
            "description": "Work not completed",
        },
    )
    assert dispute_response.status_code == 201
    dispute_id = dispute_response.get_json()["id"]

    with app.app_context():
        raised_entry = AuditLog.query.filter_by(event_type="dispute.raised", target_id=dispute_id).first()
        assert raised_entry is not None
        assert raised_entry.actor_id == User.query.filter_by(email=seeker["email"]).first().id

    resolve_response = client.patch(
        f"/api/ops/disputes/{dispute_id}",
        headers=auth_headers(admin_token),
        json={
            "status": "RESOLVED",
            "resolution_notes": "Refund approved",
            "refund_amount": 400,
        },
    )
    assert resolve_response.status_code == 200

    with app.app_context():
        resolved_entry = AuditLog.query.filter_by(event_type="dispute.resolved", target_id=dispute_id).order_by(AuditLog.id.desc()).first()
        assert resolved_entry is not None
        assert resolved_entry.metadata_json["outcome"] == "RESOLVED"
        assert resolved_entry.metadata_json["refund_amount"] == 400.0
