from sqlalchemy import text

from .extensions import db


def service_health(app):
    checks = {"database": False, "redis": False, "socketio_queue": False}

    try:
        db.session.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as exc:  # pragma: no cover - health reporting
        app.logger.warning("health.database.failed", extra={"error": str(exc)})

    redis_url = app.config.get("REDIS_URL")
    if redis_url:
        try:
            import redis

            client = redis.Redis.from_url(redis_url)
            checks["redis"] = bool(client.ping())
            checks["socketio_queue"] = checks["redis"]
        except Exception as exc:  # pragma: no cover - health reporting
            app.logger.warning("health.redis.failed", extra={"error": str(exc)})

    checks["status"] = "ok" if all(checks.values()) else "degraded"
    return checks
