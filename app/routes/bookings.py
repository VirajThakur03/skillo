# app/routes/bookings.py
from flask import Blueprint, request, jsonify, current_app
from threading import Thread
from sqlalchemy import inspect
from sqlalchemy.orm import joinedload
from ..config import Config
from ..extensions import db, limiter, socketio
from ..models import (
    AuditLog,
    Booking,
    BookingTimelineEvent,
    Skill,
    User,
    Review,
    BookingStatus,
    PaymentStatus,
    RefundStatus,
    RoleEnum,
    WalletTransaction,
)
from decimal import Decimal
from ..integrations.whatsapp import send_whatsapp_message
from ..services.marketplace import preview_cancellation, provider_is_available, record_booking_event
from ..services.notification_triggers import notify_booking_status_change
from ..services.payments import (
    PaymentConfigurationError,
    PaymentProviderError,
    capture_booking_payment,
    create_checkout_session,
)
from ..services.payment_service import generate_booking_invoice, generate_commission_invoice
from ..services.promo_service import apply_promo_redemption, evaluate_promo
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta, timezone
from ..utils import haversine

bookings_bp = Blueprint("bookings", __name__)


def _timeline_event_summary(event_type, payload=None):
    payload = payload or {}
    lookup = {
        "requested": "Booking requested",
        "confirmed": "Booking confirmed",
        "declined": "Booking declined",
        "cancelled": "Booking cancelled",
        "payment_captured": "Payment captured",
        "payment_failed": "Payment failed",
        "refunded": "Payment refunded",
        "location_shared": "Live location shared",
        "in_progress": "Service started",
        "completed": "Service completed",
        "review_submitted": "Review submitted",
    }
    return payload.get("summary") or lookup.get(event_type, event_type.replace("_", " ").title())


