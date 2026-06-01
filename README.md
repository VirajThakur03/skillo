# ⚡ Sklio — Local Skills & Services Marketplace

Sklio is a modern, production-grade on-demand local skills and service marketplace. It connects **Seekers** looking for local assistance (cleaning, plumbing, electrical work, etc.) with verified **Providers** offering specialized services.

This repository contains the full Flask-based backend, database schema, real-time Socket.IO communication layer, payment integrations, automated KYC verification, and automated testing suites.

---

## 🛠️ Technology Stack

* **Core Framework**: Python 3.10 + Flask 3.1.2 (WSGI standard compliant)
* **Real-time Layer**: Flask-SocketIO + python-socketio + Eventlet (for high-concurrency event loops)
* **Database & ORM**: PostgreSQL (via SQLAlchemy) + Flask-Migrate (Alembic)
* **Caching & Rate Limiting**: Redis 7.0 + Flask-Limiter (integrated rate-limiting token bucket)
* **Payment Integrations**: Stripe API + Razorpay SDK (with sandbox, real webhook signature matching, and mock simulation fallbacks)
* **Storage Backend**: Multi-backend configuration (Local filesystem or AWS S3 upload integration)
* **Verification & Security**: Facial recognizer (LBPH face verification fallback), ClamAV attachment security scans
* **Testing & Quality**: pytest + detect-secrets (pre-commit hook)

---

## ✨ Features

### 1. Zero-Trust KYC Onboarding & Face Matching
* **Document Upload**: Multi-page/image upload of Government ID (front/back), Bank Proof, and Skill Certificate.
* **Selfie Verification**: Integrates face extraction and alignment checking on uploaded selfies to verify against document photos.
* **Video Verification**: Short video recording liveness verification where the provider's face in the video is cross-referenced with their document ID.
* **State Sync**: Auto-transitions through states (`pending` -> `documents_submitted` -> `under_review` -> `approved` / `rejected`).

### 2. Real-Time Chat & Geolocation Tracking
* **Socket.IO Chatroom**: Instant messaging within bookings, complete with heartbeats and connection states.
* **Read Receipts & History**: Persistent chat messages with read receipt updates and paginated message history queries.
* **Secure File Sharing**: Media sharing with basic validation or ClamAV antivirus scanning checks.
* **Live Worker Location**: Geolocation streaming. When a provider is on their way, their coordinates (latitude, longitude) stream over Socket.IO to update the seeker's UI map.

### 3. Financial Transactions & Wallets
* **Wallet Ledger**: Account balance tracking with strict transaction log integrity constraints.
* **Top-ups**: In-app wallet top-up processing via Stripe Checkout sessions or Razorpay hooks.
* **Transactions**: Standardized booking escrows, provider payments, and platform commission deduction calculations.

### 4. Job Board & Bookings Workflow
* **Flexible Bookings**: Standardized booking states (`PENDING`, `CONFIRMED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`).
* **Availability Management**: Real-time weekly slot booking controls for providers.
* **Promos & Referrals**: Automatic referral rewards program credited to user wallets when a referral completes their first booking.

---

## 📂 Project Structure

```text
├── app/
│   ├── routes/              # Blueprint definitions (Auth, Wallet, Bookings, Chat, System, etc.)
│   ├── services/            # Stripe/Razorpay integrations, Storage managers, Notification builders
│   ├── verify/              # Face extraction, Face matching, and KYC verification logic
│   ├── templates/           # Jinja2 views (Dashboards, Wallet, Verification pages)
│   ├── static/              # CSS stylesheets, frontend JavaScript, image assets
│   ├── models.py            # Database schemas (User, Skill, Booking, Ledger, WebhookEvent)
│   ├── config.py            # Configuration options parsing from environment
│   └── extensions.py        # Extensions initialization (Bcrypt, SocketIO, Limiter)
├── docs/                    # Technical runbooks, operating specs, and checklists
├── migrations/              # Database migration history
├── seeds/                   # Seed script data (seed_data.py)
├── scripts/                 # Local smoke test verification files and deployment scripts
├── tests/                   # Pytest automation test suite
├── Dockerfile               # Production multi-stage python runtime container
├── docker-compose.yml       # Dev orchestration file (Postgres, Redis, Web app)
└── wsgi.py                  # Gunicorn hook point
```

---

## 🚀 Quick Start

### 1. Prerequisites
Ensure you have Docker and Docker Compose installed.

### 2. Configuration Setup
Create your local environment configuration file:
```bash
cp .env.example .env
```
Edit the `.env` file to customize your secret keys, Stripe tokens, or enable features:
```env
FLASK_ENV=development
ALLOW_MOCK_PAYMENTS=true
SECRET_KEY=generate_a_random_key_here
JWT_SECRET_KEY=generate_another_random_key_here
```

### 3. Launch with Docker Compose
Run the container environment:
```bash
docker compose up --build
```
This starts:
* **PostgreSQL** on port `5432`
* **Redis** on port `6379`
* **Sklio Web App** on port `5000`

### 4. Database Initialization & Seeding
Open a terminal in the root folder and populate the database with seed data:
```bash
# Seed development credentials and skills
docker compose exec web python seeds/seed_data.py

# Seed staging dummy bookings and messaging history
docker compose exec web python scripts/seed_staging.py
```

---

## 🧪 Testing & Verification

### Running Unit & Integration Tests
Run the pytest test suite inside the docker container:
```bash
docker compose exec web pytest
```

### Running Smoke Tests
Audit endpoints and platform states using the local smoke tests:
```bash
# Verify route availability and status codes
docker compose exec web python scripts/smoke_verify.py

# Verify chat messaging socket synchronization
docker compose exec web python scripts/smoke_chat_experience.py

# Audit all system pages
docker compose exec web python scripts/smoke_pages.py
```

---

## 🔒 Security Best Practices

* **Signature Webhook Matching**: Webhook endpoints enforce Stripe/Razorpay signature payload checks. In local dev, a signature check bypass is allowed only if `STRIPE_WEBHOOK_SECRET` matches `"whsec_test"`.
* **Rate Limiting**: Rate limits are set on critical routes (e.g. 10 authentications per minute, 20 payments per minute) using a Redis-backed storage engine.
* **Pre-commit Secrets Hook**: Uses `detect-secrets` hooks to prevent private keys or API tokens from being pushed. If you use mock strings for tests, remember to tag the lines with `# pragma: allowlist secret` to let them bypass checks.
