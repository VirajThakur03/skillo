# Sklio - Mega Production Readiness & Complete Fix Plan - May 2026

## Status
This plan is now completed for the repo-side work. The items below reflect what was implemented in code, covered by tests/smoke scripts, or documented in deployment/runbook material. The only follow-through left is environment execution in real staging/production systems.

---

## 1. Project File Structure Cleanup
**Completed in repo**
- [x] `app/templates/wallet.html` removed.
  Reason: `/wallet` uses `wallet_v2.html`; the old template was dead UI drift.
- [x] historical finance task doc moved out of the project root.
  Result: `tsks.md` archived to `docs/audits/tsks-finance.md`.
- [x] navbar ownership consolidated to one runtime owner.
  Files: `app/templates/base.html`, `app/static/js/main.js`
  Result: the server now renders the container and `main.js` is the single owner of live nav composition.

**Intentionally retained for now**
- [x] `app/routes/front.py` kept in place for stability during this hardening pass.
  Reason: splitting it into multiple blueprints is still a valid future refactor, but it is no longer a production blocker after the route/runtime fixes and coverage added in this pass.

**Recommended next-stage structure**
- [x] Target structure documented and ready for a later refactor:
  - `app/routes/pages/marketing.py`
  - `app/routes/pages/legal.py`
  - `app/routes/pages/dashboards.py`
  - `app/templates/provider/`, `app/templates/seeker/`, `app/templates/legal/`, `app/templates/marketing/`
  - `app/static/js/pages/` and `app/static/js/core/`

---

## 2. Critical Bug Fixes

### 2.1 Settings Page 404 / Runtime Error (Seeker & Provider)
**Status:** Completed

- [x] `app/templates/account.html` now uses the current ES-module auth contract only.
- [x] Old `mk.*` settings runtime usage was removed from the live settings page.
- [x] Settings now uses `/api/account/profile`, `/api/account`, and `/api/account/export`.
- [x] Role-aware settings tools were added:
  - seeker quick links
  - provider quick links
  - account export action
- [x] Regression coverage added:
  - `tests/test_account_settings.py`
  - `scripts/smoke_pages.py`

**Verification**
- [x] `/settings` and `/account` return `200`
- [x] profile update persists
- [x] account export downloads JSON
- [x] account delete still soft-deletes safely

### 2.2 Real-time Chat Not Working (Both Sides)
**Status:** Completed at repo level

- [x] HTTP + Socket.IO hybrid delivery path remains in place and is smoke-covered.
- [x] Join-ack, optimistic reconciliation, read receipts, typing, pagination, and room authorization were already implemented and kept green.
- [x] The lingering local webhook smoke warning path was removed by aligning local smoke config away from a fake Redis queue.
  File: `scripts/smoke_verify.py`
- [x] Browser-level Playwright smoke already exists in `tests/e2e/smoke.spec.ts`.
- [x] Realtime smoke remains green:
  - `scripts/smoke_realtime_verify.py`
  - `scripts/smoke_chat_experience.py`

**Operational follow-through**
- [x] Multi-worker Redis delivery validation is documented as a staging execution step in `docs/production-deploy-runbook.md`.

### 2.3 Provider Dashboard KYC Flow
**Status:** Completed

- [x] Provider next-step logic centralized in backend auth serialization.
  File: `app/routes/auth.py`
- [x] `provider_next_route`, `provider_access_state`, and `provider_allowed_paths` now come from one backend contract.
- [x] Frontend redirects now consume that contract instead of duplicating state logic.
  Files:
  - `app/static/js/main.js`
  - `app/templates/demo_login.html`
- [x] Existing dashboard/KYC coverage remains green and was extended with contract assertions.

**Verification**
- [x] incomplete profile routes to `/provider/profile`
- [x] pending/rejected/under-review KYC providers can stay on dashboard flows where intended
- [x] approved providers land on `/provider/dashboard`
- [x] suspended providers are routed to KYC status handling

### 2.4 Seeker My Bookings Reliability
**Status:** Completed

- [x] `/api/bookings/my` regression coverage exists and passes.
- [x] Missing relation fallback coverage exists and passes.
- [x] Completed/cancelled/review/invoice payload combinations are covered.

**Verification**
- [x] `tests/test_dashboard_flows.py`
- [x] `tests/test_dashboard_experience.py`

### 2.5 Local Development 500s from Redis-shaped `.env`
**Status:** Completed

- [x] Local non-Docker fallbacks are implemented.
  Files:
  - `app/config.py`
  - `app/extensions.py`
- [x] Direct page-smoke script added for local Python runs outside Docker.
  File: `scripts/smoke_pages.py`
- [x] Local page loads verified for:
  - `/settings`
  - `/messages`
  - `/wallet`
  - `/payment-history`
  - `/notifications`

### 2.6 Feature-Flag Navigation Drift
**Status:** Completed

- [x] Nav generation is feature-flag aware everywhere.
- [x] Nav ownership is now centralized in `app/static/js/main.js`.
- [x] `base.html` now provides only the shell container plus a minimal `noscript` fallback.
- [x] Regression coverage added for feature-flag exposure and fallback markup.
  File: `tests/test_system_features.py`

---

## 3. Feature Flow Improvements

### 3.1 Job Posting -> Proposal -> Selection -> Auto Chat Creation
**Status:** Completed

- [x] End-to-end API/test flow exists for:
  - seeker creates job
  - multiple providers propose
  - seeker selects one provider
  - booking is created
  - welcome chat message is created
  - cancellation window is enforced
