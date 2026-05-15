from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import hmac
import json
from time import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app


class PaymentProviderError(RuntimeError):
    pass


class PaymentConfigurationError(PaymentProviderError):
    pass


@dataclass
class PaymentCaptureResult:
    provider: str
    reference: str
    amount: Decimal


@dataclass
class CheckoutSessionResult:
    provider: str
    session_id: str
    checkout_url: str
    payment_intent_id: str | None
    amount: Decimal
    currency: str


def _amount_due(booking) -> Decimal:
    amount = getattr(booking, "amount_payable", None)
    if amount is None:
        wallet_credit = Decimal(getattr(booking, "referral_credit_used", 0) or 0)
        promo_discount = Decimal(getattr(booking, "promo_discount_amount", 0) or 0)
        amount = Decimal(booking.price or 0) - wallet_credit - promo_discount
    amount = Decimal(amount or 0)
    return max(amount, Decimal("0.00"))


def _provider() -> str:
    return (current_app.config.get("PAYMENT_PROVIDER") or "mock").lower()


def _mode() -> str:
    return (current_app.config.get("PAYMENT_MODE") or "mock").lower()


def _assert_realtime_payments_enabled():
    env = (current_app.config.get("ENV") or "development").lower()
    provider = _provider()
    mode = _mode()

    if env != "development":
        if provider != "stripe" or mode != "real":
            raise PaymentConfigurationError(
                "real Stripe payments are mandatory outside development"
            )
        if current_app.config.get("ALLOW_MOCK_PAYMENTS"):
            raise PaymentConfigurationError(
                "mock payments cannot be enabled outside development"
            )


def _stripe_secret_key() -> str:
    _assert_realtime_payments_enabled()
    secret_key = current_app.config.get("STRIPE_SECRET_KEY")
    if not secret_key:
        raise PaymentConfigurationError("STRIPE_SECRET_KEY is not configured")
    return secret_key