def _latest_timeline_preview_map(bookings):
    if not bookings:
        return {}
    booking_ids = [booking.id for booking in bookings]
    events = (
        BookingTimelineEvent.query
        .filter(BookingTimelineEvent.booking_id.in_(booking_ids))
        .order_by(BookingTimelineEvent.created_at.desc(), BookingTimelineEvent.id.desc())
        .all()
    )
    preview_map = {}
    for event in events:
        if event.booking_id in preview_map:
            continue
        preview_map[event.booking_id] = {
            "event_type": event.event_type,
            "summary": _timeline_event_summary(event.event_type, event.payload),
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
    return preview_map


def _provider_cancellation_policy(provider):
    cutoff_hours = int(getattr(provider, "cancellation_cutoff_hours", 2) or 2)
    fee_percent = int(getattr(provider, "cancellation_fee_pct", 20) or 20)
    return {
        "cutoff_hours": cutoff_hours,
        "fee_percent": fee_percent,
        "free_before": f"{cutoff_hours} hours before start",
        "fee_after": f"{fee_percent}% of booking amount",
        "custom_text": getattr(provider, "cancellation_policy_text", None),
    }


def _invoice_payload_for_booking(booking):
    total = Decimal(getattr(booking, "amount_payable", None) or booking.price or 0)
    platform_fee = Decimal(booking.platform_fee_amount or 0)
    gst_amount = Decimal(booking.gst_amount or 0)
    service_amount = Decimal(booking.service_amount or (total - platform_fee - gst_amount))
    if service_amount < 0:
        service_amount = Decimal("0.00")

    status = None
    if booking.status == BookingStatus.COMPLETED and not booking.invoice_url:
        status = "generating"

    return {
        "status": status,
        "number": booking.invoice_number,
        "url": booking.invoice_url,
        "service": float(service_amount),
        "platform_fee": float(platform_fee),
        "gst": float(gst_amount),
        "total": float(total),
        "generated_at": booking.invoice_generated_at.isoformat() if booking.invoice_generated_at else None,
    }


def _generate_invoice_async(booking_id: int, max_retries: int = 3):
    app = current_app._get_current_object()

    def _run():
        import time
        from random import uniform
        attempt = 0
        while attempt < max_retries:
            with app.app_context():
                try:
                    generate_booking_invoice(str(booking_id))
                    app.logger.info(f"booking.invoice_generated success: {booking_id}")
                    return # Success
                except Exception as exc:
                    attempt += 1
                    wait_time = (2 ** attempt) + uniform(0, 1)
                    app.logger.warning(
                        f"booking.invoice_generation_failed attempt {attempt}/{max_retries}",
                        extra={"booking_id": booking_id, "error": str(exc)},
                    )
                    if attempt < max_retries:
                        time.sleep(wait_time)
                    else:
                        app.logger.error(
                            "booking.invoice_generation_abandoned",
                            extra={"booking_id": booking_id, "error": str(exc)},
                        )

    if app.testing:
        _run()
        return

    Thread(target=_run, daemon=True).start()


def _amount_due_for_booking(booking):
    total = Decimal(getattr(booking, "amount_payable", None) or booking.price or 0)
    return max(total, Decimal("0.00"))


@bookings_bp.route("", methods=["POST"])
@limiter.limit(lambda: current_app.config.get("BOOKING_RATE_LIMIT", "20 per hour"))
@jwt_required()
def create_booking():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    skill_id = data.get("skill_id")
    provider_id = data.get("provider_id")   # ✅ NEW
    scheduled_at = data.get("scheduled_at")
    duration = int(data.get("duration_minutes", 60))
    promo_code = (data.get("promo_code") or "").strip()

    if not skill_id or not scheduled_at:
        current_app.logger.warning("booking.create_failed.missing_fields", extra={"skill_id": skill_id, "scheduled_at": scheduled_at})
        return {"error": "skill_id and scheduled_at are required"}, 400

    if not provider_id:
        current_app.logger.warning("booking.create_failed.missing_provider", extra={"skill_id": skill_id})
        return {"error": "provider_id is required"}, 400

    seeker = db.session.get(User, user_id)
    if not seeker:
        return {"error": "user not found"}, 404

    # ✅ only SEEKER can book
    if seeker.role != RoleEnum.SEEKER:
        return {"error": "only seekers can create bookings"}, 403

    skill = db.session.get(Skill, skill_id)
    if not skill or not skill.is_active:
        return {"error": "skill not found"}, 404

    # 🔒 CRITICAL SECURITY CHECK
    if skill.provider_id != int(provider_id):
        return {"error": "invalid provider for this skill"}, 400

    # prevent self booking
    if skill.provider_id == seeker.id:
        return {"error": "cannot book your own skill"}, 400

    # Prevent duplicate active bookings for the same seeker+provider+skill.
    # This blocks spam clicks on the same job while still allowing:
    # - same seeker booking a different provider for same skill
    # - same seeker booking same provider for a different skill
    duplicate_booking = (
        Booking.query.filter(
            Booking.seeker_id == seeker.id,
            Booking.provider_id == int(provider_id),
            Booking.skill_id == skill.id,
            Booking.status.in_([
                BookingStatus.PENDING,
                BookingStatus.CONFIRMED,
                BookingStatus.IN_PROGRESS,
            ]),
        )
        .order_by(Booking.created_at.desc())
        .first()
    )
    if duplicate_booking:
        AuditLog.record(
            "booking.duplicate_blocked",
            actor_id=seeker.id,
            actor_role=seeker.role.value,
            target_type="booking",
            target_id=duplicate_booking.id,
            metadata={
                "seeker_id": seeker.id,
                "provider_id": int(provider_id),
                "conflicting_booking_id": duplicate_booking.id,
                "scheduled_at": scheduled_at,
            },
            request=request,
        )
        db.session.commit()
        return {
            "error": "You already have an active booking for this provider and service",
            "existing_booking_id": duplicate_booking.id,
            "existing_status": duplicate_booking.status.value,
        }, 409

    try:
        raw_scheduled_at = str(scheduled_at).strip()
        if raw_scheduled_at.endswith("Z"):
            raw_scheduled_at = raw_scheduled_at[:-1] + "+00:00"
        scheduled_dt = datetime.fromisoformat(raw_scheduled_at)
    except Exception as e:
        current_app.logger.warning("booking.create_failed.invalid_date", extra={"scheduled_at": scheduled_at, "error": str(e)})
        return {"error": "invalid scheduled_at format (ISO required)"}, 400

    if scheduled_dt.tzinfo is None:
        current_app.logger.warning("booking.create_failed.no_timezone", extra={"scheduled_at": scheduled_at})
        return {
            "error": "scheduled_at must include a timezone offset",
            "message": "Please choose a time slot from the calendar.",
        }, 400

    scheduled_dt = scheduled_dt.astimezone(timezone.utc).replace(tzinfo=None)

    if scheduled_dt < datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2):
        return {
            "error": "scheduled_at must be at least 2 hours in the future",
        }, 400

    available, availability_reason = provider_is_available(
        int(provider_id),
        scheduled_dt,
        duration,
        skill_id=skill.id,
    )
    if not available:
        return {
            "error": "slot_taken",
            "message": "That time is no longer available. Please choose another.",
            "reason": availability_reason,
        }, 409

    # ------------------------------
    # 🛡️ FRAUD CHECK
    # ------------------------------
    try:
        from ..services.fraud_service import check_fraud_signals
        # Create a temporary booking-like object for fraud check
        class _TempBooking:
            pass
        _tb = _TempBooking()
        _tb.price = Decimal(skill.price or 0) * (Decimal(duration) / Decimal(60))
        _tb.seeker_id = seeker.id
        fraud_result = check_fraud_signals(_tb, seeker)
        if fraud_result["action"] == "block":
            current_app.logger.warning(
                "booking.fraud_blocked",
                extra={"seeker_id": seeker.id, "risk_score": fraud_result["risk_score"], "flags": fraud_result["flags"]},
            )
            return {
                "error": "booking_blocked",
                "message": "Unable to process this booking. Please contact support.",
            }, 403
    except Exception as exc:
        current_app.logger.warning(f"fraud_check_error: {exc}")

    # ------------------------------
    # 💰 PRICE CALC
    # ------------------------------
    base_price = Decimal(skill.price or 0)
    hours = Decimal(duration) / Decimal(60)
    full_price = base_price * hours

    # ------------------------------
    # 🎁 WALLET
    # ------------------------------
    wallet_balance = Decimal(seeker.wallet_balance or 0)
    referral_used = min(wallet_balance, full_price)
    payable_amount = full_price - referral_used
    promo_discount = Decimal("0.00")
    promo_validation = None
    if promo_code:
        is_valid_promo, promo_payload = evaluate_promo(
            promo_code,
            payable_amount,
            user=seeker,
        )
        if not is_valid_promo:
            return {
                "error": "promo_invalid",
                "message": promo_payload.get("message", "Promo code could not be applied"),
            }, 409
        promo_validation = promo_payload
        promo_discount = Decimal(str(promo_payload["discount_amount"]))
        payable_amount = max(Decimal("0.00"), payable_amount - promo_discount)

    # ------------------------------
    # 🧾 CALCULATE FEES
    # ------------------------------
    from app.services.booking_service import calculate_booking_fees
    fees = calculate_booking_fees(
        full_price,
        payable_amount,
        provider=int(provider_id),
        seeker=seeker,
    )

    # ------------------------------
    # 🧾 CREATE BOOKING
    # ------------------------------
    booking = Booking(
        seeker_id=seeker.id,
        provider_id=int(provider_id),
        skill_id=skill.id,
        scheduled_at=scheduled_dt,
        duration_minutes=duration,
        price=full_price,
        currency=skill.currency,
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
        referral_credit_used=referral_used,
        promo_discount_amount=promo_discount,
        amount_payable=payable_amount,
        payment_provider=(current_app.config.get("PAYMENT_PROVIDER") or "mock").lower(),
        payment_intent_id=None,
        payment_checkout_session_id=None,
        payment_ref=None,
    )

    db.session.add(booking)
    db.session.flush()
    record_booking_event(
        booking,
        "requested",
        actor_user_id=seeker.id,
        payload={
            "status": BookingStatus.PENDING.value,
            "summary": "Booking requested",
        },
    )

    # ✅ deduct wallet AFTER booking object is ready
    if referral_used > 0:
        from ..services.wallet_service import debit as wallet_debit
        from ..models import WalletTransactionType
        wallet_debit(
            user_id=seeker.id,
            amount=referral_used,
            txn_type=WalletTransactionType.DEBIT_BOOKING,
            description=f"Wallet credit applied to booking #{booking.id}",
            reference_type="booking",
            reference_id=booking.id,
            allow_negative=False,
        )
    if promo_validation:
        apply_promo_redemption(
            promo_validation["promo_id"],
            seeker.id,
            booking.id,
            promo_discount,
        )
    AuditLog.record(
        "booking.created",
        actor_id=seeker.id,
        actor_role=seeker.role.value,
        target_type="booking",
        target_id=booking.id,
        metadata={
            "booking_id": booking.id,
            "amount": float(booking.price or 0),
        },
        request=request,
    )

    db.session.commit()
    if referral_used > 0:
        from ..services.wallet_service import emit_wallet_update
        emit_wallet_update(seeker.id)
    if payable_amount <= 0:
        booking.payment_status = PaymentStatus.CAPTURED
        booking.status = BookingStatus.CONFIRMED
        booking.payment_ref = "WALLET_COVERED"
        record_booking_event(
            booking,
            "payment_captured",
            actor_user_id=seeker.id,
            payload={"summary": "Payment captured with wallet credits"},
        )
        record_booking_event(
            booking,
            "confirmed",
            actor_user_id=seeker.id,
            payload={"status": BookingStatus.CONFIRMED.value, "summary": "Booking confirmed"},
        )
        notify_booking_status_change(
            booking=booking,
            new_status="confirmed",
            changed_by_role="system",
        )
        db.session.commit()
    current_app.logger.info(
        "booking.created",
        extra={
            "booking_id": booking.id,
            "seeker_id": booking.seeker_id,
            "provider_id": booking.provider_id,
            "category": skill.title,
            "amount": float(booking.price or 0),
        },
    )

    # ------------------------------
    # 📲 WHATSAPP (OPTIONAL)
    # ------------------------------
    if getattr(Config, "WHATSAPP_ENABLED", False):
        provider = db.session.get(User, int(provider_id))

        if seeker.phone:
            send_whatsapp_message(
                seeker.phone,
                f"✅ Booking #{booking.id} created\n"
                f"Service: {skill.title}\n"
                f"Wallet used: ₹{int(referral_used)}\n"
                f"Payable: ₹{int(payable_amount)}"
            )

        if provider and provider.phone:
            send_whatsapp_message(
                provider.phone,
                f"📢 New job request #{booking.id}\n"
                f"Service: {skill.title}\n"
                f"From: {seeker.name}"
            )

    return {
        "id": booking.id,
        "status": booking.status.value,
        "full_price": float(full_price),
        "currency": booking.currency,
        "wallet_used": float(referral_used),
        "promo_code": promo_validation["code"] if promo_validation else None,
        "promo_discount": float(promo_discount),
        "payable_amount": float(payable_amount),
        "platform_fee_pct": float(fees["platform_fee_pct"]),
        "platform_fee_amount": float(fees["platform_fee_amount"]),
        "gst_amount": float(fees["gst_amount"]),
        "service_amount": float(fees["service_amount"]),
        "worker_earnings": float(fees["worker_earnings"]),
    }, 201