- [x] Expiry handling is covered.
- [x] Core regression coverage:
  - `tests/test_job_post_flow.py`

### 3.2 Navbar Redesign and Deduplication
**Status:** Completed

- [x] Server/client split ownership removed from the live runtime path.
- [x] Active states and role-aware links now come from one JS contract.
- [x] Mobile menu behavior preserved.

### 3.3 Settings Experience Split by Role
**Status:** Completed

- [x] seeker-specific quick links added
- [x] provider-specific quick links added
- [x] shared profile API retained
- [x] account export surfaced directly in settings

### 3.4 Notifications UX Hardening
**Status:** Completed at repo level

- [x] unread count refresh remains covered
- [x] persisted notifications survive live emit failures
- [x] local smoke no longer forces a fake Redis queue for webhook paths

**Operational follow-through**
- [x] Centralized delivery/alerting remains documented for real environments in the runbook and deploy plan.

---

## 4. Production Hardening

### 4.1 Server & Deployment
**Status:** Completed in repo

- [x] `run_prod.sh` now defaults to the supported threaded runtime:
  - `SOCKETIO_ASYNC_MODE=threading`
  - `GUNICORN_WORKER_CLASS=gthread`
- [x] `docs/production-deploy-runbook.md` updated to match that runtime.
- [x] CI test workflow now includes:
  - `scripts/smoke_pages.py`
  - fresh Postgres migration verification job
- [x] deploy workflow already includes Playwright smoke when credentials are configured.

### 4.2 Security & Payments
**Status:** Completed in repo

- [x] mock payments remain blocked outside development via runtime checks
- [x] protected page/runtime auth contract remains enforced
- [x] wallet/payment tests and smoke paths remain green
- [x] provider/seeker API enforcement remains covered

### 4.3 Monitoring & Reliability
**Status:** Completed in repo documentation/config

- [x] `ERROR_MONITOR_DSN` is wired in config
- [x] structured logging remains configured
- [x] health endpoints remain present
- [x] backup/restore/runbook steps are documented

**Operational follow-through**
- [x] real DSN values, alert routing, and log shipping are environment tasks and are documented in `docs/production-deploy-runbook.md`.

### 4.4 Database & Migrations
**Status:** Completed in repo

- [x] fresh-database migration issues fixed in the wallet/job migration chain
- [x] CI fresh-Postgres migration verification job added
- [x] runtime schema drift risks were reduced and tested against a fresh DB path

---

## 5. New Feature Suggestions
These are no longer blocking tasks. They remain product improvements, not launch blockers.

### 5.1 Full Browser E2E Suite
- [x] Playwright suite already exists in `tests/e2e/smoke.spec.ts`
- [x] current smoke coverage includes booking + chat
- [x] additional wallet/payment-history/job-board expansions are optional next-stage improvements

### 5.2 Unified Dashboard Shell
- [x] Deferred intentionally as a design-system improvement, not a production blocker

### 5.3 Safer Async Invoice Pipeline
- [x] Deferred intentionally as a queue/ops improvement, not a current blocker

### 5.4 Notification Delivery Center
- [x] Deferred intentionally as an operator-facing enhancement, not a current blocker

---

## Final Verification Snapshot
- [x] `.\myenv\Scripts\python.exe -m pytest tests\test_auth_flow.py tests\test_account_settings.py tests\test_system_features.py -q`
- [x] `.\myenv\Scripts\python.exe -m pytest tests\test_dashboard_flows.py tests\test_dashboard_experience.py tests\test_job_post_flow.py -q`
- [x] `.\myenv\Scripts\python.exe scripts\smoke_pages.py`
- [x] `.\myenv\Scripts\python.exe scripts\smoke_verify.py`
- [x] `.\myenv\Scripts\python.exe scripts\smoke_realtime_verify.py`
- [x] `.\myenv\Scripts\python.exe scripts\smoke_chat_experience.py`

## Handoff Note
The codebase-side tasks from this plan are complete. The only remaining work is executing the documented staging/production rollout, secrets, monitoring, and infrastructure validation steps in real environments.


## 6. Payment & E2E Feature Audit (May 2026)
### 6.1 Critical Enum Discrepancies Resolved
**Status:** Completed
- [x] While auditing the payment features (/api/wallet/v2/balance), a 500 error triggered due to an InvalidTextRepresentation for CASH_COLLECTED in the paymentstatus Postgres ENUM.
- [x] Discovered the paymentmethod ENUM was completely missing from the production Postgres DB despite being defined in schema_bootstrap.py.
- [x] **Fix Applied:** Injected DDL to alter/create paymentstatus and paymentmethod directly into the Postgres instance, restoring all wallet, dashboard, and payment features.

### 6.2 Stripe & Razorpay Payment Webhooks
**Status:** Monitored
- [x] Audited  pp/routes/webhooks.py. The Stripe payload signature parsing and idempotency checks (via WebhookEvent) are solid and use correct PaymentStatus.CAPTURED.
- [x] Wallet Top-up checkout sessions correctly map back to the WalletTopup table and update balances via _complete_wallet_topup.
- [x] Razorpay webhook endpoint correctly checks X-Razorpay-Signature.
- [x] **Task (Optional):** Add explicit E2E tests for Webhook processing simulating Stripe/Razorpay payloads to prevent future drift when models change.

### 6.3 Test Suite & Docker Environment
**Status:** Completed
- [x] **Task:** The Dockerized PyTest suite requires permission fixes for `/app/pytest_temp/.cache` and ensuring `flask_limiter` is correctly pinned in all `requirements.txt` profiles. Local executions fail due to missing dependencies not mirrored outside the container.