def _as_minor_units(amount: Decimal, currency: str) -> int:
    normalized = Decimal(amount or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    zero_decimal = {
        "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga",
        "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
    }
    if currency.lower() in zero_decimal:
        return int(normalized)
    return int((normalized * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def create_checkout_session(booking, *, success_url: str, cancel_url: str) -> CheckoutSessionResult:
    if _provider() != "stripe" or _mode() != "real":
        raise PaymentConfigurationError("checkout session is only available for real Stripe payments")

    amount = _amount_due(booking)
    if amount <= 0:
        raise PaymentProviderError("booking does not require payment")

    currency = (getattr(booking, "currency", None) or current_app.config.get("STRIPE_CURRENCY", "inr")).lower()
    service_name = getattr(getattr(booking, "skill", None), "title", None) or f"Booking #{booking.id}"
    customer_email = getattr(getattr(booking, "seeker", None), "email", None)

    metadata = {
        "booking_id": str(booking.id),
        "seeker_id": str(booking.seeker_id),
        "provider_id": str(booking.provider_id),
    }
    idempotency_key = f"booking-{booking.id}-checkout-session"
    form_pairs = [
        ("mode", "payment"),
        ("success_url", success_url),
        ("cancel_url", cancel_url),
        ("client_reference_id", str(booking.id)),
        ("line_items[0][quantity]", "1"),
        ("line_items[0][price_data][currency]", currency),
        ("line_items[0][price_data][product_data][name]", service_name),
        ("line_items[0][price_data][unit_amount]", str(_as_minor_units(amount, currency))),
        ("expires_at", str(int(datetime.now(timezone.utc).timestamp()) + 1800)),
    ]
    if customer_email:
        form_pairs.append(("customer_email", customer_email))
    for key, value in metadata.items():
        form_pairs.append((f"metadata[{key}]", value))
        form_pairs.append((f"payment_intent_data[metadata][{key}]", value))

    body = urlencode(form_pairs).encode("utf-8")
    request = Request(
        "https://api.stripe.com/v1/checkout/sessions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {_stripe_secret_key()}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Idempotency-Key": idempotency_key,
        },
    )

    with urlopen(request, timeout=30) as response:
        session = json.loads(response.read().decode("utf-8"))

    return CheckoutSessionResult(
        provider="stripe",
        session_id=session.get("id"),
        checkout_url=session.get("url"),
        payment_intent_id=session.get("payment_intent"),
        amount=amount,
        currency=currency.upper(),
    )


def create_wallet_topup_checkout_session(
    user,
    amount: Decimal,
    *,
    success_url: str,
    cancel_url: str,
    topup_reference: str,
) -> CheckoutSessionResult:
    if _provider() != "stripe" or _mode() != "real":
        raise PaymentConfigurationError(
            "wallet top-up checkout is only available for real Stripe payments"
        )

    amount = Decimal(amount or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise PaymentProviderError("wallet top-up amount must be positive")

    currency = (current_app.config.get("STRIPE_CURRENCY", "inr") or "inr").lower()
    customer_email = getattr(user, "email", None)
    metadata = {
        "flow": "wallet_topup",
        "topup_reference": str(topup_reference),
        "user_id": str(user.id),
    }
    idempotency_key = f"wallet-topup-{topup_reference}"
    form_pairs = [
        ("mode", "payment"),
        ("success_url", success_url),
        ("cancel_url", cancel_url),
        ("client_reference_id", str(topup_reference)),
        ("line_items[0][quantity]", "1"),
        ("line_items[0][price_data][currency]", currency),
        ("line_items[0][price_data][product_data][name]", "Sklio Wallet Top-up"),
        (
            "line_items[0][price_data][product_data][description]",
            f"Add INR {amount} to your Sklio wallet",
        ),
        (
            "line_items[0][price_data][unit_amount]",
            str(_as_minor_units(amount, currency)),
        ),
        ("expires_at", str(int(datetime.now(timezone.utc).timestamp()) + 1800)),
    ]
    if customer_email:
        form_pairs.append(("customer_email", customer_email))
    for key, value in metadata.items():
        form_pairs.append((f"metadata[{key}]", value))
        form_pairs.append((f"payment_intent_data[metadata][{key}]", value))

    body = urlencode(form_pairs).encode("utf-8")
    request = Request(
        "https://api.stripe.com/v1/checkout/sessions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {_stripe_secret_key()}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Idempotency-Key": idempotency_key,
        },
    )

    with urlopen(request, timeout=30) as response:
        session = json.loads(response.read().decode("utf-8"))

    return CheckoutSessionResult(
        provider="stripe",
        session_id=session.get("id"),
        checkout_url=session.get("url"),
        payment_intent_id=session.get("payment_intent"),
        amount=amount,
        currency=currency.upper(),
    )


def create_stripe_connect_account(user_email, user_id):
    """Creates a Stripe Express account for a provider."""
    idempotency_key = f"user-{user_id}-connect-account"
    form_pairs = [
        ("type", "express"),
        ("email", user_email),
        ("capabilities[card_payments][requested]", "true"),
        ("capabilities[transfers][requested]", "true"),
        ("metadata[user_id]", str(user_id)),
    ]
    body = urlencode(form_pairs).encode("utf-8")
    request = Request(
        "https://api.stripe.com/v1/accounts",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {_stripe_secret_key()}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Idempotency-Key": idempotency_key,
        },
    )

    with urlopen(request, timeout=30) as response:
        account = json.loads(response.read().decode("utf-8"))

    return account.get("id")


def create_stripe_account_link(stripe_account_id, refresh_url, return_url):
    """Creates an onboarding link for a Stripe Express account."""
    form_pairs = [
        ("account", stripe_account_id),
        ("refresh_url", refresh_url),
        ("return_url", return_url),
        ("type", "account_onboarding"),
    ]
    body = urlencode(form_pairs).encode("utf-8")
    request = Request(
        "https://api.stripe.com/v1/account_links",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {_stripe_secret_key()}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    with urlopen(request, timeout=30) as response:
        link = json.loads(response.read().decode("utf-8"))

    return link.get("url")


def get_stripe_account(stripe_account_id):
    """Retrieves Stripe account details to check onboarding status."""
    request = Request(
        f"https://api.stripe.com/v1/accounts/{stripe_account_id}",
        method="GET",
        headers={
            "Authorization": f"Bearer {_stripe_secret_key()}",
        },
    )

    with urlopen(request, timeout=30) as response:
        account = json.loads(response.read().decode("utf-8"))

    return account


def trigger_stripe_transfer(stripe_account_id, amount, currency, description=None):
    """Transfers funds from the platform account to a connected Express account."""
    currency = currency.lower()
    idempotency_key = f"transfer-{stripe_account_id}-{int(datetime.now(timezone.utc).timestamp())}"
    form_pairs = [
        ("amount", str(_as_minor_units(amount, currency))),
        ("currency", currency),
        ("destination", stripe_account_id),
    ]
    if description:
        form_pairs.append(("description", description))
        
    body = urlencode(form_pairs).encode("utf-8")
    request = Request(
        "https://api.stripe.com/v1/transfers",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {_stripe_secret_key()}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Idempotency-Key": idempotency_key,
        },
    )

    with urlopen(request, timeout=30) as response:
        transfer = json.loads(response.read().decode("utf-8"))

    return transfer.get("id")


def capture_booking_payment(booking, payment_ref=None):
    provider = _provider()
    if provider == "mock":
        if not current_app.config.get("ALLOW_MOCK_PAYMENTS", True):
            raise PaymentProviderError("mock payments are disabled")
        if _mode() != "mock":
            raise PaymentProviderError("mock capture is only available in mock payment mode")

        reference = payment_ref or f"MOCK-{booking.id}-{int(datetime.now(timezone.utc).timestamp())}"
        return PaymentCaptureResult(
            provider="mock",
            reference=reference,
            amount=_amount_due(booking),
        )

    raise PaymentProviderError(
        f"payment provider '{provider}' is not configured for direct capture"
    )


def construct_webhook_event(payload: bytes, signature_header: str, secret: str) -> Any:
    if _provider() != "stripe":
        raise PaymentConfigurationError("webhook construction is only supported for Stripe")
    if not signature_header:
        raise PaymentProviderError("missing Stripe-Signature header")

    timestamp = None
    signatures = []
    for part in signature_header.split(","):
        item = part.strip()
        if item.startswith("t="):
            timestamp = item.split("=", 1)[1]
        elif item.startswith("v1="):
            signatures.append(item.split("=", 1)[1])

    if not timestamp or not signatures:
        raise PaymentProviderError("invalid Stripe-Signature header")
    if abs(time() - int(timestamp)) > 300:
        raise PaymentProviderError("stale Stripe webhook timestamp")

    signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise PaymentProviderError("signature verification failed")

    return json.loads(payload.decode("utf-8"))
