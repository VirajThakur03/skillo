from wsgi import app, socketio

import os
from flask_migrate import upgrade


def should_run_migrations():
    default = "true" if app.config.get("ENV") == "development" else "false"
    return os.getenv("RUN_MIGRATIONS_ON_START", default).lower() == "true"


if __name__ == "__main__":
    if should_run_migrations():
        with app.app_context():
            try:
                upgrade()
                app.logger.info("database migrations applied on startup")
            except Exception as exc:  # pragma: no cover - startup safety net
                app.logger.warning("migration on startup skipped: %s", exc)
    socketio.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        allow_unsafe_werkzeug=bool(app.config.get("ALLOW_UNSAFE_WERKZEUG", False)),
        debug=bool(app.config.get("DEBUG", False)),
    )
