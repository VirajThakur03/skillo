# Monitoring Alerts

## Sentry

Configure these alerts in Sentry for `environment=staging` and `environment=production`.

### Critical

- Error rate `> 5%` over `5 minutes`
  - Action: page immediately
  - Scope: all backend requests

- Any `500` error on `/api/auth/*`
  - Action: page immediately
  - Scope: auth endpoints

### Warning

- `webhook.signature_invalid` occurs more than `3` times in `1 minute`
  - Action: send Slack alert
  - Scope: payment webhook endpoint

- `booking.payment_failed` occurs more than `10` times in `10 minutes`
  - Action: send Slack alert
  - Scope: booking payment flow

- `upload.failed` rate `> 10%` in any `10-minute` window
  - Action: send Slack alert
  - Scope: document, selfie, and verification uploads

### Info

- Daily digest: `booking.created` count per hour
- Daily digest: `booking.completed` vs `booking.cancelled` ratio

## Log Aggregator

If logs are shipped to Datadog, Logtail, ELK, or a similar platform, create saved searches and alerts for:

- `event=user.login.failed` grouped by IP
  - Threshold: more than `20` failed logins from the same IP in `5 minutes`
  - Action: warning to Slack

- `event=booking.provider_declined`
  - Threshold: decline rate `> 30%` in `1 hour`
  - Action: warning to Slack

- `event=booking.created`
  - Dashboard: bookings per hour

- `event=booking.completed`
  - Dashboard: completed bookings per hour

- `event=booking.payment_failed`
  - Dashboard: payment failures per hour

## Launch Checklist

- Set `SENTRY_DSN` in staging and production.
- Verify events are tagged with the correct `environment`.
- Confirm no request body, `Authorization`, or `Cookie` headers reach Sentry.
- Verify Slack or pager routing for critical alerts.
