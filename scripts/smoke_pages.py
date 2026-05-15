import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app


class SmokePagesConfig:
    ENV = "development"
    FLASK_ENV = "development"
    TESTING = True
    SECRET_KEY = os.getenv("SMOKE_SECRET_KEY", "smoke-pages-secret-1234567890")
    JWT_SECRET_KEY = os.getenv("SMOKE_JWT_SECRET_KEY", "smoke-pages-jwt-secret-1234567890")
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = "tmp_uploads"
    RATELIMIT_ENABLED = False
    RATELIMIT_STORAGE_URI = "memory://"
    SOCKETIO_MESSAGE_QUEUE = None
    SOCKETIO_CORS_ALLOWED_ORIGINS = "*"
    CORS_ALLOWED_ORIGINS = ""
    ALLOW_UNSAFE_WERKZEUG = True
    PAYMENT_PROVIDER = "mock"
    PAYMENT_MODE = "mock"
    ALLOW_MOCK_PAYMENTS = True


def main():
    app = create_app(SmokePagesConfig)
    client = app.test_client()
    pages = [
        "/settings",
        "/account",
        "/messages",
        "/wallet",
        "/payment-history",
        "/notifications",
    ]
    for path in pages:
        response = client.get(path)
        assert response.status_code == 200, f"{path} -> {response.status_code}"
    print("page smoke verification passed")


if __name__ == "__main__":
    main()
