# app/routes/subscriptions.py
"""Subscription plans API — list, subscribe, cancel, status."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..extensions import db
from ..models import (
    User,
    SubscriptionPlan,
    UserSubscription,
    MembershipStatus,
    RoleEnum,
    WalletTransactionType,
)
from ..services.wallet_service import debit, emit_wallet_update, InsufficientBalanceError

subscriptions_bp = Blueprint("subscriptions", __name__, url_prefix="/api/subscriptions")


def _utc_now():
    return datetime.now(timezone.utc)


def _plan_duration_days(plan: SubscriptionPlan) -> int:
    billing_period = (plan.billing_period or "monthly").strip().lower()
    if billing_period in {"yearly", "annual", "annually"}:
        return 365
    if billing_period in {"weekly", "week"}:
        return 7
    return 30


@subscriptions_bp.route("/plans", methods=["GET"])
def list_plans():
    plans = SubscriptionPlan.query.filter_by(active=True).order_by(SubscriptionPlan.price).all()
    return {
        "plans": [
            {
                "id": p.id,
                "name": p.name,
                "slug": p.slug,
                "price": float(p.price),
                "currency": "INR",
                "duration_days": _plan_duration_days(p),
                "features": p.benefits or [],
                "description": ", ".join((p.benefits or [])[:2]) if (p.benefits or []) else None,
                "billing_period": p.billing_period,
                "reduced_fee_pct": float(p.reduced_fee_pct) if p.reduced_fee_pct is not None else None,
                "priority_support": bool(p.priority_support),
            }
            for p in plans
        ]
    }, 200


@subscriptions_bp.route("/my", methods=["GET"])
@jwt_required()
def my_subscription():
    user_id = int(get_jwt_identity())
    sub = (
        UserSubscription.query
        .filter_by(user_id=user_id)
        .filter(UserSubscription.status == MembershipStatus.ACTIVE)
        .filter(UserSubscription.ends_at > _utc_now())
        .order_by(UserSubscription.ends_at.desc())
        .first()
    )
    if not sub:
        return {"active": False, "subscription": None}, 200

    return {
        "active": True,
        "subscription": {
            "id": sub.id,
            "plan_name": sub.plan.name if sub.plan else "Unknown",
            "status": sub.status.value,
            "started_at": sub.started_at.isoformat() if sub.started_at else None,
            "expires_at": sub.ends_at.isoformat() if sub.ends_at else None,
            "auto_renew": False,
        },
    }, 200


@subscriptions_bp.route("/subscribe", methods=["POST"])
@jwt_required()
def subscribe():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return {"error": "user not found"}, 404

    if user.role != RoleEnum.PROVIDER:
        return {"error": "only providers can subscribe to plans"}, 403

    data = request.get_json() or {}
    plan_id = data.get("plan_id")
    if not plan_id:
        return {"error": "plan_id is required"}, 400

    plan = db.session.get(SubscriptionPlan, int(plan_id))
    if not plan or not plan.active:
        return {"error": "plan not found"}, 404

    # Check if already has active subscription
    existing = (
        UserSubscription.query
        .filter_by(user_id=user_id, status=MembershipStatus.ACTIVE)
        .filter(UserSubscription.ends_at > _utc_now())
        .first()
    )
    if existing:
        return {
            "error": "You already have an active subscription",
            "expires_at": existing.ends_at.isoformat(),
        }, 409

    # Pay from wallet
    try:
        txn = debit(
            user_id=user_id,
            amount=Decimal(str(plan.price)),
            txn_type=WalletTransactionType.DEBIT_SUBSCRIPTION,
            description=f"Subscription: {plan.name} ({_plan_duration_days(plan)} days)",
            reference_type="subscription",
        )
    except InsufficientBalanceError:
        return {"error": "Insufficient wallet balance. Please top up first."}, 400

    now = _utc_now()
    sub = UserSubscription(
        user_id=user_id,
        plan_id=plan.id,
        status=MembershipStatus.ACTIVE,
        started_at=now,
        ends_at=now + timedelta(days=_plan_duration_days(plan)),
    )
    db.session.add(sub)
    db.session.commit()
    emit_wallet_update(user_id)

    return {
        "message": f"Subscribed to {plan.name}",
        "subscription_id": sub.id,
        "expires_at": sub.ends_at.isoformat(),
        "wallet_balance": float(user.wallet_balance),
    }, 201


@subscriptions_bp.route("/cancel", methods=["POST"])
@jwt_required()
def cancel_subscription():
    user_id = int(get_jwt_identity())

    sub = (
        UserSubscription.query
        .filter_by(user_id=user_id, status=MembershipStatus.ACTIVE)
        .filter(UserSubscription.ends_at > _utc_now())
        .first()
    )
    if not sub:
        return {"error": "no active subscription found"}, 404

    sub.status = MembershipStatus.CANCELLED
    db.session.commit()

    return {
        "message": "Subscription cancelled. You can use it until expiry.",
        "expires_at": sub.ends_at.isoformat() if sub.ends_at else None,
    }, 200
