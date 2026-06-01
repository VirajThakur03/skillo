from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.extensions import db
from app.models import Booking, BookingStatus, KycStatus, Skill, User, VerificationStatus


class DashboardSmokeConfig:
    ENV = "development"
    FLASK_ENV = "development"
    TESTING = True
    SECRET_KEY = os.getenv("SMOKE_SECRET_KEY", "smoke-secret-key-1234567890-AB")
    JWT_SECRET_KEY = os.getenv("SMOKE_JWT_SECRET_KEY", "smoke-jwt-secret-key-1234567890-AB")
    SQLALCHEMY_DATABASE_URI = "sqlite:///smoke_dashboard_pages.db"
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
            "password": "secret123",  # pragma: allowlist secret
            "role": role,
        },
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def main():
    app = create_app(DashboardSmokeConfig)
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

    provider = _register(client, "Dashboard Provider", "dashboard-page-provider@example.com", "provider")
    seeker = _register(client, "Dashboard Seeker", "dashboard-page-seeker@example.com", "seeker")

    with app.app_context():
        provider_record = db.session.get(User, provider["user"]["id"])
        provider_record.verification_status = VerificationStatus.completed
        provider_record.is_verified = True
        provider_record.kyc_status = KycStatus.pending
        skill = Skill(
            provider_id=provider_record.id,
            title="Cleaning",
            description="Home cleaning",
            price=Decimal("1000.00"),
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()
        booking = Booking(
            seeker_id=seeker["user"]["id"],
            provider_id=provider_record.id,
            skill_id=skill.id,
            scheduled_at=(datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None),
            duration_minutes=60,
            price=Decimal("1000.00"),
            amount_payable=Decimal("1000.00"),
            currency="INR",
            status=BookingStatus.PENDING,
        )
        db.session.add(booking)
        db.session.commit()

    provider_page = client.get("/provider/dashboard")
    assert provider_page.status_code == 200
    provider_html = provider_page.get_data(as_text=True)
    assert "providerActionCenter" in provider_html
    assert "Open KYC center" in provider_html

    seeker_page = client.get("/my-bookings")
    assert seeker_page.status_code == 200
    seeker_html = seeker_page.get_data(as_text=True)
    assert "bookingFilters" in seeker_html
    assert "bookingSearch" in seeker_html

    provider_api = client.get(
        "/api/provider/dashboard",
        headers={"Authorization": "Bearer " + provider["access_token"]},
    )
    assert provider_api.status_code == 200, provider_api.get_json()
    assert provider_api.get_json()["recommended_actions"]

    seeker_api = client.get(
        "/api/bookings/my",
        headers={"Authorization": "Bearer " + seeker["access_token"]},
    )
    assert seeker_api.status_code == 200, seeker_api.get_json()

    print("dashboard page smoke verification passed")


if __name__ == "__main__":
    main()
