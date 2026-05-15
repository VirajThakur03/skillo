import os

if os.getenv("SOCKETIO_ASYNC_MODE", "threading").strip().lower() == "eventlet":
    import eventlet

    eventlet.monkey_patch()

from pathlib import Path
from flask import Flask, abort, jsonify, request, send_from_directory, render_template
import sentry_sdk

from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from .config import Config
from .extensions import socketio, db, migrate, bcrypt, jwt, limiter
from .health import service_health
from .logging_config import setup_logging
from .monitoring import configure_observability
from .routes import register_routes
from .runtime_checks import validate_runtime_config
from .schema_bootstrap import ensure_runtime_schema


def _socketio_cors_origins(raw_value):
    if raw_value is None:
        return "*"
    if isinstance(raw_value, (list, tuple, set)):
        return list(raw_value)

    normalized = str(raw_value).strip()
    if not normalized or normalized == "*":
        return "*"

    return [item.strip() for item in normalized.split(",") if item.strip()]


def _allowed_cors_origins(raw_value):
    normalized = (raw_value or "").strip()
    if not normalized:
        return set()
    return {item.strip() for item in normalized.split(",") if item.strip()}


def scrub_sensitive_data(event, hint):
    if "request" in event:
        event["request"].pop("data", None)
        headers = event["request"].get("headers", {})
        headers.pop("Authorization", None)
        headers.pop("Cookie", None)
    return event


def _apply_security_headers(app):
    allowed_origins = _allowed_cors_origins(app.config.get("CORS_ALLOWED_ORIGINS"))
    env = app.config.get("ENV", "development")

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", app.config.get("REFERRER_POLICY"))
        response.headers.setdefault("Permissions-Policy", app.config.get("PERMISSIONS_POLICY"))
        response.headers.setdefault("Content-Security-Policy", app.config.get("CONTENT_SECURITY_POLICY"))
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")

        if env != "development":
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={app.config.get('SECURITY_HSTS_SECONDS', 31536000)}; includeSubDomains; preload",
            )

        origin = request.headers.get("Origin")
        if origin and (origin in allowed_origins or "*" in allowed_origins):
            response.headers["Access-Control-Allow-Origin"] = origin if origin in allowed_origins else "*"
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Request-ID"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Credentials"] = "true"

        return response


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)
    app.debug = bool(app.config.get("DEBUG", False))
    app.testing = bool(app.config.get("TESTING", False))

    setup_logging()
    validate_runtime_config(app)
    app.logger.info("Sklio backend starting")

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)
    limiter.init_app(app)

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload: dict) -> bool:
        from .models import TokenBlocklist
        jti = jwt_payload["jti"]
        token = db.session.query(TokenBlocklist.id).filter_by(jti=jti).scalar()
        return token is not None

    socketio.init_app(
        app,
        cors_allowed_origins=_socketio_cors_origins(
            app.config.get("SOCKETIO_CORS_ALLOWED_ORIGINS")
        ),
        message_queue=app.config.get("SOCKETIO_MESSAGE_QUEUE"),
        channel=app.config.get("SOCKETIO_CHANNEL"),
    )

    sentry_sdk.init(
        dsn=os.getenv("SENTRY_DSN") or app.config.get("ERROR_MONITOR_DSN"),
        integrations=[FlaskIntegration(), SqlalchemyIntegration()],
        traces_sample_rate=0.1,
        profiles_sample_rate=0.05,
        environment=app.config.get("ENV", "development"),
        send_default_pii=False,
        before_send=scrub_sensitive_data,
    )

    configure_observability(app)
    _apply_security_headers(app)

    with app.app_context():
        ensure_runtime_schema(app)

    register_routes(app)

    @app.route("/ping")
    def ping():
        return {"status": "ok", "service": "sklio-backend"}

    @app.route("/health")
    def health():
        checks = service_health(app)
        status_code = 200 if checks["status"] == "ok" else 503
        return {
            "status": checks["status"],
            "service": "sklio-backend",
            "environment": app.config.get("ENV", "development"),
            "checks": checks,
        }, status_code

    @app.route("/uploads/<path:filename>")
    def uploaded_file(filename):
        normalized = Path(filename).as_posix().lstrip("/")
        if not normalized.startswith("invoices/"):
            abort(404)

        upload_root = Path(app.config["UPLOAD_FOLDER"]).resolve()
        target = (upload_root / normalized).resolve()
        try:
            target.relative_to(upload_root)
        except ValueError:
            abort(404)
        if not target.exists() or not target.is_file():
            abort(404)
        return send_from_directory(upload_root, normalized)

    @app.errorhandler(404)
    def page_not_found(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "not found"}), 404
        return render_template("404.html"), 404

    @app.errorhandler(413)
    def request_too_large(_error):
        max_mb = int(app.config.get("MAX_CONTENT_LENGTH", 0) / (1024 * 1024))
        return jsonify({
            "error": "file too large",
            "max_mb": max_mb,
        }), 413

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):  # pragma: no cover - broad safety net
        if getattr(error, "code", None) == 404:
            return page_not_found(error)
        if getattr(error, "code", None) and isinstance(getattr(error, "code"), int):
            return error
        app.logger.exception("request.unhandled_error", extra={"error": str(error)})
        if request.path.startswith("/api/"):
            payload = {"error": "internal server error"}
            if app.config.get("ENV") == "development":
                payload["details"] = str(error)
            return jsonify(payload), 500
        return render_template("500.html"), 500

    @app.after_request
    def add_cache_headers(response):
        if request.path.startswith("/static/"):
            if app.config.get("ENV") == "production":
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "no-store"
        return response

    if app.config.get("ENV") == "development":
        @app.post("/api/test-error")
        def test_error():
            raise RuntimeError("deliberate test error")

    return app
