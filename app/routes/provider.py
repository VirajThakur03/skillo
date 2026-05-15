from flask import Blueprint,jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import User, Booking, BookingStatus, RoleEnum, VerificationStatus, Skill, KycStatus, Review
from ..extensions import db
from decimal import Decimal, InvalidOperation
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from ..services.marketplace import compute_provider_badges
from ..models import BookingTimelineEvent

provider_bp = Blueprint("provider", __name__, url_prefix="/api/provider")


def _latest_timeline_preview(bookings):
    if not bookings:
        return {}
    booking_ids = [booking.id for booking in bookings]
    preview_by_booking = {}
    events = (
        BookingTimelineEvent.query
        .filter(BookingTimelineEvent.booking_id.in_(booking_ids))
        .order_by(BookingTimelineEvent.created_at.desc(), BookingTimelineEvent.id.desc())
        .all()
    )
    for event in events:
        if event.booking_id in preview_by_booking:
            continue
        preview_by_booking[event.booking_id] = {
            "event_type": event.event_type,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "summary": (event.payload or {}).get("summary") or event.event_type.replace("_", " ").title(),
        }
    return preview_by_booking


def _recommended_actions(provider, bookings, review_by_booking, kyc_blocked):
    actions = []
    pending_count = sum(1 for booking in bookings if booking.status == BookingStatus.PENDING)
    outstanding_review_replies = sum(
        1
        for booking in bookings
        if review_by_booking.get(booking.id) and not review_by_booking[booking.id].provider_reply
    )

    if kyc_blocked:
        actions.append({
            "id": "kyc",
            "title": "Finish KYC to become bookable",
            "description": "Open the KYC center to see missing documents, review status, and next steps.",
            "href": "/provider/kyc-status",
            "label": "Open KYC center",
            "priority": 100,
        })
    if pending_count > 0:
        actions.append({
            "id": "pending_bookings",
            "title": f"{pending_count} pending job request{'s' if pending_count != 1 else ''}",
            "description": "Respond quickly to improve acceptance rate and conversion.",
            "href": "#pendingJobs",
            "label": "Review pending jobs",
            "priority": 90,
        })
    if outstanding_review_replies > 0:
        actions.append({
            "id": "review_replies",
            "title": f"{outstanding_review_replies} review repl{'ies' if outstanding_review_replies != 1 else 'y'} waiting",
            "description": "A short public reply helps trust and repeat bookings.",
            "href": "#completedJobs",
            "label": "Reply to reviews",
            "priority": 70,
        })
    if provider.is_accepting_bookings is False and not kyc_blocked:
        actions.append({
            "id": "resume_availability",
            "title": "You are currently offline",
            "description": "Turn availability back on to receive new requests in search and direct booking.",
            "href": "#availabilityToggle",
            "label": "Resume bookings",
            "priority": 60,
        })
    
    # Stripe Onboarding Action
    if not getattr(provider, "stripe_onboarding_complete", False):
        actions.append({
            "id": "stripe_onboarding",
            "title": "Connect Stripe for payouts",
            "description": "Set up your payout account to receive earnings from completed jobs.",
            "href": "#onboardStripe",
            "label": "Connect account",
            "priority": 85,
        })
    if not actions:
        actions.append({
            "id": "growth",
            "title": "Keep your profile sharp",
            "description": "Update pricing, availability, and portfolio regularly to win more bookings.",
            "href": "/provider/profile",
            "label": "Edit provider profile",
            "priority": 10,
        })

    return sorted(actions, key=lambda item: item["priority"], reverse=True)


