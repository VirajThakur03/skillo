# Production Deploy Runbook

This runbook assumes:

- `staging` and `production` use separate hosts, Postgres databases, and Redis instances.
- bookings and payouts use Stripe outside local development
- wallet top-ups use Stripe when `FEATURE_WALLET=true`
- `.env.runtime` is managed on each host through a secret manager or secure copy process.

## 1. Production server setup

Production entrypoint files:

- `wsgi.py`
- `gunicorn.conf.py`
- `run_prod.sh`
- `docker-compose.prod.yml`

Start the app locally in production mode:

```bash
cp .env.example .env
set ENV=production
set PAYMENT_PROVIDER=stripe
set PAYMENT_MODE=real
set ALLOW_MOCK_PAYMENTS=false
set WALLET_TOPUP_PROVIDER=stripe
python -m pip install -r requirements.txt
gunicorn --config gunicorn.conf.py wsgi:app
```

The default production runtime uses Gunicorn's threaded worker (`gthread`) with
`simple-websocket` for Flask-SocketIO support. This avoids the import-order and
monkey-patching problems that can happen with `eventlet`. `run_prod.sh` now defaults
to `SOCKETIO_ASYNC_MODE=threading` and `GUNICORN_WORKER_CLASS=gthread`. If you
explicitly set `SOCKETIO_ASYNC_MODE=eventlet`, test that mode separately before
deploying it.

Development mode remains:

```bash
python run.py
```

## 2. Provision staging and production infrastructure

### Postgres 15+

Staging:

```bash
docker run -d --name sklio-postgres-staging \
  -e POSTGRES_DB=sklio_staging \
  -e POSTGRES_USER=sklio \
  -e POSTGRES_PASSWORD='<strong-password>' \
  -v /srv/sklio/staging/postgres:/var/lib/postgresql/data \
  -p 5432:5432 postgres:15
```

Production:

```bash
docker run -d --name sklio-postgres-production \
  -e POSTGRES_DB=sklio_production \
  -e POSTGRES_USER=sklio \
  -e POSTGRES_PASSWORD='<strong-password>' \
  -v /srv/sklio/production/postgres:/var/lib/postgresql/data \
  -p 5432:5432 postgres:15
```

### Redis 7+

Staging:

```bash
docker run -d --name sklio-redis-staging \
  -v /srv/sklio/staging/redis:/data \
  -p 6379:6379 redis:7 redis-server --appendonly yes
```

Production:

```bash
docker run -d --name sklio-redis-production \
  -v /srv/sklio/production/redis:/data \
  -p 6379:6379 redis:7 redis-server --appendonly yes
```

### TLS and domain

Install Nginx and Certbot:

```bash
sudo apt-get update
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo cp ops/nginx/sklio.conf /etc/nginx/sites-available/sklio.conf
sudo ln -sf /etc/nginx/sites-available/sklio.conf /etc/nginx/sites-enabled/sklio.conf
sudo certbot --nginx -d api.example.com
sudo systemctl enable nginx
sudo systemctl restart nginx
```

### Required runtime environment

`.env.runtime` on each host must include:

```env
ENV=staging
FLASK_ENV=staging
PAYMENT_PROVIDER=stripe
PAYMENT_MODE=real
ALLOW_MOCK_PAYMENTS=false
WALLET_TOPUP_PROVIDER=stripe
DATABASE_URL=postgresql://sklio:...@db-host:5432/sklio_staging
REDIS_URL=redis://redis-host:6379/0
SOCKETIO_MESSAGE_QUEUE=redis://redis-host:6379/1
RATELIMIT_STORAGE_URI=redis://redis-host:6379/2
SECRET_KEY=...
JWT_SECRET_KEY=...
STRIPE_SECRET_KEY=sk_test_or_sk_live...
STRIPE_PUBLISHABLE_KEY=pk_test_or_pk_live...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_API_MODE=test
STORAGE_BACKEND=s3
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=ap-south-1
S3_BUCKET_NAME=...
PLATFORM_GSTIN=...
PLATFORM_SAC_CODE=998599
LEGAL_ENTITY_NAME=Sklio Marketplace
LEGAL_ENTITY_ADDRESS=...
PAYMENT_SUCCESS_URL=https://api.example.com/track/{booking_id}?checkout=success
PAYMENT_CANCEL_URL=https://api.example.com/booking/{skill_id}?provider={provider_id}&checkout=cancelled
CORS_ALLOWED_ORIGINS=https://app.example.com
SOCKETIO_CORS_ALLOWED_ORIGINS=https://app.example.com
ERROR_MONITOR_DSN=...
```

