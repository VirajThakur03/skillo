from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import User, Booking, BookingStatus
from ..extensions import db

provider_bp = Blueprint("provider", __name__, url_prefix="/api/provider")


@provider_bp.route("/dashboard")
@jwt_required()
def provider_dashboard():
    user_id = get_jwt_identity()
    provider = User.query.get(user_id)

    if not provider or provider.role.value != "provider":
        return {"error": "forbidden"}, 403

    bookings = Booking.query.filter_by(provider_id=user_id).all()

    def serialize(b):
        return {
            "id": b.id,
            "skill": b.skill.title,
            "seeker": b.seeker.name,
            "status": b.status.value,
            "price": float(b.price),
            "scheduled_at": b.scheduled_at.isoformat(),
        }

    return {
        "provider": {
            "name": provider.name,
            "rating": provider.rating,
            "completed_jobs": provider.completed_jobs,
            "wallet_balance": float(provider.wallet_balance or 0),
            "badges": provider.badges or [],
            "is_verified": provider.is_verified,
        },
        "bookings": {
            "pending": [serialize(b) for b in bookings if b.status == BookingStatus.PENDING],
            "active":  [serialize(b) for b in bookings if b.status == BookingStatus.CONFIRMED],
            "completed": [serialize(b) for b in bookings if b.status == BookingStatus.COMPLETED],
        }
    }