@provider_bp.route("/dashboard", methods=["GET"])
@jwt_required()
def provider_dashboard():
    user_id = int(get_jwt_identity())
    provider = db.session.get(User, user_id)

    # --------------------
    # BASIC AUTH
    # --------------------
    if not provider:
        return {"error": "unauthenticated"}, 401

    if provider.role != RoleEnum.PROVIDER:
        return {"error": "forbidden"}, 403

    # --------------------
    # 🔐 VERIFICATION & KYC CHECKS (RELAXED FOR DASHBOARD ACCESS)
    # Only 'suspended' blocks the dashboard entirely.
    # Pending/Rejected verification/KYC states show a notice instead of a 403.
    # --------------------
    if provider.kyc_status == KycStatus.suspended:
        return {
            "error": "provider kyc suspended",
            "status": provider.kyc_status.value,
            "reason": provider.kyc_rejection_reason or "Your account is suspended from accepting new bookings. Contact support for help.",
        }, 403

    # Define if the provider is blocked from being bookable in search
    kyc_blocked = (
        provider.kyc_status != KycStatus.approved or 
        provider.verification_status not in (VerificationStatus.face_verified, VerificationStatus.completed)
    )

    # Determine a descriptive kyc_notice
    kyc_notice = None
    if kyc_blocked:
        if provider.verification_status == VerificationStatus.rejected:
            kyc_notice = "Your identity verification was rejected. Please re-upload your documents."
        elif provider.kyc_status == KycStatus.rejected:
            kyc_notice = provider.kyc_rejection_reason or "Your KYC was rejected. Please review the missing steps."
        elif provider.kyc_status == KycStatus.under_review:
            kyc_notice = "Your KYC is currently under review by our team. This usually takes 24-48 hours."
        elif provider.verification_status == VerificationStatus.pending:
            kyc_notice = "Please complete your identity verification to become bookable."
        else:
            kyc_notice = "Your KYC approval is pending. You can manage your profile, but you are not yet live in search."

    # --------------------
    # FETCH BOOKINGS (CRITICAL FIX)
    # --------------------
    limit = min(max(request.args.get("limit", default=200, type=int), 1), 500)
    bookings = (
        Booking.query
        .options(joinedload(Booking.skill), joinedload(Booking.seeker))
        .filter(Booking.provider_id == provider.id)
        .order_by(Booking.created_at.desc())
        .limit(limit)
        .all()
    )

    try:
        review_by_booking = {
            item.booking_id: item
            for item in Review.query.filter(Review.provider_id == provider.id).all()
        }
    except Exception:
        review_by_booking = {}
    timeline_preview_by_booking = _latest_timeline_preview(bookings)

    def serialize(b):
        booking_review = review_by_booking.get(b.id)
        return {
            "id": b.id,
            "skill": b.skill.title if b.skill else "Service unavailable",
            "seeker": b.seeker.name if b.seeker else "Seeker unavailable",
            "status": b.status.value,
            "price": float(b.price or 0),
            "scheduled_at": (
                b.scheduled_at.isoformat() if b.scheduled_at else None
            ),
            "provider_notes": b.provider_notes or "",
            "review_id": booking_review.id if booking_review else None,
            "review_rating": float(booking_review.rating) if booking_review else None,
            "review_comment": booking_review.comment if booking_review else None,
            "review_provider_reply": booking_review.provider_reply if booking_review else None,
            "review_provider_replied_at": booking_review.provider_replied_at.isoformat() if booking_review and booking_review.provider_replied_at else None,
            "cancellation_reason": b.cancellation_reason,
            "timeline_preview": timeline_preview_by_booking.get(b.id),
        }

    pending = [
        serialize(b)
        for b in bookings
        if b.status == BookingStatus.PENDING
    ]

    active = [
        serialize(b)
        for b in bookings
        if b.status in (
            BookingStatus.CONFIRMED,
            BookingStatus.IN_PROGRESS,
        )
    ]

    completed = [
        serialize(b)
        for b in bookings
        if b.status == BookingStatus.COMPLETED
    ]

    cancelled = [
        serialize(b)
        for b in bookings
        if b.status == BookingStatus.CANCELLED
    ]

    # --------------------
    # RESPONSE
    # --------------------
    return {
        "provider": {
            "id": provider.id,
            "name": provider.name,
            "rating": provider.rating or 0,
            "completed_jobs": len(completed),
            "wallet_balance": float(provider.wallet_balance or 0),
            "badges": compute_provider_badges(provider),
            "is_verified": provider.is_verified,
            "verification_status": provider.verification_status.value,
            "kyc_status": provider.kyc_status.value,
            "kyc_rejection_reason": provider.kyc_rejection_reason,
            "kyc_blocked": kyc_blocked,
            "kyc_notice": kyc_notice,
            "is_accepting_bookings": getattr(provider, "is_accepting_bookings", True),
        },
        "recommended_actions": _recommended_actions(provider, bookings, review_by_booking, kyc_blocked),
        "bookings": {
            "pending": pending,
            "active": active,
            "completed": completed,
            "cancelled": cancelled,
        }
    }, 200