Production must use:

```env
ENV=production
STRIPE_API_MODE=live
```

## 3. GitHub Actions deploy workflow

Configure environment-scoped GitHub secrets for both `staging` and `production`:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `APP_ROOT`
- `HEALTHCHECK_URL`

The workflow:

- runs smoke scripts plus a curated stable pytest suite
- builds and pushes a GHCR image
- ships `docker-compose.prod.yml` and `scripts/remote_blue_green_deploy.sh`
- performs blue-green deploy on the target host
- runs `/health` and `/api/system/features` after deploy
- runs Playwright smoke when test credentials are configured

## 4. Fresh staging database migration verification

```bash
set ENV=staging
set FLASK_ENV=staging
set DATABASE_URL=postgresql://sklio:...@localhost:5432/sklio_staging
flask db upgrade
flask db current
```

Schema verification:

```sql
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'bookings'
ORDER BY column_name;
```

Expected payment columns include:

- `payment_provider`
- `payment_checkout_session_id`
- `payment_intent_id`
- `payment_ref`
- `promo_discount_amount`
- `amount_payable`

## 5. Smoke test commands

Install local test dependencies:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Run app tests:

```bash
pytest tests/test_auth_flow.py tests/test_dashboard_flows.py tests/test_dashboard_experience.py tests/test_chat_experience.py tests/test_job_post_flow.py tests/test_notifications_flow.py tests/test_stripe_payment_flow.py tests/test_stripe_wallet_topups.py tests/test_payment_wallet_contracts.py tests/test_finance_logic.py tests/test_finance_ops.py tests/test_system_features.py -q
```

Run the direct page smoke verifier for non-Docker local environments:

```bash
python scripts/smoke_pages.py
```

Run the repo-local smoke verifier when pytest is unavailable or to sanity-check the critical path quickly:

```bash
python scripts/smoke_verify.py
```

Run Stripe webhook simulation locally:

```bash
stripe listen --forward-to localhost:5000/webhooks/stripe
stripe trigger checkout.session.completed
stripe trigger payment_intent.succeeded
```

Recommended staging payment checks:

1. Create a staging booking with Stripe test keys enabled.
2. Open `/api/bookings/<id>/payment-session` and confirm Checkout URL creation.
3. Complete payment with Stripe test card `4242 4242 4242 4242`.
4. Trigger duplicate webhook delivery and confirm the second request returns `{"status":"duplicate"}`.
5. Trigger `payment_intent.payment_failed` and `charge.refunded` on a separate test booking and verify booking timeline updates.

Recommended staging wallet checks:

1. Open `/wallet` with `WALLET_TOPUP_PROVIDER=stripe`.
2. Create a wallet top-up checkout session and confirm a `wallet_topups` row is created in `PENDING`.
3. Complete the Stripe test payment and confirm the webhook marks the row `COMPLETED`.
4. Verify the user's `wallet_transactions` and `/payment-history` both show the top-up exactly once.

Host smoke checks:

```bash
curl -fsS https://api.example.com/health
curl -fsS https://api.example.com/api/system/features
```

## 6. Backups and restore

Postgres backup:

```bash
pg_dump "$DATABASE_URL" > "backup-$(date +%F).sql"
```

Postgres restore:

```bash
psql "$DATABASE_URL" < backup-2026-04-19.sql
```

Redis backup:

```bash
redis-cli -u "$REDIS_URL" BGSAVE
```

Redis restore uses the persisted `dump.rdb` or append-only file after stopping the Redis process and replacing data files.

## 7. Upload retention and cleanup

Run upload cleanup on a schedule:

```bash
python scripts/purge_expired_uploads.py
```

This now purges:

- regular uploads older than `DOCUMENT_RETENTION_DAYS`
- quarantined chat attachments older than `CHAT_ATTACHMENT_QUARANTINE_RETENTION_DAYS`

Example cron:

```bash
0 3 * * * cd /srv/sklio/current && /usr/bin/python scripts/purge_expired_uploads.py >> /var/log/sklio-upload-cleanup.log 2>&1
```
