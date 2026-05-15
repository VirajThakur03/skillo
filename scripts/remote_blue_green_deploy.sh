#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${1:?environment required}"
IMAGE_NAME="${2:?image required}"
APP_ROOT="${APP_ROOT:-/opt/sklio}"
HEALTH_PATH="${HEALTH_PATH:-/health}"
CURRENT_COLOR_FILE="$APP_ROOT/current_color.$ENV_NAME"
BLUE_PORT="${BLUE_PORT:-5001}"
GREEN_PORT="${GREEN_PORT:-5002}"

mkdir -p "$APP_ROOT"
cd "$APP_ROOT"

if [ ! -f docker-compose.prod.yml ]; then
  echo "docker-compose.prod.yml must exist in $APP_ROOT" >&2
  exit 1
fi

if [ ! -f .env.runtime ]; then
  echo ".env.runtime must exist in $APP_ROOT" >&2
  exit 1
fi

current_color="blue"
if [ -f "$CURRENT_COLOR_FILE" ]; then
  current_color="$(cat "$CURRENT_COLOR_FILE")"
fi

if [ "$current_color" = "blue" ]; then
  next_color="green"
  next_port="$GREEN_PORT"
else
  next_color="blue"
  next_port="$BLUE_PORT"
fi

project_name="sklio-${ENV_NAME}-${next_color}"
old_project_name="sklio-${ENV_NAME}-${current_color}"

export ENV="$ENV_NAME"
export IMAGE_NAME
export APP_PORT="$next_port"

if [ -n "${GHCR_TOKEN:-}" ] && [ -n "${GHCR_USERNAME:-}" ]; then
  echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin
fi

docker pull "$IMAGE_NAME"

docker compose -p "$project_name" -f docker-compose.prod.yml run --rm -e RUN_MIGRATIONS_ON_START=false web flask db upgrade
docker compose -p "$project_name" -f docker-compose.prod.yml up -d

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${next_port}${HEALTH_PATH}" >/dev/null; then
    break
  fi
  sleep 2
done

curl -fsS "http://127.0.0.1:${next_port}${HEALTH_PATH}" >/dev/null

sudo mkdir -p /etc/nginx/snippets
printf 'set $sklio_upstream http://127.0.0.1:%s;\n' "$next_port" | sudo tee "/etc/nginx/snippets/sklio-${ENV_NAME}-upstream.conf" >/dev/null
sudo nginx -t
sudo systemctl reload nginx

echo "$next_color" > "$CURRENT_COLOR_FILE"

if docker compose -p "$old_project_name" -f docker-compose.prod.yml ps >/dev/null 2>&1; then
  docker compose -p "$old_project_name" -f docker-compose.prod.yml down
fi
