from flask import Blueprint
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import User, Booking, BookingStatus, RoleEnum, VerificationStatus
from ..extensions import db

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
    # 🔐 FINAL VERIFICATION CHECK (CRITICAL FIX)
    # --------------------
    if not provider.is_verified and provider.verification_status != VerificationStatus.completed:
        return {"error": "provider not verified"}, 403

    # --------------------
    # FETCH BOOKINGS
    # --------------------
    bookings = Booking.query.filter_by(provider_id=provider.id).all()

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

    pending = [serialize(b) for b in bookings if b.status == BookingStatus.PENDING]
    active = [serialize(b) for b in bookings if b.status == BookingStatus.CONFIRMED]
    completed = [serialize(b) for b in bookings if b.status == BookingStatus.COMPLETED]

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
        },
        "bookings": {
            "pending": pending,
            "active": active,
            "completed": completed,
        }
    }, 200
