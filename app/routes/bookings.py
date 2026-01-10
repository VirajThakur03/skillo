# app/routes/bookings.py
from flask import Blueprint, request, jsonify
from ..extensions import db, socketio
from ..models import Booking, Skill, User, BookingStatus, PaymentStatus
from ..config import Config
from ..integrations.whatsapp import send_whatsapp_message
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime

bookings_bp = Blueprint("bookings", __name__)


@bookings_bp.route("", methods=["POST"])
@jwt_required()
def create_booking():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    skill_id = data.get("skill_id")
    scheduled_at = data.get("scheduled_at")
    duration = data.get("duration_minutes", 60)

    if not skill_id or not scheduled_at:
        return {"error": "skill_id and scheduled_at are required"}, 400

    skill = Skill.query.get(skill_id)
    if not skill:
        return {"error": "skill not found"}, 404

    # basic check: provider != seeker
    if skill.provider_id == user_id:
        return {"error": "cannot book your own skill"}, 400

    # parse scheduled_at (expecting ISO string)
    try:
        scheduled_dt = datetime.fromisoformat(scheduled_at)
    except Exception:
        return {"error": "invalid scheduled_at format, use ISO datetime"}, 400

    # --- REFERRAL WALLET LOGIC ---
    seeker = User.query.get(user_id)
    if not seeker:
        return {"error": "user not found"}, 404

    # Convert Numeric price to float safely
    try:
        full_price = float(skill.price or 0.0)
    except Exception:
        full_price = 0.0

    wallet = float(seeker.wallet_balance or 0.0)
    referral_used = min(wallet, full_price)  # use wallet first up to full price
    remaining_to_pay = full_price - referral_used

    # update wallet balance
    seeker.wallet_balance = wallet - referral_used

    # --- monetization: platform fee based on full price ---
    platform_pct = float(getattr(Config, "PLATFORM_FEE_DEFAULT", 5.0))
    platform_fee_amount = (full_price * platform_pct) / 100.0
    worker_earnings = full_price - platform_fee_amount

    booking = Booking(
        seeker_id=user_id,
        provider_id=skill.provider_id,
        skill_id=skill.id,
        scheduled_at=scheduled_dt,
        duration_minutes=duration,
        price=full_price,          # final service price (before wallet)
        currency=skill.currency,
        status=BookingStatus.PENDING,
        payment_status=PaymentStatus.NONE,
        platform_fee_pct=platform_pct,
        platform_fee_amount=platform_fee_amount,
        worker_earnings=worker_earnings,
        referral_credit_used=referral_used,
        # payment gateway placeholders (for later integration)
        payment_intent_id=None,
        payment_ref=None,
    )
    db.session.add(booking)
    db.session.commit()

    # ---------- WhatsApp notifications (optional) ----------
    if getattr(Config, "WHATSAPP_ENABLED", False):
        provider = User.query.get(skill.provider_id)

        if seeker and seeker.phone:
            send_whatsapp_message(
                seeker.phone,
                f"Sklio booking created: #{booking.id} with {provider.name} "
                f"for {skill.title} at {scheduled_dt}. "
                f"Wallet used: ₹{int(referral_used)} • Payable: ₹{int(remaining_to_pay)}"
            )

        if provider and provider.phone:
            send_whatsapp_message(
                provider.phone,
                f"New Sklio job request: #{booking.id} from {seeker.name} for {skill.title}."
            )

    return {
        "id": booking.id,
        "status": booking.status.value,
        "price": float(booking.price),
        "currency": booking.currency,
        "referral_credit_used": referral_used,
        "remaining_to_pay": remaining_to_pay,
        "platform_fee_pct": float(platform_pct),
        "platform_fee_amount": platform_fee_amount,
        "worker_earnings": worker_earnings,
    }, 201


