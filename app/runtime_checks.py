from flask import Flask


def _assert_redis_connectivity(url: str, label: str) -> None:
    try:
        import redis
    except ImportError as exc:
        raise RuntimeError("redis package is required outside development") from exc

    try:
        client = redis.Redis.from_url(url)
        if not client.ping():
            raise RuntimeError(f"{label} is unreachable")
    except Exception as exc:
        raise RuntimeError(f"{label} is unreachable") from exc


def validate_runtime_config(app: Flask) -> None:
    env = (app.config.get("ENV") or "development").lower()
    provider = (app.config.get("PAYMENT_PROVIDER") or "").lower()
    mode = (app.config.get("PAYMENT_MODE") or "").lower()
    wallet_provider = (app.config.get("WALLET_TOPUP_PROVIDER") or "mock").lower()

    if env in {"staging", "production"}:
        if app.debug or app.testing:
            raise RuntimeError("debug/testing must be disabled outside development")
        if app.config.get("ALLOW_UNSAFE_WERKZEUG"):
            raise RuntimeError("ALLOW_UNSAFE_WERKZEUG must be false outside development")
        if app.config.get("ALLOW_MOCK_PAYMENTS"):
            raise RuntimeError("mock payments must be disabled outside development")
        if mode != "real":
            raise RuntimeError("PAYMENT_MODE must be 'real' outside development")
        if provider != "stripe":
            raise RuntimeError("PAYMENT_PROVIDER must be 'stripe' outside development")
        if not app.config.get("STRIPE_SECRET_KEY"):
            raise RuntimeError("STRIPE_SECRET_KEY is required outside development")
        if not app.config.get("STRIPE_WEBHOOK_SECRET"):
            raise RuntimeError("STRIPE_WEBHOOK_SECRET is required outside development")
        if wallet_provider not in {"disabled", "stripe"}:
            raise RuntimeError("WALLET_TOPUP_PROVIDER must be 'disabled' or 'stripe' outside development")
        if app.config.get("FEATURE_WALLET", True) and wallet_provider == "stripe":
            if not app.config.get("STRIPE_SECRET_KEY"):
                raise RuntimeError("STRIPE_SECRET_KEY is required when wallet top-ups use Stripe")
            if not app.config.get("STRIPE_WEBHOOK_SECRET"):
                raise RuntimeError("STRIPE_WEBHOOK_SECRET is required when wallet top-ups use Stripe")
        if not app.config.get("REDIS_URL"):
            raise RuntimeError("REDIS_URL is required outside development")
        if not app.config.get("SOCKETIO_MESSAGE_QUEUE"):
            raise RuntimeError("SOCKETIO_MESSAGE_QUEUE is required outside development")
        _assert_redis_connectivity(app.config["REDIS_URL"], "REDIS_URL")
        _assert_redis_connectivity(app.config["SOCKETIO_MESSAGE_QUEUE"], "SOCKETIO_MESSAGE_QUEUE")

        scan_mode = (app.config.get("CHAT_ATTACHMENT_SCAN_MODE") or "").lower()
        if scan_mode not in {"basic", "clamav"}:
            raise RuntimeError("CHAT_ATTACHMENT_SCAN_MODE must be 'basic' or 'clamav' outside development")
        if not app.config.get("CHAT_ATTACHMENT_REQUIRE_SCAN"):
            raise RuntimeError("CHAT_ATTACHMENT_REQUIRE_SCAN must be enabled outside development")
        if scan_mode == "clamav" and not app.config.get("CLAMAV_HOST"):
            raise RuntimeError("CLAMAV_HOST is required when CHAT_ATTACHMENT_SCAN_MODE=clamav")

    if env == "production":
        if app.config.get("STRIPE_API_MODE") != "live":
            raise RuntimeError("STRIPE_API_MODE must be 'live' in production")
        if app.config.get("STORAGE_BACKEND") == "local":
            raise RuntimeError("STORAGE_BACKEND cannot be 'local' in production")
