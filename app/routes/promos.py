from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from ..models import User
from ..services.promo_service import evaluate_promo

promos_bp = Blueprint("promos", __name__, url_prefix="/api/promos")


@promos_bp.route("/validate", methods=["POST"])
@jwt_required(optional=True)
def validate_promo_code():
    data = request.get_json() or {}
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id)) if user_id is not None else None

    is_valid, payload = evaluate_promo(
        data.get("code"),
        data.get("booking_amount"),
        user=user,
    )
    return payload, 200 if is_valid else 409
