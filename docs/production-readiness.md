# Production Readiness

## What ships today
- JWT auth for API requests
- Mock payments behind `PAYMENT_PROVIDER=mock`
- Local upload storage behind `STORAGE_BACKEND=local`
- Request/error logging with request IDs for API failures
- Automated smoke coverage for verification, bookings, chat, tracking, and dashboard flows

## Before public launch
1. Replace `PAYMENT_PROVIDER=mock` with a real provider integration and disable `ALLOW_MOCK_PAYMENTS`.
2. Move uploads to object storage and set retention/cleanup jobs for identity files.
3. Configure `ERROR_MONITOR_DSN` and forward app logs to your monitoring platform.
4. Rotate any previously committed secrets and keep `.env`, `.mcp.json`, and `.codex/mcp.json` local-only.
5. Run `python scripts/purge_expired_uploads.py` on a schedule.
6. Apply the alert thresholds in `docs/monitoring-alerts.md` to Sentry and your log platform.

## Recommended environment values
- `PAYMENT_PROVIDER=stripe` or your real gateway when implemented
- `STORAGE_BACKEND=s3` or equivalent object storage when implemented
- `DOCUMENT_RETENTION_DAYS=30` or a shorter policy if compliance requires it
- `LOG_API_REQUESTS=true` in staging while hardening flows
- `ALLOW_MOCK_PAYMENTS=false` outside local development

## Launch Week Ops Runbook

### Provider supply targets
- Cleaning: 15 active providers
- Plumbing: 10 active providers
- Electrical: 10 active providers
- Carpentry: 5 active providers
- AC service: 8 active providers
- City gate: do not open bookings until 80% of category minimums are met
- Supply health query:
  ```sql
  SELECT category, city, COUNT(*) as active_providers
  FROM providers
  WHERE kyc_status = 'approved'
    AND last_active_at > NOW() - INTERVAL '7 days'
  GROUP BY category, city
  ORDER BY active_providers ASC;
  ```

### Support training scenarios
1. Provider no-show
   - Verify booking is confirmed and scheduled time has passed
   - If confirmed: issue full refund, suspend provider pending review, issue 10% goodwill credit, log incident
2. Quality dispute
   - Request photo evidence, give provider 24 hours to respond
   - If clear: issue partial refund (default 50%)
   - If unclear: escalate to L2 support, resolve within 48 hours
3. Payment charged but booking not confirmed
   - Check PSP status
   - If captured but webhook failed: reprocess webhook
   - If failed but charged: refund immediately
4. Provider payout request
   - Require verified bank details, min payout ₹500
   - Weekly payout schedule; urgent requests escalate to finance
5. Suspected fake review
   - Validate booking history and review velocity
   - Delete fake review; warn or suspend for repeated abuse

### Fraud flag SLAs
- Fake review cluster: 4h, auto-hide reviews
- Suspected identity fraud: 2h, auto-suspend provider
- Off-platform payment attempt: 24h, warning in chat
- Refund abuse (>3 disputes): 4h, auto-flag account
- Brute force login (20+ fails): immediate, auto-lock for 30 minutes

### First 30 days ops calendar
1. Days 1–3: invite-only 50 seekers / 30 providers, war room 8am–10pm
2. Days 4–7: open to 500 seekers, watch dispute <5%, no-show <2%
3. Days 8–14: open to full city, launch referral campaign
4. Days 15–30: weekly NPS, publish review trust signals, retro on incidents
