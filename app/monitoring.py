import logging
import time
import uuid

from flask import g, request


def configure_observability(app):
    level_name = app.config.get("LOG_LEVEL", "INFO")
    level = getattr(logging, level_name, logging.INFO)

    for handler in app.logger.handlers:
        handler.setLevel(level)

    app.logger.setLevel(level)
    app.logger.propagate = False

    @app.before_request
    def start_request_timer():
        g.request_started_at = time.perf_counter()
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]

    @app.after_request
    def log_api_request(response):
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")

        should_log = (
            request.path.startswith("/api")
            and (
                response.status_code >= 400
                or app.config.get("LOG_API_REQUESTS", False)
            )
        )

        if should_log:
            duration_ms = round(
                (
                    time.perf_counter()
                    - getattr(g, "request_started_at", time.perf_counter())
                )
                * 1000,
                2,
            )
            app.logger.info(
                "api_request method=%s path=%s status=%s duration_ms=%s request_id=%s remote_addr=%s",
                request.method,
                request.path,
                response.status_code,
                duration_ms,
                getattr(g, "request_id", ""),
                request.headers.get("X-Forwarded-For", request.remote_addr),
            )

        return response