@bookings_bp.route("/<int:booking_id>", methods=["GET"])
@jwt_required()
def get_booking(booking_id):
    user_id = int(get_jwt_identity())
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if user_id not in [booking.seeker_id, booking.provider_id]:
        return {"error": "forbidden"}, 403

    if booking.status == BookingStatus.COMPLETED and booking.invoice_url is None:
        _generate_invoice_async(booking.id)

    payload = {
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
        "payment_provider": booking.payment_provider,
        "payment_intent_id": booking.payment_intent_id,
        "payment_checkout_session_id": booking.payment_checkout_session_id,
        "payment_ref": booking.payment_ref,
        "amount_payable": float(getattr(booking, "amount_payable", None) or booking.price or 0),
        # live tracking
        "worker_latitude": booking.worker_latitude,
        "worker_longitude": booking.worker_longitude,
        "worker_last_seen_at": booking.worker_last_seen_at.isoformat()
        if booking.worker_last_seen_at
        else None,
        "cancellation_policy": _provider_cancellation_policy(booking.provider),
        "cancellation_reason": getattr(booking, "cancellation_reason", None),
        "invoice": _invoice_payload_for_booking(booking),
    }
    if user_id == booking.provider_id:
        payload["provider_notes"] = booking.provider_notes
    return payload


@bookings_bp.route("/<int:booking_id>/change-policy-preview", methods=["GET"])
@jwt_required()
def booking_change_policy_preview(booking_id):
    user_id = int(get_jwt_identity())
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if user_id not in [booking.seeker_id, booking.provider_id]:
        return {"error": "forbidden"}, 403

    preview = preview_cancellation(booking, actor_user_id=user_id)
    preview["cancellation_policy"] = _provider_cancellation_policy(booking.provider)
    preview["scheduled_at"] = booking.scheduled_at.isoformat() if booking.scheduled_at else None
    return preview, 200


