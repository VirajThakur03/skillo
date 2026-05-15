import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)).strip())


class Config:
    ENV = os.getenv("ENV", os.getenv("FLASK_ENV", "development")).strip().lower()
    FLASK_ENV = ENV
    DEBUG = ENV == "development"
    TESTING = _env_bool("TESTING", False)
    _running_in_docker = bool(os.getenv("RUNNING_IN_DOCKER", "").strip())

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwt-secret")
    
    from datetime import timedelta
    # CSRF Note: Since JWTs are sent via Authorization header (not cookies), CSRF is inherently mitigated.
    # If cookie-based JWTs are ever implemented, enable flask-wtf CSRFProtect.
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=_env_int("JWT_ACCESS_TOKEN_HOURS", 24))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=_env_int("JWT_REFRESH_TOKEN_DAYS", 30))
    
    _db_url = os.getenv("DATABASE_URL", "sqlite:///dev.db")
    if not os.getenv("RUNNING_IN_DOCKER", "").strip() and "@db:" in _db_url:
        _db_url = _db_url.replace("@db:", "@localhost:")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL_LOCAL", _db_url)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": _env_int("DB_POOL_RECYCLE_SECONDS", 1800),
        "pool_size": _env_int("DB_POOL_SIZE", 10),
        "max_overflow": _env_int("DB_MAX_OVERFLOW", 20),
    }

    AUTO_SYNC_SCHEMA = _env_bool("AUTO_SYNC_SCHEMA", ENV == "development")
    RUN_MIGRATIONS_ON_START = _env_bool("RUN_MIGRATIONS_ON_START", ENV == "development")

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    STITCH_API_KEY = os.getenv("STITCH_API_KEY", "")

    _redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    if not _running_in_docker and "redis://redis:" in _redis_url:
        _redis_url = _redis_url.replace("redis://redis:", "redis://localhost:")
    REDIS_URL = os.getenv("REDIS_URL_LOCAL", _redis_url)
    SOCKETIO_ASYNC_MODE = os.getenv("SOCKETIO_ASYNC_MODE", "threading")
    _socketio_message_queue = os.getenv("SOCKETIO_MESSAGE_QUEUE", REDIS_URL)
    if not _running_in_docker and "redis://redis:" in _socketio_message_queue:
        _socketio_message_queue = _socketio_message_queue.replace("redis://redis:", "redis://localhost:")
    if ENV == "development" and not _running_in_docker and not os.getenv("SOCKETIO_MESSAGE_QUEUE_LOCAL"):
        _socketio_message_queue = None
    SOCKETIO_MESSAGE_QUEUE = os.getenv("SOCKETIO_MESSAGE_QUEUE_LOCAL", _socketio_message_queue)
    SOCKETIO_CHANNEL = os.getenv("SOCKETIO_CHANNEL", "sklio")
    SOCKETIO_CORS_ALLOWED_ORIGINS = os.getenv("SOCKETIO_CORS_ALLOWED_ORIGINS", "*")

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_API_REQUESTS = _env_bool("LOG_API_REQUESTS", ENV != "production")
    ERROR_MONITOR_DSN = os.getenv("ERROR_MONITOR_DSN", "")

    UPLOAD_FOLDER = os.getenv(
        "UPLOAD_FOLDER",
        str(Path.cwd() / "uploads" / "documents"),
    )
    MAX_CONTENT_LENGTH = 30 * 1024 * 1024
    STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").strip().lower()
    DOCUMENT_RETENTION_DAYS = _env_int("DOCUMENT_RETENTION_DAYS", 30)
    KEEP_FAILED_VERIFICATION_MEDIA = _env_bool("KEEP_FAILED_VERIFICATION_MEDIA", False)
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
    S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
    CHAT_ATTACHMENT_SCAN_MODE = os.getenv(
        "CHAT_ATTACHMENT_SCAN_MODE",
        "basic" if ENV == "development" else "clamav",
    ).strip().lower()
    CHAT_ATTACHMENT_REQUIRE_SCAN = _env_bool(
        "CHAT_ATTACHMENT_REQUIRE_SCAN",
        ENV != "development",
    )
    CHAT_ATTACHMENT_QUARANTINE_RETENTION_DAYS = _env_int(
        "CHAT_ATTACHMENT_QUARANTINE_RETENTION_DAYS",
        14,
    )
    CLAMAV_HOST = os.getenv("CLAMAV_HOST", "")
    CLAMAV_PORT = _env_int("CLAMAV_PORT", 3310)
    CLAMAV_TIMEOUT_SECONDS = _env_int("CLAMAV_TIMEOUT_SECONDS", 5)

    PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "mock").strip().lower()
    PAYMENT_MODE = os.getenv("PAYMENT_MODE", "mock").strip().lower()
    ALLOW_MOCK_PAYMENTS = _env_bool("ALLOW_MOCK_PAYMENTS", ENV == "development")
    WALLET_TOPUP_PROVIDER = os.getenv(
        "WALLET_TOPUP_PROVIDER",
        "mock" if ENV == "development" else "stripe",
    ).strip().lower()
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_API_MODE = os.getenv(
        "STRIPE_API_MODE",
        "live" if ENV == "production" else "test",
    ).strip().lower()
    STRIPE_CURRENCY = os.getenv("STRIPE_CURRENCY", "INR").strip().lower()

    # Defaults for payment URLs to prevent 500s when missing in .env
    _default_success = "/track/{booking_id}?checkout=success"
    _default_cancel = "/booking/{skill_id}?provider={provider_id}&checkout=cancelled"
    PAYMENT_SUCCESS_URL = os.getenv("PAYMENT_SUCCESS_URL", _default_success)
    PAYMENT_CANCEL_URL = os.getenv("PAYMENT_CANCEL_URL", _default_cancel)
    WALLET_TOPUP_SUCCESS_URL = os.getenv(
        "WALLET_TOPUP_SUCCESS_URL",
        "/wallet?topup=success",
    )
    WALLET_TOPUP_CANCEL_URL = os.getenv(
        "WALLET_TOPUP_CANCEL_URL",
        "/wallet?topup=cancelled",
    )
    
    # Simple validation for production
    if ENV == "production" and PAYMENT_MODE == "stripe" and not STRIPE_SECRET_KEY:
        import logging
        logging.getLogger("app").warning("STRIPE_SECRET_KEY is missing in production with Stripe enabled!")

    PLATFORM_GSTIN = os.getenv("PLATFORM_GSTIN", "")
    PLATFORM_SAC_CODE = os.getenv("PLATFORM_SAC_CODE", "998599")
    LEGAL_ENTITY_NAME = os.getenv("LEGAL_ENTITY_NAME", "Sklio Marketplace")
    LEGAL_ENTITY_ADDRESS = os.getenv("LEGAL_ENTITY_ADDRESS", "")

    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
    EMAIL_DELIVERY_BACKEND = os.getenv("EMAIL_DELIVERY_BACKEND", "log")
    EMAIL_FROM_ADDRESS = os.getenv("EMAIL_FROM_ADDRESS", "noreply@sklio.in")
    PUSH_DELIVERY_BACKEND = os.getenv("PUSH_DELIVERY_BACKEND", "log")
    WHATSAPP_ENABLED = _env_bool("WHATSAPP_ENABLED", False)

    FEATURE_AVAILABILITY_CALENDAR = _env_bool("FEATURE_AVAILABILITY_CALENDAR", True)
    FEATURE_PUSH_NOTIFICATIONS = _env_bool("FEATURE_PUSH_NOTIFICATIONS", False)
    FEATURE_EMAIL_NOTIFICATIONS = _env_bool("FEATURE_EMAIL_NOTIFICATIONS", False)
    FEATURE_PROMO_CODES = _env_bool("FEATURE_PROMO_CODES", True)
    FEATURE_REFERRAL_REWARDS = _env_bool("FEATURE_REFERRAL_REWARDS", True)
    FEATURE_WALLET = _env_bool("FEATURE_WALLET", True)
    FEATURE_WEEKLY_AVAILABILITY = _env_bool("FEATURE_WEEKLY_AVAILABILITY", True)
    FEATURE_CHAT_READ_RECEIPTS = _env_bool("FEATURE_CHAT_READ_RECEIPTS", True)
    FEATURE_PROVIDER_REPLY_REVIEW = _env_bool("FEATURE_PROVIDER_REPLY_REVIEW", True)
    FEATURE_JOB_POSTS = _env_bool("FEATURE_JOB_POSTS", ENV == "development")

    JOB_POST_OPEN_EXPIRY_HOURS = _env_int("JOB_POST_OPEN_EXPIRY_HOURS", 72)

    RATELIMIT_ENABLED = _env_bool("RATELIMIT_ENABLED", True)
    if ENV == "development" and not _running_in_docker:
        RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI_LOCAL", "memory://")
    else:
        _ratelimit_storage = os.getenv("RATELIMIT_STORAGE_URI", REDIS_URL)
        if not _running_in_docker and "redis://redis:" in _ratelimit_storage:
            _ratelimit_storage = _ratelimit_storage.replace("redis://redis:", "redis://localhost:")
        RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI_LOCAL", _ratelimit_storage)
    RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "300 per hour")
    AUTH_RATE_LIMIT = os.getenv("AUTH_RATE_LIMIT", "10 per minute")
    BOOKING_RATE_LIMIT = os.getenv("BOOKING_RATE_LIMIT", "20 per hour")
    PASSWORD_RESET_RATE_LIMIT = os.getenv("PASSWORD_RESET_RATE_LIMIT", "5 per hour")
    PAYMENT_RATE_LIMIT = os.getenv("PAYMENT_RATE_LIMIT", "20 per minute")
    WEBHOOK_RATE_LIMIT = os.getenv("WEBHOOK_RATE_LIMIT", "120 per minute")

    CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "")
    ALLOW_UNSAFE_WERKZEUG = _env_bool("ALLOW_UNSAFE_WERKZEUG", ENV == "development")

    SECURE_COOKIES = ENV != "development"
    SESSION_COOKIE_SECURE = SECURE_COOKIES
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PREFERRED_URL_SCHEME = "https" if ENV != "development" else "http"

    SECURITY_HSTS_SECONDS = _env_int("SECURITY_HSTS_SECONDS", 31536000)
    CONTENT_SECURITY_POLICY = os.getenv(
        "CONTENT_SECURITY_POLICY",
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://js.stripe.com https://checkout.razorpay.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://api.fontshare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdn.fontshare.com data:; "
        "img-src 'self' data: https:; connect-src 'self' https://api.stripe.com https://api.razorpay.com wss: ws:; "
        "frame-src https://js.stripe.com https://checkout.stripe.com https://checkout.razorpay.com; object-src 'none'; base-uri 'self'; "
        "frame-ancestors 'none';",
    )
    REFERRER_POLICY = os.getenv("REFERRER_POLICY", "strict-origin-when-cross-origin")
    PERMISSIONS_POLICY = os.getenv(
        "PERMISSIONS_POLICY",
        "geolocation=(self), microphone=(), camera=(self)",
    )

    JWT_ACCESS_TOKEN_EXPIRES_MINUTES = _env_int("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", 60)
    JWT_REFRESH_TOKEN_EXPIRES_DAYS = _env_int("JWT_REFRESH_TOKEN_EXPIRES_DAYS", 30)
    PASSWORD_RESET_TOKEN_TTL_SECONDS = _env_int("PASSWORD_RESET_TOKEN_TTL_SECONDS", 1800)

    ALLOWED_DOCUMENT_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}

    REFERRAL_BONUS_SEEKER = 50.0
    REFERRAL_BONUS_PROVIDER = 50.0
    PLATFORM_FEE_DEFAULT = 10.0

    LEGAL_LAST_UPDATED = os.getenv("LEGAL_LAST_UPDATED", "April 9, 2026")
    GRIEVANCE_OFFICER_NAME = os.getenv("GRIEVANCE_OFFICER_NAME", "Sklio Grievance Officer")
    GRIEVANCE_EMAIL = os.getenv("GRIEVANCE_EMAIL", "grievance@sklio.in")
    GRIEVANCE_PHONE = os.getenv("GRIEVANCE_PHONE", "+91 98765 43210")
