from datetime import datetime, timedelta, timezone
from decimal import Decimal
from time import perf_counter
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.extensions import db
from app.models import Booking, BookingStatus, KycStatus, Skill, User, VerificationStatus


class BenchmarkConfig:
    ENV = "development"
    FLASK_ENV = "development"
    TESTING = True
    SECRET_KEY = os.getenv("SMOKE_SECRET_KEY", "smoke-secret-key-1234567890-AB")
    JWT_SECRET_KEY = os.getenv("SMOKE_JWT_SECRET_KEY", "smoke-jwt-secret-key-1234567890-AB")
    SQLALCHEMY_DATABASE_URI = "sqlite:///benchmark_dashboard_queries.db"
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
        json={"name": name, "email": email, "password": "secret123", "role": role},  # pragma: allowlist secret
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _seed_dataset(app, count):
    client = app.test_client()
    provider = _register(client, f"Bench Provider {count}", f"bench-provider-{count}@example.com", "provider")
    seeker = _register(client, f"Bench Seeker {count}", f"bench-seeker-{count}@example.com", "seeker")

    with app.app_context():
        provider_record = db.session.get(User, provider["user"]["id"])
        provider_record.verification_status = VerificationStatus.completed
        provider_record.is_verified = True
        provider_record.kyc_status = KycStatus.approved
        skill = Skill(
            provider_id=provider_record.id,
            title="Benchmark Service",
            description="Benchmark",
            price=Decimal("750.00"),
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()

        for index in range(count):
            status = [BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.COMPLETED, BookingStatus.CANCELLED][index % 4]
            db.session.add(
                Booking(
                    seeker_id=seeker["user"]["id"],
                    provider_id=provider_record.id,
                    skill_id=skill.id,
                    scheduled_at=(datetime.now(timezone.utc) + timedelta(days=(index % 14) + 1)).replace(tzinfo=None),
                    duration_minutes=60,
                    price=Decimal("750.00"),
                    amount_payable=Decimal("750.00"),
                    currency="INR",
                    status=status,
                )
            )
        db.session.commit()

    return provider["access_token"], seeker["access_token"]


def _measure(client, path, token, rounds=5):
    durations = []
    for _ in range(rounds):
        start = perf_counter()
        response = client.get(path, headers={"Authorization": "Bearer " + token})
        durations.append((perf_counter() - start) * 1000)
        assert response.status_code == 200, response.get_json()
    return durations


def main():
    app = create_app(BenchmarkConfig)
    with app.app_context():
        db.drop_all()
        db.create_all()

    client = app.test_client()
    for count in (100, 500, 1000):
        provider_token, seeker_token = _seed_dataset(app, count)
        provider_durations = _measure(client, "/api/provider/dashboard?limit=500", provider_token)
        seeker_durations = _measure(client, "/api/bookings/my?limit=500", seeker_token)
        print(
            f"{count} bookings | provider avg={sum(provider_durations)/len(provider_durations):.2f}ms "
            f"p95={max(provider_durations):.2f}ms | seeker avg={sum(seeker_durations)/len(seeker_durations):.2f}ms "
            f"p95={max(seeker_durations):.2f}ms"
        )


if __name__ == "__main__":
    main()
