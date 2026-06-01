import os

bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"
async_mode = os.getenv("SOCKETIO_ASYNC_MODE", "threading").strip().lower()
worker_class = os.getenv(
    "GUNICORN_WORKER_CLASS",
    "eventlet" if async_mode == "eventlet" else "gthread",
)
workers = int(os.getenv("WEB_CONCURRENCY", "1"))
threads = int(os.getenv("GUNICORN_THREADS", "100"))
worker_connections = int(os.getenv("WORKER_CONNECTIONS", "1000"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "100"))
accesslog = "-"
errorlog = "-"
capture_output = True
loglevel = os.getenv("LOG_LEVEL", "info").lower()
preload_app = False
reload = os.getenv("ENV", "development").strip().lower() == "development"

