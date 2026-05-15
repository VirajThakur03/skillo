# Deployment Checklist

This checklist reflects the current repo state as of April 19, 2026.

## Current verdict

The app is not fully ready for a public production launch yet.

It is close enough for a controlled staging deployment, but public launch should wait until the blocking items below are finished and verified.

## Fixed in this audit

- Environment-driven production settings now load into `app.config` for payments, logging, retention, and monitoring.
- Socket.IO CORS is now configurable through `SOCKETIO_CORS_ALLOWED_ORIGINS` instead of always allowing `*`.
- The public `/uploads/<path>` route now serves invoice files only and no longer exposes KYC uploads.
- The deliberate `/api/test-error` route is now disabled in production.

## Blocking before public production

1. Replace mock payments with a real provider path end to end.
   - `app/services/payments.py` still supports only `mock`.
   - Production must not rely on `ALLOW_MOCK_PAYMENTS=true`.

2. Run the full automated test suite until green.
   - `pytest -q` currently fails or hangs in the present local environment.
   - Shipping without a passing test signal is too risky.

3. Use a production WSGI / Socket.IO server instead of the current dev-server path.
   - The container still starts with `python run.py`.
   - For production, switch to a real process manager and worker model.

4. Finish deployment infrastructure.
   - `.github/workflows/deploy.yml` still contains placeholder SSH hosts and domain names.
   - The workflow is not deployable as written.

5. Confirm database migration strategy.
   - Production should use Alembic migrations as the source of truth.
   - `AUTO_SYNC_SCHEMA` must remain off in production.
   - Validate all migration heads on a fresh staging database.

## Strongly recommended before launch

1. Move user uploads to object storage.
   - Keep invoices accessible.
   - Keep KYC media private.
   - Add signed URL or authenticated download flow if staff access is needed.

2. Add production secrets and rotation process.
   - Set strong `SECRET_KEY` and `JWT_SECRET_KEY`.
   - Set `ERROR_MONITOR_DSN`.
   - Set payment and storage credentials in the host secret manager, not in repo files.

3. Put the app behind HTTPS and a reverse proxy.
   - Terminate TLS at Nginx, Caddy, a load balancer, or your platform edge.
   - Forward real client IP headers correctly.

4. Add backups and restore drills.
   - Database backups.
   - Upload bucket backups or retention policy where required.

5. Finalize observability.
   - Send logs to a log platform.
   - Configure the alert thresholds from `docs/monitoring-alerts.md`.
   - Verify Sentry receives sanitized events from staging first.

## Nice-to-have hardening

1. Add explicit readiness checks for database and Redis in `/health`.
2. Remove broad bind mounts from production compose usage.
3. Add rate limiting for login, registration, and upload endpoints.
4. Review large AI / CV dependencies for image size, startup time, and memory pressure.
5. Add a dedicated staging smoke command in CI that mirrors production startup.

## Recommended deployment sequence

1. Make staging the first target.
2. Provision managed Postgres and Redis.
3. Set production env vars and secrets.
4. Run `flask db upgrade`.
5. Start the app with a production server.
6. Verify `/health`, auth, booking, invoice download, and webhook flows.
7. Turn on monitoring alerts.
8. Promote to public traffic only after smoke tests and manual checks pass.