@bookings_bp.route("/<int:booking_id>/cancel", methods=["POST"])
@jwt_required()
def cancel_booking(booking_id):
    user_id = int(get_jwt_identity())
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if user_id not in [booking.seeker_id, booking.provider_id]:
        return {"error": "forbidden"}, 403
    if booking.status in {BookingStatus.CANCELLED, BookingStatus.COMPLETED, BookingStatus.DECLINED}:
        return {"error": "booking cannot be cancelled"}, 400

    preview = preview_cancellation(booking, actor_user_id=user_id)
    booking.status = BookingStatus.CANCELLED

    # Store cancellation reason if provided
    _body = request.get_json(silent=True) or {}
    reason_code = (_body.get("reason_code") or "").strip()
    if reason_code:
        try:
            booking.cancellation_reason = reason_code
        except Exception:
            pass  # column may not exist in older deploys

    # ── Issue actual refund to seeker's wallet ──
    refund_amount = Decimal(str(preview["refund_amount"] or 0))
    refund_issued = False
    if refund_amount > 0 and booking.payment_status == PaymentStatus.CAPTURED:
        from ..services.wallet_service import credit as wallet_credit, emit_wallet_update
        from ..models import WalletTransactionType
        wallet_credit(
            user_id=booking.seeker_id,
            amount=refund_amount,
            txn_type=WalletTransactionType.CREDIT_REFUND,
            description=f"Cancellation refund for booking #{booking.id}",
            reference_type="booking",
            reference_id=booking.id,
        )
        booking.payment_status = PaymentStatus.REFUNDED
        booking.refund_amount = refund_amount
        booking.refund_status = RefundStatus.PROCESSED
        booking.refund_completed_at = datetime.now(timezone.utc)
        booking.refund_ref = f"CANCEL-REFUND-{booking.id}-{int(datetime.now(timezone.utc).timestamp())}"
        refund_issued = True

    notify_booking_status_change(
        booking=booking,
        new_status="cancelled",
        changed_by_role="provider" if user_id == booking.provider_id else "seeker",
        refund_amount=preview["refund_amount"],
    )
    record_booking_event(
        booking,
        "cancelled",
        actor_user_id=user_id,
        payload={
            "status": BookingStatus.CANCELLED.value,
            "reason_code": reason_code or "user_requested",
            "refund_amount": float(preview["refund_amount"] or 0),
            "refund_issued": refund_issued,
            "summary": "Booking cancelled",
        },
    )
    AuditLog.record(
        "booking.cancelled",
        actor_id=user_id,
        actor_role="provider" if user_id == booking.provider_id else "seeker",
        target_type="booking",
        target_id=booking.id,
        metadata={
            "booking_id": booking.id,
            "cancelled_by": "provider" if user_id == booking.provider_id else "seeker",
            "fee_charged": float(preview["fee_amount"] or 0),
            "refund_amount": float(refund_amount),
            "refund_issued": refund_issued,
            "reason_code": reason_code or "user_requested",
        },
        request=request,
    )
    db.session.commit()

    # Emit wallet update after commit so the seeker sees new balance
    if refund_issued:
        emit_wallet_update(booking.seeker_id)

    current_app.logger.warning(
        "booking.cancelled",
        extra={
            "booking_id": booking.id,
            "cancelled_by": "provider" if user_id == booking.provider_id else "seeker",
            "reason": reason_code or "user_requested",
            "fee_applied": float(preview["fee_amount"] or 0),
            "refund_amount": float(refund_amount),
            "refund_issued": refund_issued,
        },
    )
    return {
        "success": True,
        "status": booking.status.value,
        "refund_status": "PROCESSED" if refund_issued else "NOT_APPLICABLE",
        "refund_amount": float(refund_amount),
        "fee_charged": preview["fee_amount"],
        "policy_applied": preview["policy_label"],
        "cancellation_policy": _provider_cancellation_policy(booking.provider),
    }, 200



@bookings_bp.route("/<int:booking_id>/location", methods=["POST"])
@jwt_required()
def update_worker_location(booking_id):
    user_id = int(get_jwt_identity())
    booking = db.session.get(Booking, booking_id)
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

    if booking.status == BookingStatus.CONFIRMED:
        booking.status = BookingStatus.IN_PROGRESS
        record_booking_event(
            booking,
            "in_progress",
            actor_user_id=user_id,
            payload={"status": BookingStatus.IN_PROGRESS.value, "summary": "Service started"},
        )
    booking.worker_last_seen_at = datetime.now(timezone.utc)
    record_booking_event(
        booking,
        "location_shared",
        actor_user_id=user_id,
        payload={
            "latitude": booking.worker_latitude,
            "longitude": booking.worker_longitude,
            "summary": "Live location shared",
        },
    )
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
        msg = f"Your worker for booking #{booking.id} is on the way!"
        
        if (seeker.latitude is not None and seeker.longitude is not None and 
            booking.worker_latitude is not None and booking.worker_longitude is not None):
            dist = haversine(
                seeker.latitude, seeker.longitude,
                booking.worker_latitude, booking.worker_longitude
            )
            if dist < 0.5:
                msg = f"Your worker for booking #{booking.id} is arriving now (less than 500m away)!"
            elif dist < 2.0:
                msg = f"Your worker for booking #{booking.id} is very close ({round(dist, 1)}km away)!"
            else:
                msg = f"Your worker for booking #{booking.id} is {round(dist, 1)}km away."

        send_whatsapp_message(seeker.phone, msg)

    return {"ok": True}


@bookings_bp.route("/<int:booking_id>/payment-session", methods=["POST"])
@jwt_required()
@limiter.limit(lambda: current_app.config.get("PAYMENT_RATE_LIMIT", "20 per minute"))
def create_booking_payment_session(booking_id):
    user_id = int(get_jwt_identity())
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if booking.seeker_id != user_id:
        return {"error": "only the seeker can pay for this booking"}, 403
    if booking.payment_status == PaymentStatus.CAPTURED:
        return {"error": "already paid"}, 400

    amount_due = _amount_due_for_booking(booking)
    if amount_due <= 0:
        return {"error": "booking does not require payment"}, 400

    success_template = current_app.config.get("PAYMENT_SUCCESS_URL") or ""
    cancel_template = current_app.config.get("PAYMENT_CANCEL_URL") or ""
    if not success_template or not cancel_template:
        return {"error": "payment urls are not configured"}, 500

    try:
        session = create_checkout_session(
            booking,
            success_url=success_template.format(booking_id=booking.id, skill_id=booking.skill_id, provider_id=booking.provider_id),
            cancel_url=cancel_template.format(booking_id=booking.id, skill_id=booking.skill_id, provider_id=booking.provider_id),
        )
    except (PaymentConfigurationError, PaymentProviderError) as exc:
        current_app.logger.error(
            "booking.payment_session_failed",
            extra={"booking_id": booking.id, "error": str(exc)},
        )
        return {"error": str(exc)}, 400

    booking.payment_provider = session.provider
    booking.payment_checkout_session_id = session.session_id
    booking.payment_intent_id = session.payment_intent_id or booking.payment_intent_id
    db.session.commit()

    return {
        "provider": session.provider,
        "session_id": session.session_id,
        "checkout_url": session.checkout_url,
        "payment_intent_id": session.payment_intent_id,
        "amount": float(session.amount),
        "currency": session.currency,
    }, 201


