# Sklio Payment System - Remaining Tasks (tsks.md)

## Critical (Must Fix Before Production)
- [x] Unify the payment architecture around one production gateway
  - Description: The codebase currently mixes Stripe booking payments with Razorpay wallet top-ups, while production guards in `app/services/payments.py` enforce Stripe outside development. This creates a split-brain payment architecture that is not production-safe.
  - Files involved: `app/config.py`, `app/services/payments.py`, `app/services/payment_service.py`, `app/routes/wallet.py`, `app/routes/webhooks.py`, `.env.example`, `docs/production-deploy-runbook.md`
  - Acceptance criteria:
    - One documented production gateway strategy exists for bookings, wallet top-ups, refunds, and webhooks.
    - Production config validation hard-fails if the chosen gateway secrets are missing.
    - Staging/prod smoke tests cover the chosen gateway end-to-end.
  - Priority: P0

- [x] Fix the Wallet V2 API/UI contract
  - Description: `/wallet` renders `wallet_v2.html`, but the frontend expects fields and pagination shapes that `/api/wallet/v2/*` does not return. Top-up payload keys also do not match the Razorpay checkout integration.
  - Files involved: `app/templates/wallet_v2.html`, `app/routes/wallet.py`, `app/services/wallet_service.py`
  - Acceptance criteria:
    - `GET /api/wallet/v2/balance` returns every field used by the page.
    - `GET /api/wallet/v2/transactions` supports the page’s filter and pagination contract.
    - `POST /api/wallet/v2/topup` returns Razorpay-ready keys or the frontend is updated to the real contract.
    - Wallet page loads without JavaScript/runtime errors.
  - Priority: P0

- [x] Replace mutable wallet balance updates with an atomic ledger workflow
  - Description: Wallet credits/debits currently update `user.wallet_balance` directly without row locking or optimistic concurrency. This can create race conditions, duplicate debits, or invalid balances under concurrent requests.
  - Files involved: `app/services/wallet_service.py`, `app/routes/bookings.py`, `app/routes/payouts.py`, `app/models.py`
  - Acceptance criteria:
    - All balance-changing flows run inside DB transactions with row-level locking or equivalent atomic update protection.
    - Withdrawals, COD commission debits, refunds, top-ups, and subscriptions all write `WalletTransaction` entries consistently.
    - Negative balances are impossible unless a clearly documented credit facility is enabled.
  - Priority: P0

- [x] Remove duplicate subscription models and standardize membership logic
  - Description: `app/models.py` defines `SubscriptionPlan` and `UserSubscription` twice with incompatible schemas. There is also a second membership flow in `app/routes/ops.py`.
  - Files involved: `app/models.py`, `app/routes/subscriptions.py`, `app/routes/ops.py`, migrations touching `subscription_plans` and `user_subscriptions`
  - Acceptance criteria:
    - Exactly one canonical subscription schema exists.
    - Exactly one API surface powers `/memberships`.
    - Existing data is migrated safely.
    - Membership commission rules and UI plan fields come from the same source.
  - Priority: P0

- [x] Make commission calculation membership-aware and enforce COD recovery safely
  - Description: `calculate_booking_fees()` always uses `Config.PLATFORM_FEE_DEFAULT` and does not check provider membership. COD completion debits provider wallet with `allow_negative=True`, which can hide revenue leakage or create unbounded debt.
  - Files involved: `app/services/booking_service.py`, `app/routes/bookings.py`, `app/routes/subscriptions.py`, `app/models.py`
  - Acceptance criteria:
    - Commission calculation uses the provider’s active membership plan when applicable.
    - Cash booking completion debits commission exactly once.
    - COD commission collection cannot silently fail or overdraw wallets unexpectedly.
  - Priority: P0

- [x] Implement real GST-compliant invoice and tax computation
  - Description: PDF invoices are generated with ReportLab, but GST computation is not derived from provider/customer place of supply. Required tax/compliance fields are incomplete.
  - Files involved: `app/services/booking_service.py`, `app/services/payment_service.py`, `app/models.py`, booking creation routes, invoice templates/data builders
  - Acceptance criteria:
    - CGST/SGST vs IGST is computed from real state/GSTIN rules.
    - Invoice data includes SAC code, legal entity details, GSTIN, and a verifiable invoice number.
    - PDF downloads remain valid for completed bookings and commission invoices.
  - Priority: P0

- [x] Build a unified payment history surface
  - Description: `/payment-history` is labeled unified, but the API only returns booking payment history and the template calls the wrong invoice-generation endpoint.
  - Files involved: `app/templates/payment_history.html`, `app/routes/bookings.py`, `app/routes/wallet.py`, `app/routes/payouts.py`
  - Acceptance criteria:
    - Payment history includes wallet top-ups, refunds, subscription debits, withdrawals, commissions, and booking invoices.
    - Generate/download actions call real endpoints.
    - Invoice and transaction filters work correctly.
  - Priority: P0

