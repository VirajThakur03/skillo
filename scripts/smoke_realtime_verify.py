from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.extensions import db, socketio
from app.models import BookingStatus, KycStatus, Message, Skill, User, VerificationStatus


class SmokeRealtimeConfig:
    ENV = "development"
    FLASK_ENV = "development"
    TESTING = True
    SECRET_KEY = os.getenv("SMOKE_SECRET_KEY", "smoke-secret-key-1234567890-AB")
    JWT_SECRET_KEY = os.getenv("SMOKE_JWT_SECRET_KEY", "smoke-jwt-secret-key-1234567890-AB")
    SQLALCHEMY_DATABASE_URI = "sqlite:///smoke_realtime.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = "tmp_uploads"
    PAYMENT_PROVIDER = "mock"
    PAYMENT_MODE = "mock"
    ALLOW_MOCK_PAYMENTS = True
    RATELIMIT_ENABLED = False
    RATELIMIT_STORAGE_URI = "memory://"
    SOCKETIO_MESSAGE_QUEUE = None
    SOCKETIO_CORS_ALLOWED_ORIGINS = "*"
    CORS_ALLOWED_ORIGINS = ""
    ALLOW_UNSAFE_WERKZEUG = True
    WHATSAPP_ENABLED = False


def _register(client, name, email, role):
    response = client.post(
        "/api/auth/register",
        json={
            "name": name,
            "email": email,
            "password": "secret123",
            "role": role,
        },
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _event_payload(event):
    args = event.get("args")
    if isinstance(args, list):
        return args[0] if args else {}
    return args or {}


def main():
    app = create_app(SmokeRealtimeConfig)
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

    provider = _register(client, "Realtime Provider", "realtime-provider@example.com", "provider")
    seeker = _register(client, "Realtime Seeker", "realtime-seeker@example.com", "seeker")
    provider_token = provider["access_token"]
    seeker_token = seeker["access_token"]

    with app.app_context():
        provider_record = db.session.get(User, provider["user"]["id"])
        provider_record.is_verified = True
        provider_record.verification_status = VerificationStatus.completed
        provider_record.kyc_status = KycStatus.approved
        provider_record.phone = "9999999998"
        seeker_record = db.session.get(User, seeker["user"]["id"])
        seeker_record.phone = "9999999997"
        db.session.commit()

    profile = client.post(
        "/api/provider/profile",
        headers={"Authorization": "Bearer " + provider_token},
        json={
            "name": "Realtime Provider",
            "phone": "9999999998",
            "skill": "Electrician",
            "price": 800,
            "location": "Mumbai",
            "description": "Realtime smoke check",
        },
    )
    assert profile.status_code == 200, profile.get_json()
    skill_id = profile.get_json()["skill_id"]

    future_schedule = (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).replace(microsecond=0).isoformat()

    booking = client.post(
        "/api/bookings",
        headers={"Authorization": "Bearer " + seeker_token},
        json={
            "skill_id": skill_id,
            "provider_id": provider["user"]["id"],
            "scheduled_at": future_schedule,
            "duration_minutes": 60,
        },
    )
    assert booking.status_code == 201, booking.get_json()
    booking_id = booking.get_json()["id"]

    seeker_socket = socketio.test_client(
        app,
        flask_test_client=app.test_client(),
        auth={"token": seeker_token},
    )
    provider_socket = socketio.test_client(
        app,
        flask_test_client=app.test_client(),
        auth={"token": provider_token},
    )
    assert seeker_socket.is_connected()
    assert provider_socket.is_connected()

    seeker_socket.emit("join", {"room": f"booking_{booking_id}"})
    provider_socket.emit("join", {"room": f"booking_{booking_id}"})
    seeker_socket.get_received()
    provider_socket.get_received()

    seeker_socket.emit(
        "message",
        {
            "room": f"booking_{booking_id}",
            "message": "Please call before arrival.",
            "token": seeker_token,
        },
    )
    provider_events = provider_socket.get_received()
    assert any(
        event["name"] == "message"
        and _event_payload(event).get("content") == "Please call before arrival."
        for event in provider_events
    ), provider_events

    payment = client.post(
        f"/api/bookings/{booking_id}/pay",
        headers={"Authorization": "Bearer " + seeker_token},
        json={"payment_ref": f"SMOKE-{booking_id}"},
    )
    assert payment.status_code == 200, payment.get_json()

    location = client.post(
        f"/api/bookings/{booking_id}/location",
        headers={"Authorization": "Bearer " + provider_token},
        json={"latitude": 19.076, "longitude": 72.8777},
    )
    assert location.status_code == 200, location.get_json()

    seeker_events = seeker_socket.get_received()
    assert any(event["name"] == "worker_location_update" for event in seeker_events), seeker_events

    booking_state = client.get(
        f"/api/bookings/{booking_id}",
        headers={"Authorization": "Bearer " + seeker_token},
    )
    assert booking_state.status_code == 200, booking_state.get_json()
    assert booking_state.get_json()["status"] == BookingStatus.IN_PROGRESS.value, booking_state.get_json()

    timeline = client.get(
        f"/api/bookings/{booking_id}/timeline",
        headers={"Authorization": "Bearer " + seeker_token},
    )
    assert timeline.status_code == 200, timeline.get_json()
    timeline_events = timeline.get_json()["events"]
    assert any(event["event_type"] == "requested" for event in timeline_events), timeline_events
    assert any(event["event_type"] == "location_shared" for event in timeline_events), timeline_events

    with app.app_context():
        message = Message.query.filter_by(room=f"booking_{booking_id}").first()
        assert message is not None
        assert message.content == "Please call before arrival."

    complete = client.post(
        f"/api/bookings/{booking_id}/complete",
        headers={"Authorization": "Bearer " + provider_token},
    )
    assert complete.status_code == 200, complete.get_json()

    seeker_socket.disconnect()
    provider_socket.disconnect()
    print("realtime smoke verification passed")


if __name__ == "__main__":
    main()
