"""Comprehensive route audit - tests all frontend and API routes."""
import urllib.request
import urllib.error
import json

BASE = "http://localhost:5000"

def test_url(path, token=None, label=""):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            code = r.getcode()
            print(f"  {label}{path} => {code} OK")
            return code
    except urllib.error.HTTPError as e:
        print(f"  {label}{path} => {e.code} {e.reason}")
        return e.code
    except Exception as e:
        print(f"  {label}{path} => ERROR: {e}")
        return 0

def test_api(path, token=None, method="GET", data=None, label=""):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(f"{BASE}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            code = r.getcode()
            resp = json.loads(r.read())
            print(f"  {label}{method} {path} => {code} OK")
            return code, resp
    except urllib.error.HTTPError as e:
        try:
            resp = json.loads(e.read())
        except Exception:
            resp = {}
        print(f"  {label}{method} {path} => {e.code} {e.reason}")
        return e.code, resp
    except Exception as e:
        print(f"  {label}{method} {path} => ERROR: {e}")
        return 0, {}

def register_and_login(role):
    """Create a test user and get a JWT token."""
    import random, string
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    email = f"audit_{role}_{suffix}@test.com"
    payload = {"name": f"Audit {role.title()}", "email": email, "password": "AuditPass123!", "role": role}  # pragma: allowlist secret
    code, resp = test_api("/api/auth/register", method="POST", data=payload, label=f"[{role.upper()} REGISTER] ")
    if code == 201 and resp.get("access_token"):
        return resp["access_token"]
    # Try login if already exists
    code2, resp2 = test_api("/api/auth/login", method="POST", data={"email": email, "password": "AuditPass123!"}, label=f"[{role.upper()} LOGIN] ")  # pragma: allowlist secret
    if code2 == 200 and resp2.get("access_token"):
        return resp2["access_token"]
    return None

print("=" * 70)
print("SKLIO PLATFORM - COMPREHENSIVE LIVE FEATURE AUDIT")
print("=" * 70)

# ===========================================
# 1. PUBLIC ROUTES
# ===========================================
print("\n[1] PUBLIC ROUTES")
public_routes = [
    ("/", "Homepage"),
    ("/home", "Browse Services"),
    ("/login", "Login Page"),
    ("/register", "Register Page"),
    ("/demo_login", "Demo Login Page"),
    ("/ping", "Ping"),
    ("/health", "Health Check"),
    ("/legal/terms", "Terms"),
    ("/legal/privacy", "Privacy"),
    ("/legal/refund", "Refund Policy"),
    ("/legal/grievance", "Grievance"),
    ("/legal/provider-terms", "Provider Agreement"),
    ("/trust-center", "Trust Center"),
    ("/help", "Help Center"),
    ("/seeker-onboarding", "Seeker Onboarding"),
    ("/provider-onboarding", "Provider Onboarding"),
    ("/jobs", "Job Board"),
    ("/memberships", "Memberships"),
    ("/notifications", "Notifications Page"),
]
results = {}
for path, name in public_routes:
    code = test_url(path)
    results[path] = (name, code)

# ===========================================
# 2. AUTHENTICATION
# ===========================================
print("\n[2] AUTHENTICATION")
seeker_token = register_and_login("seeker")
provider_token = register_and_login("provider")
print(f"  Seeker token: {'OK' if seeker_token else 'MISSING'}")
print(f"  Provider token: {'OK' if provider_token else 'MISSING'}")

# Auth endpoints
if seeker_token:
    test_api("/api/auth/me", seeker_token, label="[SEEKER] ")
if provider_token:
    test_api("/api/auth/me", provider_token, label="[PROVIDER] ")

# ===========================================
# 3. SEEKER ROUTES (Frontend)
# ===========================================
print("\n[3] SEEKER FRONTEND ROUTES")
seeker_pages = [
    ("/my-bookings", "My Bookings / Seeker Dashboard"),
    ("/messages", "Messages"),
    ("/wallet", "Wallet"),
    ("/account", "Account/Settings"),
    ("/jobs", "Job Board"),
    ("/my-jobs", "My Job Posts"),
    ("/notifications", "Notifications"),
    ("/saved-providers", "Saved Providers"),
    ("/quote-requests", "Quote Requests"),
    ("/referrals", "Referrals"),
    ("/account/referrals", "Referrals (alt)"),
    ("/disputes", "Disputes"),
]
for path, name in seeker_pages:
    test_url(path, seeker_token, label="[SEEKER] ")

# ===========================================
# 4. PROVIDER ROUTES (Frontend)
# ===========================================
print("\n[4] PROVIDER FRONTEND ROUTES")
provider_pages = [
    ("/provider/dashboard", "Provider Dashboard"),
    ("/provider/profile", "Provider Profile"),
    ("/provider/kyc-status", "KYC Status"),
    ("/provider/job-board", "Provider Job Board"),
    ("/provider-availability", "Availability Calendar"),
    ("/account", "Account/Settings"),
    ("/messages", "Messages"),
    ("/wallet", "Wallet"),
    ("/provider_verification", "Verification"),
    ("/provider_verification_video", "Verification Video"),
    ("/provider_verification_selfie", "Verification Selfie"),
    ("/confirm_location", "Confirm Location"),
]
for path, name in provider_pages:
    test_url(path, provider_token, label="[PROVIDER] ")

# ===========================================
# 5. SEEKER API ENDPOINTS
# ===========================================
print("\n[5] SEEKER API ENDPOINTS")
seeker_apis = [
    ("GET", "/api/auth/me"),
    ("GET", "/api/wallet"),
    ("GET", "/api/notifications"),
    ("GET", "/api/skills"),
    ("GET", "/api/favorites"),
    ("GET", "/api/jobs"),
    ("GET", "/api/bookings/seeker"),
]
for method, path in seeker_apis:
    test_api(path, seeker_token, method, label="[SEEKER] ")

# ===========================================
# 6. PROVIDER API ENDPOINTS
# ===========================================
print("\n[6] PROVIDER API ENDPOINTS")
provider_apis = [
    ("GET", "/api/provider/dashboard"),
    ("GET", "/api/skills"),
    ("GET", "/api/wallet"),
    ("GET", "/api/notifications"),
    ("GET", "/api/jobs"),
    ("GET", "/api/bookings/provider"),
]
for method, path in provider_apis:
    test_api(path, provider_token, method, label="[PROVIDER] ")

# ===========================================
# 7. SYSTEM & OPS
# ===========================================
print("\n[7] SYSTEM ENDPOINTS")
system_urls = [
    ("/api/system/health", "System Health API"),
    ("/health", "App Health"),
    ("/ops-dashboard", "Ops Dashboard"),
    ("/admin", "Admin Search"),
    ("/ai-assist", "AI Assist"),
]
for path, name in system_urls:
    test_url(path, provider_token, label="[SYSTEM] ")

# ===========================================
# 8. KNOWN BUG: /settings
# ===========================================
print("\n[8] SETTINGS BUG CHECK")
print("  Note: Settings link in UI points to /account (line 591 in main.js)")
test_url("/account", seeker_token, label="[BUG-CHECK SEEKER] ")
test_url("/account", provider_token, label="[BUG-CHECK PROVIDER] ")
test_url("/settings", label="[BUG-CHECK] ")

print("\n" + "=" * 70)
print("AUDIT COMPLETE")
print("=" * 70)