## High Priority
- [x] Harden Razorpay webhook processing for wallet top-ups
  - Description: A Razorpay webhook exists, but it credits wallets by `user_id` and `topup_id` notes without matching a persisted top-up intent record. That is not enough for strong replay protection or reconciliation.
  - Files involved: `app/routes/webhooks.py`, `app/routes/wallet.py`, `app/models.py`, `app/services/payment_service.py`
  - Acceptance criteria:
    - Wallet top-ups persist a pending top-up/order record before checkout.
    - Webhook processing verifies the order/payment linkage and records idempotent completion.
    - Replayed or malformed top-ups cannot credit the wallet twice.
  - Priority: P1

- [x] Add transaction/reference records for withdrawals
  - Description: Provider withdrawal currently edits `user.wallet_balance` directly and does not write a `WalletTransaction` ledger entry.
  - Files involved: `app/routes/payouts.py`, `app/services/wallet_service.py`, `app/models.py`
  - Acceptance criteria:
    - Every withdrawal creates a traceable transaction row.
    - Payout status and failure handling are visible in history.
  - Priority: P1

- [x] Fix membership frontend/auth assumptions
  - Description: `memberships.html` checks `localStorage.user_role`, while the rest of the app uses the newer auth storage keys. This can create false access errors in the browser.
  - Files involved: `app/templates/memberships.html`, `app/static/js/main.js`
  - Acceptance criteria:
    - Membership page uses the same auth/session keys as the rest of the site.
    - Subscribe flow works for eligible providers with wallet funds.
  - Priority: P1

- [x] Add booking creation rate-limit enforcement
  - Description: Fraud scoring exists, but booking creation itself is not obviously rate-limited at the route layer.
  - Files involved: `app/routes/bookings.py`, `app/services/fraud_service.py`, `app/extensions.py`
  - Acceptance criteria:
    - Booking creation has route-level rate limiting.
    - Suspicious spikes are blocked or stepped up for review.
  - Priority: P1

- [x] Replace environment defaults that encourage unsafe local/prod copying
  - Description: `.env.example` still advertises `SOCKETIO_ASYNC_MODE=eventlet`, `GUNICORN_WORKER_CLASS=eventlet`, and dev-friendly toggles that can be copied into real deployments.
  - Files involved: `.env.example`, `docs/production-deploy-runbook.md`, `gunicorn.conf.py`, `run_prod.sh`
  - Acceptance criteria:
    - Example config clearly separates dev and prod values.
    - Production examples reflect the actual supported runtime stack.
  - Priority: P1

## Medium / Polish
- [x] Add real-time wallet refresh support
  - Description: The premium wallet spec expects live balance updates, but current code only loads data via page fetches.
  - Files involved: `app/templates/wallet_v2.html`, Socket.IO notification/event code, optional wallet events route/service
  - Acceptance criteria:
    - Wallet updates after top-up, refund, commission debit, and subscription purchase without a full page reload.
  - Priority: P2

- [x] Add transaction filtering and stable pagination semantics
  - Description: `wallet_v2.html` expects filter-by-type and page-based pagination, but the backend currently exposes cursor-like `before_id` semantics only.
  - Files involved: `app/routes/wallet.py`, `app/services/wallet_service.py`, `app/templates/wallet_v2.html`
  - Acceptance criteria:
    - Filters for credit/debit/type work server-side.
    - Pagination UI and API use the same contract.
  - Priority: P2

- [x] Add invoice/download tests for the frontend contract
  - Description: Backend invoice tests exist, but the payment-history frontend still points to a non-existent endpoint.
  - Files involved: `tests/test_booking_invoices.py`, browser/e2e tests, `app/templates/payment_history.html`
  - Acceptance criteria:
    - Automated tests verify the invoice generate button and download link contract.
  - Priority: P2

## Suggested Improvements / Nice-to-Haves
- [x] Add a dedicated `wallet_topups` table
  - Description: Store pending/completed top-up intents, gateway order ids, payment ids, audit timestamps, and failure reasons.
  - Files involved: `app/models.py`, migrations, `app/routes/wallet.py`, `app/routes/webhooks.py`

- [x] Add double-entry accounting concepts for platform money movement
  - Description: For a fintech-style marketplace, a true ledger with platform liability, receivable, provider payable, and tax buckets will scale better than a single mutable wallet balance.
  - Files involved: accounting/ledger service layer, migrations, reconciliation jobs

- [x] Add reconciliation jobs and ops dashboards
  - Description: Daily reconciliation between gateway events, wallet balances, bookings, invoices, and withdrawals should be automated and visible to operators.
  - Files involved: background jobs, admin routes, ops templates, monitoring
