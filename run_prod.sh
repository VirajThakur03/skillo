#!/bin/sh
set -eu

export ENV="${ENV:-production}"
export FLASK_ENV="${FLASK_ENV:-$ENV}"
export PAYMENT_PROVIDER="${PAYMENT_PROVIDER:-stripe}"
export PAYMENT_MODE="${PAYMENT_MODE:-real}"
export ALLOW_MOCK_PAYMENTS="${ALLOW_MOCK_PAYMENTS:-false}"
export ALLOW_UNSAFE_WERKZEUG="${ALLOW_UNSAFE_WERKZEUG:-false}"
export SOCKETIO_ASYNC_MODE="${SOCKETIO_ASYNC_MODE:-threading}"
export GUNICORN_WORKER_CLASS="${GUNICORN_WORKER_CLASS:-gthread}"
export GUNICORN_THREADS="${GUNICORN_THREADS:-100}"

if [ "${RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
  flask db upgrade
fi

exec gunicorn --config gunicorn.conf.py wsgi:app
