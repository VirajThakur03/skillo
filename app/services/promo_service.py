from datetime import datetime, timezone
from decimal import Decimal

from ..extensions import db
from ..models import Booking, PromoCode, PromoDiscountType, PromoRedemption


def evaluate_promo(code, booking_amount, user=None):
    normalized_code = (code or "").strip().upper()
    amount = Decimal(str(booking_amount or 0))

    if not normalized_code:
        return False, {"valid": False, "message": "Code not found"}

    promo = PromoCode.query.filter_by(code=normalized_code, active=True).first()
    if not promo:
        return False, {"valid": False, "message": "Code not found"}
    if promo.expires_at and promo.expires_at < datetime.now(timezone.utc):
        return False, {"valid": False, "message": "Code expired"}
    if amount < Decimal(promo.min_order_amount or 0):
        minimum = int(Decimal(promo.min_order_amount or 0))
        return False, {"valid": False, "message": f"Minimum INR {minimum} required"}
    if promo.usage_limit is not None and (promo.used_count or 0) >= promo.usage_limit:
        return False, {"valid": False, "message": "Code usage limit reached"}
    if user is not None:
        existing_redemption = PromoRedemption.query.filter_by(
            promo_code_id=promo.id,
            user_id=user.id,
        ).first()
        if existing_redemption:
            return False, {"valid": False, "message": "Already used"}
        if promo.first_booking_only:
            prior_bookings = Booking.query.filter_by(seeker_id=user.id).count()
            if prior_bookings > 0:
                return False, {"valid": False, "message": "Only valid on your first booking"}

    if promo.discount_type == PromoDiscountType.PERCENT:
        discount = (amount * Decimal(promo.discount_value or 0)) / Decimal("100")
    else:
        discount = Decimal(promo.discount_value or 0)
    if promo.max_discount_amount:
        discount = min(discount, Decimal(promo.max_discount_amount))
    discount = min(discount, amount)
    discount = discount.quantize(Decimal("0.01"))
    final_amount = (amount - discount).quantize(Decimal("0.01"))

    return True, {
        "valid": True,
        "code": promo.code,
        "title": promo.title,
        "promo_id": promo.id,
        "discount_type": promo.discount_type.value.lower(),
        "discount_value": float(Decimal(promo.discount_value or 0)),
        "discount_amount": float(discount),
        "final_amount": float(final_amount),
        "expires_at": promo.expires_at.isoformat() if promo.expires_at else None,
    }


def apply_promo_redemption(promo_id, user_id, booking_id, discount_amount):
    promo = db.session.get(PromoCode, promo_id)
    if not promo:
        raise ValueError("promo not found")

    redemption = PromoRedemption(
        promo_code_id=promo.id,
        user_id=user_id,
        booking_id=booking_id,
        discount_amount=Decimal(str(discount_amount or 0)),
    )
    promo.used_count = int(promo.used_count or 0) + 1
    db.session.add(redemption)
    return redemption
