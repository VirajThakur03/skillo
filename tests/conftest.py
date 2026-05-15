import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.extensions import db, socketio
from app.models import Booking, BookingStatus, Skill, User, VerificationStatus, KycStatus


@pytest.fixture()
def app(tmp_path):
    class TestConfig:
        ENV = "development"
        FLASK_ENV = "development"
        TESTING = True
        SECRET_KEY = "test-secret"  # pragma: allowlist secret
        JWT_SECRET_KEY = "22811bf5e29f2d3aee8c2d87f9cfd9c1f9c6af406ba56ecddc9b84ba26cf2aac"  # pragma: allowlist secret
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        UPLOAD_FOLDER = str(tmp_path / "uploads")
        MAX_CONTENT_LENGTH = 10 * 1024 * 1024
        ALLOWED_DOCUMENT_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}
        WHATSAPP_ENABLED = False
        PAYMENT_PROVIDER = "mock"
        PAYMENT_MODE = "mock"
        ALLOW_MOCK_PAYMENTS = True
        LOG_API_REQUESTS = False
        STORAGE_BACKEND = "local"
        DOCUMENT_RETENTION_DAYS = 30
        KEEP_FAILED_VERIFICATION_MEDIA = False
        PLATFORM_FEE_DEFAULT = 5.0
        RATELIMIT_ENABLED = False
        RATELIMIT_STORAGE_URI = "memory://"
        SOCKETIO_CORS_ALLOWED_ORIGINS = "*"
        AUTO_SYNC_SCHEMA = False
        ALLOW_UNSAFE_WERKZEUG = True

    app = create_app(TestConfig)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_headers():
    def _build(token):
        return {"Authorization": f"Bearer {token}"}

    return _build


@pytest.fixture()
def register_user(client):
    def _register(role, name=None, email=None, password="secret123"):  # pragma: allowlist secret
        role_name = role.lower()
        suffix = email or f"{role_name}-{datetime.now(timezone.utc).timestamp()}@example.com"
        payload = {
            "name": name or f"{role.title()} User",
            "email": suffix,
            "password": password,
            "role": role_name,
        }
        response = client.post("/api/auth/register", json=payload)
        assert response.status_code == 201, response.get_json()
        data = response.get_json()
        return data["user"], data["access_token"]

    return _register


@pytest.fixture()
def image_upload():
    def _image(filename="upload.jpg", color=(41, 128, 185)):
        image = Image.new("RGB", (320, 240), color)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        buffer.seek(0)
        return buffer, filename

    return _image


@pytest.fixture()
def video_upload():
    def _video(filename="verification.mp4"):
        return io.BytesIO(b"fake video bytes"), filename

    return _video


@pytest.fixture()
def future_schedule():
    return (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).replace(microsecond=0).isoformat()


@pytest.fixture()
def socket_client(app):
    clients = []

    def _connect(token=None):
        flask_client = app.test_client()
        auth = {"token": token} if token else None
        client = socketio.test_client(app, flask_test_client=flask_client, auth=auth)
        clients.append(client)
        return client

    yield _connect

    for client in clients:
        if client.is_connected():
            client.disconnect()


@pytest.fixture()
def booking_with_missing_relations(app, register_user):
    seeker, seeker_token = register_user(
        "seeker",
        name="Missing Relation Seeker",
        email="missing-relations-seeker@example.com",
    )
    provider, _ = register_user(
        "provider",
        name="Missing Relation Provider",
        email="missing-relations-provider@example.com",
    )

    with app.app_context():
        provider_record = db.session.get(User, provider["id"])
        provider_record.verification_status = VerificationStatus.completed
        provider_record.kyc_status = KycStatus.approved
        provider_record.is_verified = True
        skill = Skill(
            provider_id=provider_record.id,
            title="Temporary Skill",
            description="Fixture skill",
            price=500,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()
        booking = Booking(
            seeker_id=seeker["id"],
            provider_id=provider_record.id,
            skill_id=skill.id,
            scheduled_at=(datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None),
            duration_minutes=60,
            price=500,
            currency="INR",
            status=BookingStatus.PENDING,
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id
        provider_id = provider_record.id
        skill_id = skill.id

        db.session.execute(
            text("UPDATE bookings SET provider_id = :provider_id, skill_id = :skill_id WHERE id = :booking_id"),
            {
                "provider_id": provider_id + 99999,
                "skill_id": skill_id + 99999,
                "booking_id": booking_id,
            },
        )
        db.session.commit()

    return {
        "booking_id": booking_id,
        "seeker_id": seeker["id"],
        "token": seeker_token,
    }
