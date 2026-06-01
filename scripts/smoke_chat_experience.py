from datetime import datetime, timedelta, timezone
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.extensions import db, socketio
from app.models import Booking, BookingStatus, PaymentStatus, Skill, User, VerificationStatus


class SmokeChatConfig:
    ENV = "development"
    FLASK_ENV = "development"
    TESTING = True
    SECRET_KEY = os.getenv("SMOKE_SECRET_KEY", "smoke-secret-key-1234567890-AB")
    JWT_SECRET_KEY = os.getenv("SMOKE_JWT_SECRET_KEY", "smoke-jwt-secret-key-1234567890-AB")
    SQLALCHEMY_DATABASE_URI = "sqlite:///smoke_chat_experience.db"
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
    AUTO_SYNC_SCHEMA = False


def _register(client, name, email, role):
    response = client.post(
        "/api/auth/register",
        json={
            "name": name,
            "email": email,
            "password": "secret123",  # pragma: allowlist secret
            "role": role,
        },
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _auth(token):
    return {"Authorization": "Bearer " + token}


def main():
    app = create_app(SmokeChatConfig)
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

    provider = _register(client, "Chat Provider", "chat-provider@example.com", "provider")
    seeker = _register(client, "Chat Seeker", "chat-seeker@example.com", "seeker")
    provider_token = provider["access_token"]
    seeker_token = seeker["access_token"]

    with app.app_context():
        provider_record = db.session.get(User, provider["user"]["id"])
        provider_record.is_verified = True
        provider_record.verification_status = VerificationStatus.completed
        db.session.commit()

    profile = client.post(
        "/api/provider/profile",
        headers=_auth(provider_token),
        json={
            "name": "Chat Provider",
            "phone": "9999999994",
            "skill": "Electrician",
            "price": 800,
            "location": "Mumbai",
            "description": "Chat experience smoke",
        },
    )
    assert profile.status_code == 200, profile.get_json()
    skill_id = profile.get_json()["skill_id"]

    future_schedule = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0).isoformat()
    booking = client.post(
        "/api/bookings",
        headers=_auth(seeker_token),
        json={
            "skill_id": skill_id,
            "provider_id": provider["user"]["id"],
            "scheduled_at": future_schedule,
            "duration_minutes": 60,
        },
    )
    assert booking.status_code == 201, booking.get_json()
    booking_id = booking.get_json()["id"]

    seeker_socket = socketio.test_client(app, flask_test_client=app.test_client(), auth={"token": seeker_token})
    provider_socket = socketio.test_client(app, flask_test_client=app.test_client(), auth={"token": provider_token})
    assert seeker_socket.is_connected()
    assert provider_socket.is_connected()

    seeker_socket.emit("join", {"room": f"booking_{booking_id}"})
    provider_socket.emit("join", {"room": f"booking_{booking_id}"})
    seeker_socket.get_received()
    provider_socket.get_received()

    seeker_socket.emit("heartbeat")
    provider_socket.emit("heartbeat")

    for idx in range(3):
      sent = client.post(
          f"/api/chat/room/booking_{booking_id}",
          headers=_auth(seeker_token),
          json={"content": f"Need update {idx}"},
      )
      assert sent.status_code == 201, sent.get_json()

    meta = client.get(
        f"/api/chat/room/booking_{booking_id}/meta",
        headers=_auth(seeker_token),
    )
    assert meta.status_code == 200, meta.get_json()
    assert meta.get_json()["other_party_name"] == "Chat Provider"
    assert meta.get_json()["other_party_online"] is True

    paginated = client.get(
        f"/api/chat/room/booking_{booking_id}?format=paginated&limit=2",
        headers=_auth(seeker_token),
    )
    assert paginated.status_code == 200, paginated.get_json()
    page_payload = paginated.get_json()
    assert len(page_payload["items"]) == 2
    assert page_payload["has_more"] is True
    assert page_payload["next_before_id"] is not None

    older = client.get(
        f"/api/chat/room/booking_{booking_id}?format=paginated&limit=2&before_id={page_payload['next_before_id']}",
        headers=_auth(seeker_token),
    )
    assert older.status_code == 200, older.get_json()

    searched = client.get(
        f"/api/chat/room/booking_{booking_id}?format=paginated&q=update 1",
        headers=_auth(seeker_token),
    )
    assert searched.status_code == 200, searched.get_json()
    assert len(searched.get_json()["items"]) == 1

    global_search = client.get(
        "/api/chat/search?q=update",
        headers=_auth(seeker_token),
    )
    assert global_search.status_code == 200, global_search.get_json()
    assert global_search.get_json()["items"], global_search.get_json()

    pdf_file = (io.BytesIO(b"%PDF-1.4 fake pdf"), "quote.pdf")
    upload = client.post(
        f"/api/chat/room/booking_{booking_id}/upload",
        headers=_auth(seeker_token),
        data={"file": pdf_file},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 201, upload.get_json()
    assert upload.get_json()["message_type"] == "file"
    assert "name=quote.pdf" in upload.get_json()["content"]

    rooms = client.get(
        "/api/chat/rooms?limit=10",
        headers=_auth(seeker_token),
    )
    assert rooms.status_code == 200, rooms.get_json()
    room_items = rooms.get_json()["items"]
    assert room_items[0]["room"] == f"booking_{booking_id}"
    assert room_items[0]["other_party_online"] is True

    print("chat experience smoke verification passed")


if __name__ == "__main__":
    main()
