import logging
import os

from flask import has_request_context, request

try:
    try:
        from pythonjsonlogger import json as jsonlogger
    except ImportError:
        from pythonjsonlogger import jsonlogger
except ImportError:  # pragma: no cover
    jsonlogger = None


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        record.environment = os.getenv("ENV", os.getenv("FLASK_ENV", "development"))
        record.service = "sklio-backend"
        if has_request_context():
            record.request_id = request.headers.get("X-Request-ID", "")
            record.remote_addr = request.headers.get("X-Forwarded-For", request.remote_addr)
            record.path = request.path
            record.method = request.method
        else:
            record.request_id = ""
            record.remote_addr = ""
            record.path = ""
            record.method = ""
        return True


def setup_logging():
    logger = logging.getLogger()
    logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.addFilter(RequestContextFilter())

    if jsonlogger:
        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(environment)s %(service)s %(request_id)s %(remote_addr)s %(path)s %(method)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s env=%(environment)s request_id=%(request_id)s path=%(path)s"
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO if os.getenv("ENV", os.getenv("FLASK_ENV", "development")) == "production" else logging.DEBUG)
    return logger


log = setup_logging()
