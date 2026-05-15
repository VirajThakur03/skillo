#!/bin/sh
# scripts/backup_db.sh
# Production database and Redis backup script with 7-day rotation.
# Usage: Run this as a cron job at night inside the web container.

set -e

BACKUP_DIR="/app/backups"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
RETENTION_DAYS=7

mkdir -p "$BACKUP_DIR"

echo "[$TIMESTAMP] Starting database backup..."

# 1. Backup PostgreSQL
# Note: Requires DATABASE_URL or appropriate PG environment variables
if [ -n "$DATABASE_URL" ]; then
    FILENAME_PG="$BACKUP_DIR/pg_backup_$TIMESTAMP.sql.gz"
    # Extract host, user, db from DATABASE_URL if needed, or use pg_dump directly if env is set
    # For Docker simplicity, we assume pg_dump is available and connected via env
    pg_dump "$DATABASE_URL" | gzip > "$FILENAME_PG"
    echo "[$TIMESTAMP] Postgres backup saved to $FILENAME_PG"
else
    echo "[$TIMESTAMP] SKIP: DATABASE_URL not set"
fi

# 2. Backup Redis
# Note: This is a simple RDB copy if accessible, or using redis-cli SAVE
if [ -n "$REDIS_URL" ]; then
    FILENAME_REDIS="$BACKUP_DIR/redis_backup_$TIMESTAMP.rdb.gz"
    # We use redis-cli to trigger a save and then copy the dump.rdb if we have local access,
    # but for a generic script, we'll try to use redis-cli --rdb if available.
    # Alternatively, just save the current state.
    redis-cli -u "$REDIS_URL" SAVE || true
    # If running in same container as redis, we could copy /data/dump.rdb
    # Since this is likely the web container, we'll use --rdb if supported.
    redis-cli -u "$REDIS_URL" --rdb "$BACKUP_DIR/redis_temp.rdb"
    gzip -c "$BACKUP_DIR/redis_temp.rdb" > "$FILENAME_REDIS"
    rm "$BACKUP_DIR/redis_temp.rdb"
    echo "[$TIMESTAMP] Redis backup saved to $FILENAME_REDIS"
else
    echo "[$TIMESTAMP] SKIP: REDIS_URL not set"
fi

# 3. Rotate old backups
echo "[$TIMESTAMP] Cleaning up backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -name "*.gz" -type f -mtime +"$RETENTION_DAYS" -delete

echo "[$TIMESTAMP] Backup process completed successfully."
