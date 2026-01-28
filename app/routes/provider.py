from flask import Blueprint,jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import User, Booking, BookingStatus, RoleEnum, VerificationStatus, Skill
from ..extensions import db
from decimal import Decimal, InvalidOperation

provider_bp = Blueprint("provider", __name__, url_prefix="/api/provider")


@provider_bp.route("/dashboard", methods=["GET"])
@jwt_required()
def provider_dashboard():
    user_id = int(get_jwt_identity())
    provider = User.query.get(user_id)

    # --------------------
    # BASIC AUTH
    # --------------------
    if not provider:
        return {"error": "unauthenticated"}, 401

    if provider.role != RoleEnum.PROVIDER:
        return {"error": "forbidden"}, 403

    # --------------------
    # 🔐 VERIFICATION CHECK (FIXED)
    # Allow after face_verified or completed
    # --------------------
    if provider.verification_status not in (
        VerificationStatus.face_verified,
        VerificationStatus.completed,
    ):
        return {
            "error": "provider verification incomplete",
            "status": provider.verification_status.value
        }, 403

    # --------------------
    # FETCH BOOKINGS (CRITICAL FIX)
    # --------------------
    bookings = (
        Booking.query
        .filter(Booking.provider_id == provider.id)
        .order_by(Booking.created_at.desc())
        .all()
    )

    def serialize(b):
        return {
            "id": b.id,
            "skill": b.skill.title if b.skill else "",
            "seeker": b.seeker.name if b.seeker else "",
            "status": b.status.value,
            "price": float(b.price or 0),
            "scheduled_at": (
                b.scheduled_at.isoformat() if b.scheduled_at else None
            ),
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
            "badges": provider.badges or [],
            "is_verified": provider.is_verified,
            "verification_status": provider.verification_status.value,
        },
        "bookings": {
            "pending": pending,
            "active": active,
            "completed": completed,
        }
    }, 200


@provider_bp.route("/profile", methods=["POST"])
@jwt_required()
def save_provider_profile():
    try:
        user = User.query.get(int(get_jwt_identity()))

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

        db.session.commit()

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