@bookings_bp.route("/<int:booking_id>/pay", methods=["POST"])
@jwt_required()
@limiter.limit(lambda: current_app.config.get("PAYMENT_RATE_LIMIT", "20 per minute"))
def pay_booking(booking_id):
    user_id = int(get_jwt_identity())
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if booking.seeker_id != user_id:
        return {"error": "only the seeker can pay for this booking"}, 403
    if booking.payment_status == PaymentStatus.CAPTURED:
        return {"error": "already paid"}, 400

    if (current_app.config.get("ENV") or "development") != "development":
        return {"error": "mock payment endpoint is disabled outside development"}, 404
    if (current_app.config.get("PAYMENT_MODE") or "mock") != "mock" and not current_app.config.get("ALLOW_MOCK_PAYMENTS", False):
        return {"error": "mock payment endpoint is disabled when real payments are enabled"}, 404

    data = request.get_json() or {}
    mock_ref = data.get("payment_ref")
    try:
        capture = capture_booking_payment(booking, payment_ref=mock_ref)
    except PaymentProviderError as exc:
        return {"error": str(exc)}, 400

    booking.payment_provider = capture.provider
    booking.payment_status = PaymentStatus.CAPTURED
    booking.status = BookingStatus.CONFIRMED
    booking.payment_ref = capture.reference
    record_booking_event(
        booking,
        "payment_captured",
        actor_user_id=user_id,
        payload={"summary": "Payment captured"},
    )
    record_booking_event(
        booking,
        "confirmed",
        actor_user_id=user_id,
        payload={"status": BookingStatus.CONFIRMED.value, "summary": "Booking confirmed"},
    )
    notify_booking_status_change(
        booking=booking,
        new_status="confirmed",
        changed_by_role="seeker",
    )
    db.session.commit()
    current_app.logger.info(
        "booking.confirmed",
        extra={"booking_id": booking.id, "payment_id": capture.reference},
    )

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
        "payment_ref": capture.reference,
    }


def _process_referral_rewards(booking):
    try:
        from ..models import ReferralReward, ReferralRewardStatus, WalletTransactionType
        from ..services.wallet_service import credit as wallet_credit, emit_wallet_update

        prior_completed_count = Booking.query.filter(
            Booking.seeker_id == booking.seeker_id,
            Booking.status == BookingStatus.COMPLETED,
            Booking.id != booking.id,
        ).count()

        if prior_completed_count == 0:
            reward = ReferralReward.query.filter_by(
                referred_user_id=booking.seeker_id,
                status=ReferralRewardStatus.PENDING,
            ).first()
            if reward:
                wallet_credit(
                    user_id=reward.referrer_user_id,
                    amount=reward.reward_amount,
                    txn_type=WalletTransactionType.CREDIT_REFERRAL,
                    description=f"Referral reward for inviting user #{booking.seeker_id}",
                    reference_type="referral",
                    reference_id=reward.id,
                )
                reward.status = ReferralRewardStatus.EARNED
                reward.booking_id = booking.id
                reward.paid_at = datetime.now(timezone.utc)
                db.session.add(reward)
                emit_wallet_update(reward.referrer_user_id)
    except Exception as e:
        current_app.logger.error(
            "referrals.processing_failed",
            extra={"booking_id": booking.id, "error": str(e)},
        )


@bookings_bp.route("/<int:booking_id>/complete", methods=["POST"])
@jwt_required()
def complete_booking(booking_id):
    """
    Mark a booking as completed.
    Allow either seeker or provider to trigger completion.
    Increments provider.completed_jobs.
    """
    user_id = int(get_jwt_identity())
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if user_id not in [booking.seeker_id, booking.provider_id]:
        return {"error": "not allowed"}, 403

    booking.status = BookingStatus.COMPLETED
    provider = booking.provider
    provider.completed_jobs = (provider.completed_jobs or 0) + 1
    record_booking_event(
        booking,
        "completed",
        actor_user_id=user_id,
        payload={"status": BookingStatus.COMPLETED.value, "summary": "Service completed"},
    )
    notify_booking_status_change(
        booking=booking,
        new_status="completed",
        changed_by_role="provider" if user_id == booking.provider_id else "seeker",
    )
    _process_referral_rewards(booking)
    db.session.commit()
    try:
        if booking.invoice_url is None:
            generate_commission_invoice(str(booking.id))
    except Exception as exc:
        current_app.logger.error(
            "booking.invoice_generation_failed",
            extra={"booking_id": booking.id, "error": str(exc)},
        )
    current_app.logger.info(
        "booking.completed",
        extra={"booking_id": booking.id, "duration_minutes": booking.duration_minutes or 0},
    )

    return {"message": "booking completed"}


@bookings_bp.route("/<int:booking_id>/invoice/retry", methods=["POST"])
@jwt_required()
def retry_booking_invoice(booking_id):
    user_id = int(get_jwt_identity())
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if user_id not in [booking.seeker_id, booking.provider_id]:
        user = db.session.get(User, user_id)
        if not (user and user.is_admin):
            return {"error": "forbidden"}, 403

    if booking.status != BookingStatus.COMPLETED:
        return {"error": "invoice can only be generated for completed bookings"}, 400

    _generate_invoice_async(booking_id, max_retries=1)
    return {"message": "invoice generation triggered"}, 200


@bookings_bp.route("/<int:booking_id>/notes", methods=["PATCH"])
@jwt_required()
def save_provider_notes(booking_id):
    user_id = int(get_jwt_identity())
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if booking.provider_id != user_id:
        return {"error": "only the provider can edit notes"}, 403

    data = request.get_json() or {}
    notes = (data.get("notes") or "").strip()
    if len(notes) > 1000:
        return {"error": "notes must be 1000 characters or fewer"}, 400

    booking.provider_notes = notes or None
    db.session.commit()
    return {"success": True, "notes": booking.provider_notes or ""}, 200