@provider_bp.route("/availability", methods=["POST"])
@jwt_required()
def toggle_availability():
    user_id = int(get_jwt_identity())
    provider = db.session.get(User, user_id)
    if not provider or provider.role != RoleEnum.PROVIDER:
        return {"error": "forbidden"}, 403

    data = request.get_json() or {}
    is_accepting = data.get("is_accepting_bookings")
    if is_accepting is not None:
        provider.is_accepting_bookings = bool(is_accepting)
        db.session.commit()

    return {"is_accepting_bookings": provider.is_accepting_bookings}, 200


@provider_bp.route("/profile", methods=["POST"])
@jwt_required()
def save_provider_profile():
    try:
        user = db.session.get(User, int(get_jwt_identity()))

        if not user:
            return jsonify({"error": "user not found"}), 404

        if user.role != RoleEnum.PROVIDER:
            return jsonify({"error": "only providers allowed"}), 403

        data = request.get_json(silent=True) or {}

        # --------------------
        # VALIDATION (SAFE)
        # --------------------
        name       = (data.get("name") or "").strip()
        phone      = (data.get("phone") or "").strip()
        location   = (data.get("location") or "").strip()
        skill_name = (data.get("skill") or "").strip()
        price_raw  = data.get("price")

        if not name or not phone or not location or not skill_name:
            return jsonify({
                "error": "name, phone, location and skill are required"
            }), 400

        # ---- PRICE FIX (ROOT CAUSE SOLVED) ----
        try:
            price = Decimal(str(price_raw).strip())
            if price <= 0:
                raise ValueError
        except (InvalidOperation, ValueError, TypeError):
            return jsonify({"error": "invalid price"}), 400

        # --------------------
        # UNIQUE PHONE CHECK
        # --------------------
        if phone:
            existing_phone = User.query.filter(
                User.phone == phone,
                User.id != user.id,
            ).first()
            if existing_phone:
                return jsonify({"error": "phone already in use"}), 409

        # --------------------
        # UPDATE USER PROFILE
        # --------------------
        user.name = name
        user.phone = phone
        user.location = location
        user.bio = (data.get("bio") or user.bio)

        # --------------------
        # CREATE / UPDATE SKILL
        # --------------------
        existing_skill = Skill.query.filter_by(
            provider_id=user.id,
            title=skill_name
        ).first()

        if existing_skill:
            # update instead of duplicate
            existing_skill.price = price
            existing_skill.location = location
            existing_skill.is_active = True
            skill = existing_skill
        else:
            skill = Skill(
                provider_id=user.id,
                title=skill_name,
                description=data.get("description"),
                price=price,
                currency=data.get("currency") or "INR",
                location=location,
                is_active=True
            )
            db.session.add(skill)

        # 🔥 IMPORTANT FLAG (STOPS REDIRECT LOOP)
        user.is_provider_profile_complete = True

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({
                "error": "phone or email already in use"
            }), 409

        return jsonify({
            "success": True,
            "message": "Provider profile saved successfully",
            "skill_id": skill.id
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({
            "error": "failed to save provider profile",
            "details": str(e)
        }), 500

@provider_bp.route("/earnings", methods=["GET"])
@jwt_required()
def provider_earnings():
    user_id = int(get_jwt_identity())
    provider = db.session.get(User, user_id)

    if not provider or provider.role != RoleEnum.PROVIDER:
        return {"error": "forbidden"}, 403

    # Calculate total earnings from completed bookings
    total_earnings = db.session.query(func.sum(Booking.price)).filter(
        Booking.provider_id == user_id, 
        Booking.status == BookingStatus.COMPLETED
    ).scalar() or 0
    
    # Calculate pending earnings from active (confirmed, in_progress, en_route) bookings
    pending_earnings = db.session.query(func.sum(Booking.price)).filter(
        Booking.provider_id == user_id, 
        Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.IN_PROGRESS])
    ).scalar() or 0
    
    return {"total": float(total_earnings), "pending": float(pending_earnings)}, 200