@bookings_bp.route("/<int:booking_id>", methods=["GET"])
@jwt_required()
def get_booking(booking_id):
    user_id = get_jwt_identity()
    booking = Booking.query.get(booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if user_id not in [booking.seeker_id, booking.provider_id]:
        return {"error": "forbidden"}, 403

    return {
        "id": booking.id,
        "skill_id": booking.skill_id,
        "seeker_id": booking.seeker_id,
        "provider_id": booking.provider_id,
        "scheduled_at": booking.scheduled_at.isoformat(),
        "status": booking.status.value,
        "price": float(booking.price) if booking.price is not None else 0.0,
        "currency": booking.currency,
        # monetization fields
        "platform_fee_pct": float(booking.platform_fee_pct)
        if booking.platform_fee_pct is not None
        else None,
        "platform_fee_amount": float(booking.platform_fee_amount)
        if booking.platform_fee_amount is not None
        else None,
        "worker_earnings": float(booking.worker_earnings)
        if booking.worker_earnings is not None
        else None,
        "referral_credit_used": float(booking.referral_credit_used)
        if booking.referral_credit_used is not None
        else 0.0,
        # payment fields
        "payment_status": booking.payment_status.value,
        "payment_intent_id": booking.payment_intent_id,
        "payment_ref": booking.payment_ref,
        # live tracking
        "worker_latitude": booking.worker_latitude,
        "worker_longitude": booking.worker_longitude,
        "worker_last_seen_at": booking.worker_last_seen_at.isoformat()
        if booking.worker_last_seen_at
        else None,
    }


@bookings_bp.route("/<int:booking_id>/location", methods=["POST"])
@jwt_required()
def update_worker_location(booking_id):
    user_id = get_jwt_identity()
    booking = Booking.query.get(booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if booking.provider_id != user_id:
        return {"error": "only the assigned worker may update location"}, 403

    data = request.get_json() or {}
    lat = data.get("latitude")
    lon = data.get("longitude")
    if lat is None or lon is None:
        return {"error": "latitude and longitude required"}, 400

    try:
        booking.worker_latitude = float(lat)
        booking.worker_longitude = float(lon)
    except Exception:
        return {"error": "invalid latitude/longitude"}, 400

    booking.worker_last_seen_at = datetime.utcnow()
    db.session.commit()

    # emit socket event to room: booking_<id>
    socketio.emit(
        "worker_location_update",
        {
            "booking_id": booking.id,
            "latitude": booking.worker_latitude,
            "longitude": booking.worker_longitude,
            "last_seen_at": booking.worker_last_seen_at.isoformat(),
        },
        to=f"booking_{booking.id}",
    )

    # geofence notification (simple version)
    seeker = booking.seeker
    if seeker and seeker.phone and getattr(Config, "WHATSAPP_ENABLED", False):
        # TODO: compute actual distance vs seeker location if available
        # For demo, just always send "worker is on the way"
        send_whatsapp_message(
            seeker.phone,
            f"Your worker for booking #{booking.id} is on the way!",
        )

    return {"ok": True}


@bookings_bp.route("/<int:booking_id>/pay", methods=["POST"])
@jwt_required()
def pay_booking(booking_id):
    """
    Mock payment endpoint:
    - Only seeker can pay
    - Marks payment_status as CAPTURED
    - Sets status to CONFIRMED
    - Fills payment_ref
    """
    user_id = get_jwt_identity()
    booking = Booking.query.get(booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if booking.seeker_id != user_id:
        return {"error": "only the seeker can pay for this booking"}, 403
    if booking.payment_status == PaymentStatus.CAPTURED:
        return {"error": "already paid"}, 400

    data = request.get_json() or {}
    mock_ref = data.get(
        "payment_ref",
        f"MOCK-{booking_id}-{int(datetime.utcnow().timestamp())}"
    )

    booking.payment_status = PaymentStatus.CAPTURED
    booking.status = BookingStatus.CONFIRMED
    booking.payment_ref = mock_ref
    db.session.commit()

    # WhatsApp stub
    seeker = booking.seeker
    provider = booking.provider
    if seeker and seeker.phone and getattr(Config, "WHATSAPP_ENABLED", False):
        send_whatsapp_message(
            seeker.phone,
            f"Payment successful for booking #{booking.id}. "
            f"Your worker {provider.name} is confirmed."
        )
    if provider and provider.phone and getattr(Config, "WHATSAPP_ENABLED", False):
        send_whatsapp_message(
            provider.phone,
            f"Booking #{booking.id} payment received. Job confirmed."
        )

    return {
        "message": "payment captured",
        "booking_id": booking.id,
        "payment_ref": mock_ref,
    }


@bookings_bp.route("/<int:booking_id>/complete", methods=["POST"])
@jwt_required()
def complete_booking(booking_id):
    """
    Mark a booking as completed.
    Allow either seeker or provider to trigger completion.
    Increments provider.completed_jobs.
    """
    user_id = get_jwt_identity()
    booking = Booking.query.get(booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if user_id not in [booking.seeker_id, booking.provider_id]:
        return {"error": "not allowed"}, 403

    booking.status = BookingStatus.COMPLETED
    provider = booking.provider
    provider.completed_jobs = (provider.completed_jobs or 0) + 1
    db.session.commit()

    return {"message": "booking completed"}


@bookings_bp.route("/<int:booking_id>/review", methods=["POST"])
@jwt_required()
def review_booking(booking_id):
    """
    Seeker leaves a rating/review after booking is completed.
    Updates provider.rating and badges.
    """
    user_id = get_jwt_identity()
    booking = Booking.query.get(booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if booking.seeker_id != user_id:
        return {"error": "only seeker can review"}, 403
    if booking.status != BookingStatus.COMPLETED:
        return {"error": "booking must be completed to review"}, 400

    data = request.get_json() or {}
    rating = data.get("rating")
    comment = data.get("comment", "")

    try:
        rating = float(rating)
    except Exception:
        return {"error": "rating must be a number"}, 400
    if rating < 1 or rating > 5:
        return {"error": "rating must be between 1 and 5"}, 400

    provider = booking.provider

    # simple average update
    old_rating = provider.rating or 0
    n = provider.completed_jobs or 1  # avoid divide-by-zero
    provider.rating = (old_rating * (n - 1) + rating) / n

    # simple badges demo
    badges = set(provider.badges or [])
    if provider.rating >= 4.8 and provider.completed_jobs >= 10:
        badges.add("top_rated")
    if provider.completed_jobs >= 20:
        badges.add("expert")
    provider.badges = list(badges)

    db.session.commit()
    return {
        "message": "review saved",
        "provider_rating": provider.rating,
        "badges": provider.badges,
    }