@bookings_bp.route("/<int:booking_id>/review", methods=["POST"])
@jwt_required()
def review_booking(booking_id):
    """
    Seeker leaves a rating/review after booking is completed.
    Updates provider.rating and badges.
    """
    
    
    user_id = int(get_jwt_identity())
    booking = db.session.get(Booking, booking_id)
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
    reviews_table_available = inspect(db.engine).has_table("reviews")
    if reviews_table_available:
        existing_review = Review.query.filter_by(booking_id=booking.id).first()
        if existing_review:
            existing_review.rating = rating
            existing_review.comment = comment
        else:
            db.session.add(
                Review(
                    booking_id=booking.id,
                    seeker_id=booking.seeker_id,
                    provider_id=booking.provider_id,
                    rating=rating,
                    comment=comment,
                )
            )

    # Recompute provider rating from persisted reviews when available.
    if reviews_table_available:
        provider_reviews = Review.query.filter_by(provider_id=provider.id).all()
        if provider_reviews:
            provider.rating = sum(float(r.rating or 0) for r in provider_reviews) / len(provider_reviews)
        else:
            old_rating = provider.rating or 0
            n = provider.completed_jobs or 1  # avoid divide-by-zero
            provider.rating = (old_rating * (n - 1) + rating) / n
    else:
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
    record_booking_event(
        booking,
        "review_submitted",
        actor_user_id=user_id,
        payload={
            "rating": rating,
            "summary": f"Review submitted with rating {rating:.1f}",
        },
    )

    db.session.commit()
    return {
        "message": "review saved",
        "provider_rating": provider.rating,
        "badges": provider.badges,
        "comment": comment,
    }


@bookings_bp.route("/reviews/<int:review_id>/reply", methods=["POST"])
@jwt_required()
def reply_to_review(review_id):
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user or user.role != RoleEnum.PROVIDER:
        return {"error": "only providers can reply"}, 403

    review = db.session.get(Review, review_id)
    if not review:
        return {"error": "review not found"}, 404
    if review.provider_id != user_id:
        return {"error": "forbidden"}, 403
    if review.provider_reply:
        return {"error": "reply already submitted"}, 409

    data = request.get_json() or {}
    reply = (data.get("reply") or "").strip()
    if not reply:
        return {"error": "reply is required"}, 400
    if len(reply) > 280:
        return {"error": "reply must be 280 characters or fewer"}, 400

    review.provider_reply = reply
    review.provider_replied_at = datetime.now(timezone.utc)
    db.session.commit()
    return {
        "success": True,
        "review_id": review.id,
        "provider_reply": review.provider_reply,
        "provider_replied_at": review.provider_replied_at.isoformat(),
    }, 201

