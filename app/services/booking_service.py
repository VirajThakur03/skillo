from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import current_app

from ..config import Config
from ..extensions import db
from ..models import (
    Booking,
    BookingStatus,
    MembershipStatus,
    MessageType,
    PaymentStatus,
    RoleEnum,
    SubscriptionPlan,
    User,
    UserSubscription,
)
from .marketplace import record_booking_event


def _normalized_place_key(user: User | None) -> str | None:
    if not user:
        return None
    gstin = (getattr(user, "gstin", None) or "").strip().upper()
    if len(gstin) >= 2 and gstin[:2].isdigit():
        return f"gstin:{gstin[:2]}"
    location = (getattr(user, "location", None) or "").strip().lower()
    if not location:
        return None
    parts = [part.strip() for part in location.split(",") if part.strip()]
    return parts[-1] if parts else location


def _active_membership_plan(provider_id: int | None) -> SubscriptionPlan | None:
    if not provider_id:
        return None
    now = datetime.now(timezone.utc)
    subscription = (
        UserSubscription.query
        .filter_by(user_id=provider_id, status=MembershipStatus.ACTIVE)
        .filter(UserSubscription.ends_at.isnot(None))
        .filter(UserSubscription.ends_at > now)
        .order_by(UserSubscription.ends_at.desc())
        .first()
    )
    return subscription.plan if subscription and subscription.plan else None


def _effective_platform_fee_pct(provider_id: int | None) -> Decimal:
    default_pct = Decimal(str(getattr(Config, "PLATFORM_FEE_DEFAULT", 10)))
    plan = _active_membership_plan(provider_id)
    if plan and plan.reduced_fee_pct is not None:
        reduced = Decimal(str(plan.reduced_fee_pct))
        return min(default_pct, max(Decimal("0.00"), reduced))
    return default_pct


def calculate_booking_fees(full_price, amount_payable=None, provider=None, seeker=None):
    """
    Calculate platform fee, GST and worker earnings.

    GST split rule:
    - If both provider and seeker place-of-supply identifiers are available and differ, use IGST.
    - Otherwise default to CGST + SGST split.
    """
    full_price = Decimal(str(full_price or 0))
    if amount_payable is None:
        amount_payable = full_price
    amount_payable = Decimal(str(amount_payable or 0))

    provider_id = provider.id if isinstance(provider, User) else provider
    platform_pct = _effective_platform_fee_pct(provider_id)
    platform_fee_amount = (amount_payable * platform_pct) / Decimal("100")
    platform_fee_amount = round(platform_fee_amount, 2)

    gst_rate = Decimal("0.18")
    gst_amount = round(platform_fee_amount * gst_rate, 2)

    provider_place = _normalized_place_key(provider if isinstance(provider, User) else db.session.get(User, int(provider)) if provider else None)
    seeker_place = _normalized_place_key(seeker if isinstance(seeker, User) else db.session.get(User, int(seeker)) if seeker else None)
    inter_state = bool(provider_place and seeker_place and provider_place != seeker_place)

    if inter_state:
        cgst_amount = Decimal("0.00")
        sgst_amount = Decimal("0.00")
        igst_amount = gst_amount
    else:
        cgst_amount = round(gst_amount / 2, 2)
        sgst_amount = gst_amount - cgst_amount
        igst_amount = Decimal("0.00")

    worker_earnings = round(amount_payable - platform_fee_amount, 2)
    service_amount = full_price - platform_fee_amount - gst_amount

    return {
        "platform_fee_pct": platform_pct,
        "platform_fee_amount": platform_fee_amount,
        "gst_amount": gst_amount,
        "cgst_amount": cgst_amount,
        "sgst_amount": sgst_amount,
        "igst_amount": igst_amount,
        "worker_earnings": worker_earnings,
        "service_amount": max(Decimal("0.00"), round(service_amount, 2)),
        "tax_mode": "igst" if inter_state else "cgst_sgst",
    }


def create_booking_from_job(job, proposal):
    """Convert a JobPost and JobProposal into a Booking."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    amount_payable = proposal.quoted_amount
    seeker = db.session.get(User, job.seeker_id)
    provider = db.session.get(User, proposal.provider_id)
    fees = calculate_booking_fees(
        amount_payable,
        amount_payable,
        provider=provider,
        seeker=seeker,
    )

    booking = Booking(
        seeker_id=job.seeker_id,
        provider_id=proposal.provider_id,
        job_post_id=job.id,
        scheduled_at=job.scheduled_for or now + timedelta(days=1),
        duration_minutes=proposal.estimated_duration_minutes or 60,
        price=proposal.quoted_amount,
        currency=job.currency or "INR",
        status=BookingStatus.PENDING,
        payment_status=PaymentStatus.NONE,
        platform_fee_pct=fees["platform_fee_pct"],
        platform_fee_amount=fees["platform_fee_amount"],
        gst_amount=fees["gst_amount"],
        cgst_amount=fees["cgst_amount"],
        sgst_amount=fees["sgst_amount"],
        igst_amount=fees["igst_amount"],
        sac_code=current_app.config.get("PLATFORM_SAC_CODE", "998599"),
        service_amount=fees["service_amount"],
        worker_earnings=fees["worker_earnings"],
        amount_payable=amount_payable,
        payment_provider=(current_app.config.get("PAYMENT_PROVIDER") or "mock").lower(),
    )

    db.session.add(booking)
    db.session.flush()

    record_booking_event(
        booking,
        "requested_from_job",
        actor_user_id=job.seeker_id,
        payload={
            "status": BookingStatus.PENDING.value,
            "summary": f"Booking created from Job Post #{job.id}",
        },
    )

    return booking
