from decimal import Decimal

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from ..extensions import db
from ..models import Booking, ReferralReward, ReferralRewardStatus, RoleEnum, User

referrals_bp = Blueprint("referrals", __name__, url_prefix="/api/referrals")
wallet_bp = Blueprint("wallet_api", __name__, url_prefix="/api/wallet")


def _current_user():
    identity = get_jwt_identity()
    if identity is None:
        return None
    return db.session.get(User, int(identity))


def _mask_friend(user):
    if user is None:
        return "Friend"
    if user.phone:
        digits = "".join(ch for ch in user.phone if ch.isdigit())
        if len(digits) >= 5:
            return f"+91 XXXXX {digits[-5:]}"
    if user.name:
        parts = user.name.split()
        if len(parts) >= 2:
            return f"{parts[0]} {parts[-1][0]}."
        return user.name[:1] + "***"
    if user.email:
        local = user.email.split("@", 1)[0]
        return f"{local[:2]}***"
    return "Friend"


@referrals_bp.route("", methods=["GET"])
@jwt_required()
def get_referrals():
    user = _current_user()
    if not user:
        return {"error": "user not found"}, 404

    rewards = ReferralReward.query.filter_by(referrer_user_id=user.id).order_by(ReferralReward.created_at.desc()).all()
    pending = [reward for reward in rewards if reward.status == ReferralRewardStatus.PENDING]
    rewarded = [reward for reward in rewards if reward.status in {ReferralRewardStatus.EARNED, ReferralRewardStatus.PAID}]
    wallet_credit_earned = sum(Decimal(reward.reward_amount or 0) for reward in rewarded)

    return {
        "code": user.referral_code,
        "total_referred": len(user.referrals),
        "pending": float(sum(Decimal(reward.reward_amount or 0) for reward in pending)),
        "rewarded": float(wallet_credit_earned),
        "wallet_credit_earned": float(wallet_credit_earned),
        "items": [
            {
                "id": reward.id,
                "friend_label": _mask_friend(reward.referred_user),
                "joined_date": reward.referred_user.created_at.isoformat() if reward.referred_user and reward.referred_user.created_at else None,
                "booking_status": reward.booking.status.value if reward.booking else "Pending first booking",
                "reward_status": reward.status.value,
                "reward_amount": float(reward.reward_amount or 0),
                "booking_id": reward.booking_id,
                "created_at": reward.created_at.isoformat() if reward.created_at else None,
                "note": reward.note,
            }
            for reward in rewards
        ],
    }, 200


@referrals_bp.route("/apply", methods=["POST"])
@jwt_required()
def apply_referral_code():
    user = _current_user()
    if not user:
        return {"error": "user not found"}, 404

    data = request.get_json() or {}
    code = (data.get("code") or "").strip().upper()
    if not code:
        return {"error": "code is required"}, 400
    if user.referral_code and user.referral_code.upper() == code:
        return {"error": "you cannot use your own referral code"}, 400
    if user.referred_by_id is not None:
        return {"error": "referral already applied"}, 400
    if Booking.query.filter_by(seeker_id=user.id).count() > 0:
        return {"error": "referral codes can only be applied before your first booking"}, 400

    referrer = User.query.filter(User.referral_code.ilike(code)).first()
    if not referrer:
        return {"error": "referral code not found"}, 404
    if referrer.id == user.id:
        return {"error": "you cannot use your own referral code"}, 400

    user.referred_by_id = referrer.id
    reward = ReferralReward(
        referrer_user_id=referrer.id,
        referred_user_id=user.id,
        status=ReferralRewardStatus.PENDING,
        reward_amount=Decimal("100.00"),
        note="Reward credited after friend's first completed booking.",
    )
    db.session.add(reward)
    db.session.commit()
    return {"success": True, "code": referrer.referral_code}, 200


@wallet_bp.route("", methods=["GET"])
@jwt_required()
def get_wallet():
    user = _current_user()
    if not user:
        return {"error": "user not found"}, 404

    reward_entries = ReferralReward.query.filter_by(referrer_user_id=user.id).order_by(ReferralReward.created_at.desc()).all()
    booking_entries = (
        Booking.query.filter_by(seeker_id=user.id)
        .filter(Booking.referral_credit_used > 0)
        .order_by(Booking.created_at.desc())
        .all()
    )

    transactions = [
        {
            "type": "referral_reward",
            "title": f"Referral reward - {reward.status.value.title()}",
            "amount": float(reward.reward_amount or 0),
            "status": reward.status.value,
            "created_at": reward.created_at.isoformat() if reward.created_at else None,
            "reference": f"RR-{reward.id}",
        }
        for reward in reward_entries
    ]
    transactions.extend(
        {
            "type": "wallet_spend",
            "title": f"Wallet used on booking #{booking.id}",
            "amount": -float(booking.referral_credit_used or 0),
            "status": booking.status.value,
            "created_at": booking.created_at.isoformat() if booking.created_at else None,
            "reference": f"BK-{booking.id}",
        }
        for booking in booking_entries
    )
    transactions.sort(key=lambda item: item["created_at"] or "", reverse=True)

    return {
        "balance": float(user.wallet_balance or 0),
        "transactions": transactions[:50],
    }, 200