@bookings_bp.route("/my", methods=["GET"])
@jwt_required()
def my_bookings():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)

    if not user or user.role != RoleEnum.SEEKER:
        return {"error": "only seekers allowed"}, 403

    status_filter = (request.args.get("status") or "").strip().lower()
    limit = min(max(request.args.get("limit", default=200, type=int), 1), 500)
    offset = max(request.args.get("offset", default=0, type=int), 0)
    query = (
        Booking.query
        .options(joinedload(Booking.skill), joinedload(Booking.provider))
        .filter_by(seeker_id=user.id)
    )
    if status_filter == "active":
        query = query.filter(Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.IN_PROGRESS]))
    elif status_filter == "completed":
        query = query.filter(Booking.status == BookingStatus.COMPLETED)
    elif status_filter == "cancelled":
        query = query.filter(Booking.status == BookingStatus.CANCELLED)
    elif status_filter == "needs_review":
        # needs_review = status=COMPLETED AND no review row exists
        query = query.filter(Booking.status == BookingStatus.COMPLETED)
        query = query.outerjoin(Review, Review.booking_id == Booking.id).filter(Review.id == None)

    bookings = (
        query
        .order_by(Booking.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    review_by_booking = {}
    if bookings and inspect(db.engine).has_table("reviews"):
        try:
            ids = [b.id for b in bookings]
            for rev in Review.query.filter(Review.booking_id.in_(ids)).all():
                review_by_booking[rev.booking_id] = rev
        except Exception:
            review_by_booking = {}
    timeline_preview_by_booking = _latest_timeline_preview_map(bookings)

    def row(b):
        rev = review_by_booking.get(b.id)
        needs_review = b.status == BookingStatus.COMPLETED and rev is None
        out = {
            "id": b.id,
            "status": b.status.value,
            "scheduled_at": b.scheduled_at.isoformat() if b.scheduled_at else None,
            "price": float(b.price or 0),
            "skill_id": b.skill_id,
            "skill": b.skill.title if b.skill else "Service unavailable",
            "provider_id": b.provider_id,
            "provider": b.provider.name if b.provider else "Provider unavailable",
            "review_rating": float(rev.rating) if rev else None,
            "review_comment": rev.comment if rev else None,
            "review_id": rev.id if rev else None,
            "review_provider_reply": rev.provider_reply if rev else None,
            "review_provider_replied_at": rev.provider_replied_at.isoformat() if rev and rev.provider_replied_at else None,
            "invoice": _invoice_payload_for_booking(b),
            "cancellation_reason": getattr(b, "cancellation_reason", None),
            "needs_review": needs_review,
            "timeline_preview": timeline_preview_by_booking.get(b.id),
        }
        return out

    rows = [row(b) for b in bookings]
    return rows, 200

@bookings_bp.route("/provider", methods=["GET"])
@jwt_required()
def provider_bookings():
    from sqlalchemy.orm import joinedload
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)

    if not user or user.role != RoleEnum.PROVIDER:
        return {"error": "only providers allowed"}, 403

    bookings = (
        Booking.query
        .options(joinedload(Booking.skill), joinedload(Booking.seeker))
        .filter_by(provider_id=user.id)
        .order_by(Booking.created_at.desc())
        .all()
    )

    return [{
        "id": b.id,
        "skill": b.skill.title,
        "seeker": b.seeker.name,
        "status": b.status.value,
        "scheduled_at": b.scheduled_at.isoformat(),
    } for b in bookings], 200

@bookings_bp.route("/<int:booking_id>/decision", methods=["POST"])
@jwt_required()
def decide_booking(booking_id):
    user = db.session.get(User, int(get_jwt_identity()))
    data = request.get_json() or {}
    action = data.get("action")  # accept | reject

    booking = Booking.query.get_or_404(booking_id)

    if user.role != RoleEnum.PROVIDER or booking.provider_id != user.id:
        return {"error": "unauthorized"}, 403

    if booking.status != BookingStatus.PENDING:
        return {"error": "already processed"}, 400

    if action == "accept":
        booking.status = BookingStatus.CONFIRMED
        record_booking_event(
            booking,
            "confirmed",
            actor_user_id=user.id,
            payload={"status": BookingStatus.CONFIRMED.value, "summary": "Provider accepted the booking"},
        )
        notify_booking_status_change(
            booking=booking,
            new_status="confirmed",
            changed_by_role="provider",
        )
        current_app.logger.info(
            "booking.provider_accepted",
            extra={"booking_id": booking.id, "provider_id": user.id},
        )
    elif action == "reject":
        booking.status = BookingStatus.DECLINED
        record_booking_event(
            booking,
            "declined",
            actor_user_id=user.id,
            payload={"status": BookingStatus.DECLINED.value, "summary": "Provider declined the booking"},
        )
        notify_booking_status_change(
            booking=booking,
            new_status="declined",
            changed_by_role="provider",
        )
        current_app.logger.info(
            "booking.provider_declined",
            extra={"booking_id": booking.id, "reason": "provider_rejected"},
        )
    else:
        return {"error": "invalid action"}, 400

    db.session.commit()
    return {"success": True, "status": booking.status.value}


@bookings_bp.route("/<int:booking_id>/invoice/generate", methods=["POST"])
@jwt_required()
def generate_booking_invoice_endpoint(booking_id):
    user_id = int(get_jwt_identity())
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if user_id not in [booking.seeker_id, booking.provider_id]:
        return {"error": "forbidden"}, 403

    _generate_invoice_async(booking.id)
    return {"invoice": {"status": "generating"}}, 202


@bookings_bp.route("/<int:booking_id>/timeline", methods=["GET"])
@jwt_required()
def booking_timeline(booking_id):
    user_id = int(get_jwt_identity())
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return {"error": "booking not found"}, 404
    if user_id not in [booking.seeker_id, booking.provider_id]:
        return {"error": "forbidden"}, 403

    events = (
        BookingTimelineEvent.query
        .filter_by(booking_id=booking.id)
        .order_by(BookingTimelineEvent.created_at.asc(), BookingTimelineEvent.id.asc())
        .all()
    )
    return {
        "booking_id": booking.id,
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "summary": _timeline_event_summary(event.event_type, event.payload),
                "actor_user_id": event.actor_user_id,
                "payload": event.payload or {},
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
    }, 200


# ==============================
# 💵 CASH PAYMENT
# ==============================

@bookings_bp.route("/<int:booking_id>/cash-payment", methods=["POST"])
@jwt_required()
def cash_payment(booking_id):
    """
    Worker confirms cash collected from seeker after job completion.
    Commission (10%) is deducted from worker's wallet or tracked as payable.
    """
    user_id = int(get_jwt_identity())
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return {"error": "booking not found"}, 404

    # Only the provider (worker) can confirm cash collection
    if booking.provider_id != user_id:
        return {"error": "only the assigned worker can confirm cash payment"}, 403

    # Must be IN_PROGRESS or COMPLETED
    if booking.status not in {BookingStatus.IN_PROGRESS, BookingStatus.COMPLETED}:
        return {"error": "booking must be in progress or completed for cash payment"}, 400

    # Prevent double payment
    if booking.payment_status in {PaymentStatus.CAPTURED, PaymentStatus.CASH_COLLECTED}:
        return {"error": "payment already recorded"}, 400

    data = request.get_json() or {}
    amount_collected = data.get("amount_collected")
    if amount_collected is not None:
        try:
            amount_collected = Decimal(str(amount_collected))
        except Exception:
            return {"error": "invalid amount"}, 400

    # Mark payment as cash collected
    booking.payment_status = PaymentStatus.CASH_COLLECTED
    booking.payment_method = "cash"
    booking.cash_collected_at = datetime.now(timezone.utc)
    booking.cash_collected_by = user_id
    booking.payment_ref = f"CASH-{booking.id}-{int(datetime.now(timezone.utc).timestamp())}"

    # If booking wasn't already completed, complete it now
    if booking.status != BookingStatus.COMPLETED:
        booking.status = BookingStatus.COMPLETED
        provider = booking.provider
        provider.completed_jobs = (provider.completed_jobs or 0) + 1
        record_booking_event(
            booking,
            "completed",
            actor_user_id=user_id,
            payload={"status": BookingStatus.COMPLETED.value, "summary": "Service completed"},
        )
        _process_referral_rewards(booking)

    record_booking_event(
        booking,
        "payment_captured",
        actor_user_id=user_id,
        payload={
            "summary": f"Cash payment of ₹{float(booking.price or 0):.0f} collected",
            "method": "cash",
            "amount_collected": float(amount_collected) if amount_collected else float(booking.price or 0),
        },
    )

    # Track commission owed: worker keeps ₹900 from ₹1000, owes Skillo ₹100
    commission = Decimal(booking.platform_fee_amount or 0)

    from ..services.wallet_service import debit, emit_wallet_update, InsufficientBalanceError
    from ..models import WalletTransactionType
    commission_deducted = False
    if commission > 0:
        try:
            debit(
                user_id=booking.provider_id,
                amount=commission,
                txn_type=WalletTransactionType.DEBIT_COMMISSION,
                description=f"Commission for cash booking #{booking.id} (₹{float(commission):.0f})",
                reference_type="booking",
                reference_id=booking.id,
                allow_negative=False,
            )
            commission_deducted = True
        except InsufficientBalanceError:
            return {
                "error": "insufficient_wallet_balance",
                "message": "Please top up your wallet with the platform commission amount before confirming cash collection.",
                "commission_due": float(commission),
            }, 409

    AuditLog.record(
        "booking.cash_payment",
        actor_id=user_id,
        actor_role="provider",
        target_type="booking",
        target_id=booking.id,
        metadata={
            "booking_id": booking.id,
            "amount": float(booking.price or 0),
            "commission": float(commission),
            "commission_deducted": commission_deducted,
        },
        request=request,
    )

    notify_booking_status_change(
        booking=booking,
        new_status="completed",
        changed_by_role="provider",
    )
    db.session.commit()
    emit_wallet_update(booking.provider_id)

    # Generate invoice
    try:
        if booking.invoice_url is None:
            generate_commission_invoice(str(booking.id))
    except Exception as exc:
        current_app.logger.error(
            "booking.cash_invoice_failed",
            extra={"booking_id": booking.id, "error": str(exc)},
        )

    return {
        "message": "Cash payment recorded",
        "booking_id": booking.id,
        "payment_ref": booking.payment_ref,
        "amount": float(booking.price or 0),
        "commission": float(commission),
        "worker_earnings": float(booking.worker_earnings or 0),
    }, 200


# ==============================
# 💸 REFUND
# ==============================

@bookings_bp.route("/<int:booking_id>/refund", methods=["POST"])
@jwt_required()
def refund_booking(booking_id):
    """
    Initiate a refund for a booking. Admin or system use.
    For online payments, calls the payment gateway.
    For wallet/promo payments, credits back to wallet.
    """
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return {"error": "booking not found"}, 404

    # Only admin or the seeker can request refund
    is_admin = user and user.is_admin
    if not is_admin and user_id != booking.seeker_id:
        return {"error": "forbidden"}, 403

    if booking.payment_status not in {PaymentStatus.CAPTURED}:
        return {"error": "booking payment must be captured to refund"}, 400

    if booking.refund_status in {RefundStatus.PROCESSED, RefundStatus.PENDING}:
        return {"error": "refund already in progress or completed"}, 400

    data = request.get_json() or {}
    reason = (data.get("reason") or "").strip() or "Requested by user"
    refund_amount_input = data.get("amount")

    total_paid = Decimal(getattr(booking, "amount_payable", None) or booking.price or 0)
    if refund_amount_input:
        try:
            refund_amount = min(Decimal(str(refund_amount_input)), total_paid)
        except Exception:
            return {"error": "invalid amount"}, 400
    else:
        refund_amount = total_paid

    if refund_amount <= 0:
        return {"error": "refund amount must be positive"}, 400

    booking.refund_status = RefundStatus.PENDING
    booking.refund_amount = refund_amount
    booking.refund_reason = reason
    booking.refund_initiated_at = datetime.now(timezone.utc)

    # Credit back to wallet
    from ..services.wallet_service import credit as wallet_credit, emit_wallet_update
    from ..models import WalletTransactionType
    wallet_credit(
        user_id=booking.seeker_id,
        amount=refund_amount,
        txn_type=WalletTransactionType.CREDIT_REFUND,
        description=f"Refund for booking #{booking.id}: {reason}",
        reference_type="booking",
        reference_id=booking.id,
    )

    booking.refund_status = RefundStatus.PROCESSED
    booking.refund_completed_at = datetime.now(timezone.utc)
    booking.payment_status = PaymentStatus.REFUNDED
    booking.refund_ref = f"REFUND-{booking.id}-{int(datetime.now(timezone.utc).timestamp())}"

    record_booking_event(
        booking,
        "refunded",
        actor_user_id=user_id,
        payload={
            "summary": f"Refund of ₹{float(refund_amount):.0f} processed",
            "amount": float(refund_amount),
            "reason": reason,
        },
    )

    db.session.commit()
    emit_wallet_update(booking.seeker_id)

    return {
        "message": "Refund processed",
        "refund_amount": float(refund_amount),
        "refund_ref": booking.refund_ref,
        "wallet_credited": True,
    }, 200


# ==============================
# 📊 PAYMENT HISTORY
# ==============================

@bookings_bp.route("/payment-history", methods=["GET"])
@jwt_required()
def payment_history():
    """Get booking and wallet payment history for the current user."""
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return {"error": "user not found"}, 404

    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 50)

    booking_query = Booking.query.filter(
        db.or_(Booking.seeker_id == user_id, Booking.provider_id == user_id),
        Booking.payment_status != PaymentStatus.NONE,
        Booking.is_deleted == False,
    )
    wallet_query = WalletTransaction.query.filter_by(user_id=user_id)

    booking_items = []
    for b in booking_query.all():
        role = "seeker" if b.seeker_id == user_id else "provider"
        service_title = b.skill.title if b.skill else f"Booking #{b.id}"
        booking_items.append({
            "kind": "booking",
            "id": f"booking-{b.id}",
            "booking_id": b.id,
            "role": role,
            "service": service_title,
            "skill_title": service_title,
            "status": b.status.value,
            "payment_status": b.payment_status.value,
            "payment_method": getattr(b, "payment_method", "online") or "online",
            "amount": float(b.price or 0),
            "amount_payable": float(getattr(b, "amount_payable", None) or b.price or 0),
            "platform_fee": float(b.platform_fee_amount or 0),
            "worker_earnings": float(b.worker_earnings or 0),
            "refund_status": b.refund_status.value if b.refund_status else None,
            "refund_amount": float(b.refund_amount or 0),
            "invoice_url": b.invoice_url,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        })

    wallet_items = []
    for txn in wallet_query.all():
        wallet_items.append({
            "kind": "wallet",
            "id": f"wallet-{txn.id}",
            "booking_id": None,
            "role": "self",
            "service": txn.description,
            "skill_title": txn.description,
            "status": txn.txn_type.value,
            "payment_status": txn.txn_type.value,
            "payment_method": "wallet",
            "amount": float(abs(txn.amount or 0)),
            "amount_payable": float(abs(txn.amount or 0)),
            "platform_fee": 0.0,
            "worker_earnings": 0.0,
            "refund_status": None,
            "refund_amount": 0.0,
            "invoice_url": None,
            "created_at": txn.created_at.isoformat() if txn.created_at else None,
            "reference_type": txn.reference_type,
            "reference_id": txn.reference_id,
        })

    all_items = booking_items + wallet_items
    all_items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    total = len(all_items)
    start = max((page - 1) * per_page, 0)
    end = start + per_page
    items = all_items[start:end]

    return {
        "items": items,
        "total": total,
        "page": page,
        "current_page": page,
        "per_page": per_page,
        "total_pages": max((total + per_page - 1) // per_page, 1),
        "has_more": (page * per_page) < total,
    }, 200
