# app/services/fraud_service.py
"""Fraud detection signals for bookings and payments."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import current_app

from ..extensions import db
from ..models import Booking, BookingStatus, User


def _utc_now():
    return datetime.now(timezone.utc)


def check_fraud_signals(booking, user) -> dict:
    """
    Evaluate fraud risk for a booking/payment.
    Returns: { risk_score: 0-100, flags: [...], action: "allow"|"review"|"block" }
    """
    flags = []
    now = _utc_now()

    # --- 1. Velocity check: too many bookings in 1 hour ---
    max_per_hour = int(current_app.config.get("FRAUD_MAX_BOOKINGS_PER_HOUR", 5))
    one_hour_ago = now - timedelta(hours=1)
    recent_count = Booking.query.filter(
        Booking.seeker_id == user.id,
        Booking.created_at >= one_hour_ago,
    ).count()
    if recent_count >= max_per_hour:
        flags.append({"code": "velocity", "detail": f"{recent_count} bookings in last hour"})

    # --- 2. Amount anomaly: booking > 3x user's average ---
    avg_price_row = (
        db.session.query(db.func.avg(Booking.price))
        .filter(
            Booking.seeker_id == user.id,
            Booking.status != BookingStatus.CANCELLED,
        )
        .scalar()
    )
    if avg_price_row and booking.price:
        avg_price = Decimal(str(avg_price_row or 0))
        if avg_price > 0 and Decimal(str(booking.price)) > avg_price * 3:
            flags.append({
                "code": "amount_anomaly",
                "detail": f"₹{booking.price} vs avg ₹{avg_price:.0f}",
            })

    # --- 3. New account + high value ---
    threshold = Decimal(current_app.config.get("FRAUD_HIGH_VALUE_THRESHOLD", 5000))
    if user.created_at:
        account_age = now - user.created_at.replace(tzinfo=timezone.utc) if user.created_at.tzinfo is None else now - user.created_at
        if account_age < timedelta(hours=24) and Decimal(str(booking.price or 0)) > threshold:
            flags.append({
                "code": "new_account_high_value",
                "detail": f"Account age {account_age.total_seconds() / 3600:.0f}h, amount ₹{booking.price}",
            })

    # --- 4. Rapid cancellation pattern ---
    one_day_ago = now - timedelta(days=1)
    cancel_count = Booking.query.filter(
        Booking.seeker_id == user.id,
        Booking.status == BookingStatus.CANCELLED,
        Booking.updated_at >= one_day_ago,
    ).count()
    if cancel_count >= 3:
        flags.append({"code": "rapid_cancellations", "detail": f"{cancel_count} cancellations in 24h"})

    # --- Score ---
    risk_score = min(len(flags) * 20, 100)
    block_threshold = int(current_app.config.get("FRAUD_BLOCK_SCORE", 60))

    if risk_score >= block_threshold:
        action = "block"
    elif risk_score >= 30:
        action = "review"
    else:
        action = "allow"

    return {"risk_score": risk_score, "flags": flags, "action": action}
