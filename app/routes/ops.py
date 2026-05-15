from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import case, func, or_

from ..extensions import db
from ..models import (
    AIJobIntakeLog,
    AccountingEntry,
    AuditLog,
    Booking,
    BookingDispute,
    BookingStatus,
    PaymentStatus,
    ChatInsight,
    DisputeStatus,
    FraudFlag,
    KycStatus,
    Message,
    MembershipStatus,
    NotificationCategory,
    PromoCode,
    PromoDiscountType,
    PromoRedemption,
    ReferralReward,
    ReferralRewardStatus,
    Review,
    RoleEnum,
    SearchQueryLog,
    Skill,
    SubscriptionPlan,
    User,
    UserSubscription,
    WalletTopup,
    WalletTransaction,
)
from ..services.accounting import (
    ACCOUNT_GATEWAY_CLEARING,
    ACCOUNT_GST_PAYABLE,
    ACCOUNT_PLATFORM_COMMISSION_REVENUE,
    ACCOUNT_PROVIDER_PAYABLE,
    ACCOUNT_SUBSCRIPTION_REVENUE,
    ACCOUNT_WALLET_LIABILITY,
)
from ..services.ai_helpers import (
    infer_job_intake,
    rank_provider_match,
    summarize_chat,
    summarize_reviews,
)
from ..services.marketplace import create_notification

ops_bp = Blueprint("ops", __name__, url_prefix="/api/ops")


def _current_user():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return None, ({"error": "user not found"}, 404)
    return user, None


def _require_admin():
    user, error = _current_user()
    if error:
        return None, error
    user_role = getattr(user.role, "value", user.role)
    if not user.is_admin and str(user_role).lower() != "admin":
        return None, ({"error": "admin only"}, 403)
    return user, None


def _mask_phone(phone):
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if not digits:
        return None
    if len(digits) <= 5:
        return digits
    return f"+91 XXXXX {digits[-5:]}"


def _mask_email(email):
    email = str(email or "").strip()
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[:1] + "*"
    else:
        masked_local = local[:2] + "*" * max(1, len(local) - 2)
    return f"{masked_local}@{domain}"


def _serialize_audit_entry(entry):
    return {
        "id": entry.id,
        "event_type": entry.event_type,
        "actor_id": entry.actor_id,
        "actor_role": entry.actor_role,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "metadata": entry.metadata_json or {},
        "ip_address": entry.ip_address,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def _serialize_dispute(item):
    return {
        "id": item.id,
        "booking_id": item.booking_id,
        "opened_by_user_id": item.opened_by_user_id,
        "assigned_admin_id": item.assigned_admin_id,
        "status": item.status.value,
        "category": item.category,
        "description": item.description,
        "evidence": item.evidence or [],
        "resolution_notes": item.resolution_notes,
        "refund_amount": float(item.refund_amount or 0),
        "created_at": item.created_at.isoformat(),
    }


def _serialize_subscription(item):
    return {
        "id": item.id,
        "user_id": item.user_id,
        "plan": {
            "id": item.plan.id,
            "slug": item.plan.slug,
            "name": item.plan.name,
            "price": float(item.plan.price or 0),
            "billing_period": item.plan.billing_period,
            "benefits": item.plan.benefits or [],
        },
        "status": item.status.value,
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "ends_at": item.ends_at.isoformat() if item.ends_at else None,
    }


def _money(value):
    return float(Decimal(value or 0))


@ops_bp.route("/referrals", methods=["GET"])
@jwt_required()
def referral_dashboard():
    user, error = _current_user()
    if error:
        return error

    rewards = ReferralReward.query.filter_by(referrer_user_id=user.id).order_by(ReferralReward.created_at.desc()).all()
    return {
        "referral_code": user.referral_code,
        "wallet_balance": float(user.wallet_balance or 0),
        "referrals_count": len(user.referrals),
        "rewards": [
            {
                "id": reward.id,
                "referred_user_id": reward.referred_user_id,
                "booking_id": reward.booking_id,
                "status": reward.status.value,
                "reward_amount": float(reward.reward_amount or 0),
                "note": reward.note,
                "created_at": reward.created_at.isoformat(),
            }
            for reward in rewards
        ],
    }, 200


@ops_bp.route("/promos", methods=["GET"])
def list_promos():
    now = datetime.now(timezone.utc)
    promos = PromoCode.query.filter_by(active=True).all()
    return {
        "items": [
            {
                "code": promo.code,
                "title": promo.title,
                "description": promo.description,
                "discount_type": promo.discount_type.value,
                "discount_value": float(promo.discount_value or 0),
                "min_order_amount": float(promo.min_order_amount or 0),
                "expires_at": promo.expires_at.isoformat() if promo.expires_at else None,
            }
            for promo in promos
            if not promo.expires_at or promo.expires_at >= now
        ]
    }, 200


@ops_bp.route("/promos/validate", methods=["POST"])
@jwt_required(optional=True)
def validate_promo():
    data = request.get_json() or {}
    code = (data.get("code") or "").strip().upper()
    amount = Decimal(str(data.get("amount") or 0))
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id)) if user_id is not None else None

    promo = PromoCode.query.filter_by(code=code, active=True).first()
    if not promo:
        return {"error": "promo code not found"}, 404
    if promo.expires_at and promo.expires_at < datetime.now(timezone.utc):
        return {"error": "promo code expired"}, 409
    if amount < Decimal(promo.min_order_amount or 0):
        return {"error": "order amount does not meet promo minimum"}, 409
    if promo.usage_limit is not None and promo.used_count >= promo.usage_limit:
        return {"error": "promo usage limit reached"}, 409
    if promo.first_booking_only and user:
        prior_bookings = Booking.query.filter_by(seeker_id=user.id).count()
        if prior_bookings > 0:
            return {"error": "promo is only valid on the first booking"}, 409

    if promo.discount_type == PromoDiscountType.PERCENT:
        discount = (amount * Decimal(promo.discount_value or 0)) / Decimal("100")
    else:
        discount = Decimal(promo.discount_value or 0)
    if promo.max_discount_amount:
        discount = min(discount, Decimal(promo.max_discount_amount))
    discount = min(discount, amount)
    return {
        "code": promo.code,
        "title": promo.title,
        "discount_amount": float(round(discount, 2)),
    }, 200


@ops_bp.route("/memberships/plans", methods=["GET"])
def membership_plans():
    plans = SubscriptionPlan.query.filter_by(active=True).order_by(SubscriptionPlan.price.asc()).all()
    if not plans:
        starter = SubscriptionPlan(
            slug="priority-seeker",
            name="Priority Seeker",
            audience="SEEKER",
            price=Decimal("299.00"),
            benefits=["Priority support", "Loyalty credits", "Preferred booking queue"],
            priority_support=True,
            loyalty_credit=Decimal("100.00"),
        )
        provider_plan = SubscriptionPlan(
            slug="pro-provider",
            name="Pro Provider",
            audience="PROVIDER",
            price=Decimal("499.00"),
            benefits=["Reduced platform fee", "Priority support", "Featured search boosts"],
            priority_support=True,
            reduced_fee_pct=Decimal("2.00"),
        )
        db.session.add(starter)
        db.session.add(provider_plan)
        db.session.commit()
        plans = [starter, provider_plan]

    return {
        "items": [
            {
                "id": plan.id,
                "slug": plan.slug,
                "name": plan.name,
                "audience": plan.audience,
                "price": float(plan.price or 0),
                "billing_period": plan.billing_period,
                "benefits": plan.benefits or [],
                "priority_support": plan.priority_support,
                "reduced_fee_pct": float(plan.reduced_fee_pct or 0) if plan.reduced_fee_pct is not None else None,
                "loyalty_credit": float(plan.loyalty_credit or 0) if plan.loyalty_credit is not None else None,
            }
            for plan in plans
        ]
    }, 200


@ops_bp.route("/memberships/subscribe", methods=["POST"])
@jwt_required()
def subscribe_membership():
    user, error = _current_user()
    if error:
        return error

    data = request.get_json() or {}
    plan = db.session.get(SubscriptionPlan, data.get("plan_id"))
    if not plan or not plan.active:
        return {"error": "plan not found"}, 404

    existing = UserSubscription.query.filter_by(user_id=user.id, status=MembershipStatus.ACTIVE).first()
    if existing:
        existing.status = MembershipStatus.CANCELLED
        existing.ends_at = datetime.now(timezone.utc)

    subscription = UserSubscription(
        user_id=user.id,
        plan_id=plan.id,
        status=MembershipStatus.ACTIVE,
        started_at=datetime.now(timezone.utc),
        ends_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.session.add(subscription)
    if plan.loyalty_credit:
        from ..models import WalletTransactionType
        from ..services.wallet_service import credit as wallet_credit, emit_wallet_update
        wallet_credit(
            user_id=user.id,
            amount=Decimal(plan.loyalty_credit or 0),
            txn_type=WalletTransactionType.CREDIT_PROMO,
            description=f"Loyalty credit for membership {plan.name}",
            reference_type="membership",
            reference_id=subscription.id,
        )
    db.session.commit()
    if plan.loyalty_credit:
        emit_wallet_update(user.id)
    return _serialize_subscription(subscription), 201


@ops_bp.route("/memberships/me", methods=["GET"])
@jwt_required()
def my_membership():
    user, error = _current_user()
    if error:
        return error

    subscription = (
        UserSubscription.query.filter_by(user_id=user.id)
        .order_by(UserSubscription.created_at.desc())
        .first()
    )
    return {"subscription": _serialize_subscription(subscription) if subscription else None}, 200


@ops_bp.route("/disputes", methods=["POST"])
@jwt_required()
def create_dispute():
    user, error = _current_user()
    if error:
        return error

    data = request.get_json() or {}
    booking = db.session.get(Booking, data.get("booking_id"))
    if not booking:
        return {"error": "booking not found"}, 404
    if user.id not in (booking.seeker_id, booking.provider_id) and not user.is_admin:
        return {"error": "forbidden"}, 403

    dispute = BookingDispute(
        booking_id=booking.id,
        opened_by_user_id=user.id,
        category=(data.get("category") or "OTHER").upper(),
        description=(data.get("description") or "").strip() or "No description provided.",
        evidence=data.get("evidence") or [],
        status=DisputeStatus.OPEN,
    )
    db.session.add(dispute)
    create_notification(
        recipient_id=booking.provider_id if user.id == booking.seeker_id else booking.seeker_id,
        category=NotificationCategory.BOOKING_UPDATE,
        title="Dispute opened",
        body=f"A dispute was opened for booking #{booking.id}.",
        entity_type="booking",
        entity_id=booking.id,
        deep_link=f"/track/{booking.id}",
        template_key="booking.dispute_opened",
    )
    AuditLog.record(
        "dispute.raised",
        actor_id=user.id,
        actor_role=user.role.value,
        target_type="dispute",
        target_id=dispute.id,
        metadata={
            "booking_id": booking.id,
            "raised_by_role": user.role.value,
            "reason": dispute.category,
        },
        request=request,
    )
    db.session.commit()
    return _serialize_dispute(dispute), 201


@ops_bp.route("/disputes", methods=["GET"])
@jwt_required()
def list_disputes():
    user, error = _current_user()
    if error:
        return error

    query = BookingDispute.query
    if not user.is_admin:
        query = query.filter(
            (BookingDispute.opened_by_user_id == user.id)
            | (BookingDispute.booking_id.in_([item.id for item in Booking.query.filter(
                (Booking.seeker_id == user.id) | (Booking.provider_id == user.id)
            ).all()]))
        )

    items = query.order_by(BookingDispute.created_at.desc()).all()
    return {"items": [_serialize_dispute(item) for item in items]}, 200


@ops_bp.route("/disputes/<int:dispute_id>", methods=["PATCH"])
@jwt_required()
def resolve_dispute(dispute_id):
    admin, error = _require_admin()
    if error:
        return error

    dispute = db.session.get(BookingDispute, dispute_id)
    if not dispute:
        return {"error": "dispute not found"}, 404

    data = request.get_json() or {}
    dispute.status = DisputeStatus[(data.get("status") or "UNDER_REVIEW").upper()]
    dispute.assigned_admin_id = admin.id
    dispute.resolution_notes = data.get("resolution_notes", dispute.resolution_notes)
    if data.get("refund_amount") is not None:
        dispute.refund_amount = Decimal(str(data.get("refund_amount")))
    AuditLog.record(
        "dispute.resolved",
        actor_id=admin.id,
        actor_role="admin",
        target_type="dispute",
        target_id=dispute.id,
        metadata={
            "dispute_id": dispute.id,
            "outcome": dispute.status.value,
            "refund_amount": float(dispute.refund_amount or 0),
        },
        request=request,
    )
    db.session.commit()
    return _serialize_dispute(dispute), 200


@ops_bp.route("/admin/overview", methods=["GET"])
@jwt_required()
def admin_overview():
    _, error = _require_admin()
    if error:
        return error

    providers = User.query.filter_by(role=RoleEnum.PROVIDER).all()
    seekers = User.query.filter_by(role=RoleEnum.SEEKER).all()
    bookings = Booking.query.all()
    disputes = BookingDispute.query.all()
    fraud_flags = FraudFlag.query.all()
    top_queries = Counter(
        item.query_text.strip().lower()
        for item in SearchQueryLog.query.filter(SearchQueryLog.query_text.isnot(None)).all()
        if item.query_text and item.query_text.strip()
    ).most_common(5)
    city_rows = {}
    for provider in providers:
        key = provider.location or "Unknown"
        row = city_rows.setdefault(key, {"providers": 0, "skills": 0, "completed_jobs": 0})
        row["providers"] += 1
        row["skills"] += len(provider.skills)
        row["completed_jobs"] += provider.completed_jobs or 0

    return {
        "users": {
            "seekers": len(seekers),
            "providers": len(providers),
        },
        "bookings": {
            "total": len(bookings),
            "pending": sum(1 for item in bookings if item.status == BookingStatus.PENDING),
            "confirmed": sum(1 for item in bookings if item.status == BookingStatus.CONFIRMED),
            "completed": sum(1 for item in bookings if item.status == BookingStatus.COMPLETED),
            "cancelled": sum(1 for item in bookings if item.status == BookingStatus.CANCELLED),
        },
        "disputes": {
            "open": sum(1 for item in disputes if item.status in {DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW}),
            "resolved": sum(1 for item in disputes if item.status == DisputeStatus.RESOLVED),
        },
        "fraud_flags": len(fraud_flags),
        "top_queries": [
            {"query": query, "count": count}
            for query, count in top_queries
        ],
        "top_categories": Counter(
            booking.skill.title for booking in bookings if booking.skill
        ).most_common(5),
        "trends": {
            "bookings": [
                {
                    "day": (datetime.now(timezone.utc) - timedelta(days=i)).date().isoformat(),
                    "count": sum(1 for b in bookings if b.created_at and b.created_at.date() == (datetime.now(timezone.utc) - timedelta(days=i)).date())
                }
                for i in range(29, -1, -1)
            ],
            "revenue": [
                {
                    "day": (datetime.now(timezone.utc) - timedelta(days=i)).date().isoformat(),
                    "amount": float(sum(b.price or 0 for b in bookings if b.created_at and b.created_at.date() == (datetime.now(timezone.utc) - timedelta(days=i)).date() and b.status == BookingStatus.COMPLETED))
                }
                for i in range(29, -1, -1)
            ]
        },
        "city_launch": [
            {"city": city, **stats}
            for city, stats in city_rows.items()
        ],
    }, 200


@ops_bp.route("/admin/finance/summary", methods=["GET"])
@jwt_required()
def admin_finance_summary():
    _, error = _require_admin()
    if error:
        return error

    wallet_liability_total = (
        db.session.query(func.sum(User.wallet_balance)).scalar() or Decimal("0.00")
    )
    pending_topups_total = (
        db.session.query(func.sum(WalletTopup.amount))
        .filter(WalletTopup.status == "PENDING")
        .scalar()
        or Decimal("0.00")
    )
    captured_booking_total = (
        db.session.query(func.sum(Booking.amount_payable))
        .filter(Booking.payment_status == PaymentStatus.CAPTURED)
        .scalar()
        or Decimal("0.00")
    )

    def _ledger_total(account_code, direction):
        return (
            db.session.query(func.sum(AccountingEntry.amount))
            .filter(
                AccountingEntry.account_code == account_code,
                AccountingEntry.direction == direction,
            )
            .scalar()
            or Decimal("0.00")
        )

    return {
        "wallet_liability_total": _money(wallet_liability_total),
        "pending_topups": {
            "count": WalletTopup.query.filter(WalletTopup.status == "PENDING").count(),
            "amount": _money(pending_topups_total),
        },
        "captured_bookings_total": _money(captured_booking_total),
        "ledger": {
            "entries": AccountingEntry.query.count(),
            "gateway_clearing_debits": _money(
                _ledger_total(ACCOUNT_GATEWAY_CLEARING, "DEBIT")
            ),
            "wallet_liability_credits": _money(
                _ledger_total(ACCOUNT_WALLET_LIABILITY, "CREDIT")
            ),
            "provider_payable_credits": _money(
                _ledger_total(ACCOUNT_PROVIDER_PAYABLE, "CREDIT")
            ),
            "gst_payable_credits": _money(
                _ledger_total(ACCOUNT_GST_PAYABLE, "CREDIT")
            ),
            "commission_revenue_credits": _money(
                _ledger_total(ACCOUNT_PLATFORM_COMMISSION_REVENUE, "CREDIT")
            ),
            "subscription_revenue_credits": _money(
                _ledger_total(ACCOUNT_SUBSCRIPTION_REVENUE, "CREDIT")
            ),
        },
    }, 200


@ops_bp.route("/admin/finance/reconciliation", methods=["GET"])
@jwt_required()
def admin_finance_reconciliation():
    _, error = _require_admin()
    if error:
        return error

    now = datetime.now(timezone.utc)
    latest_txn_ids = (
        db.session.query(
            WalletTransaction.user_id.label("user_id"),
            func.max(WalletTransaction.id).label("max_txn_id"),
        )
        .group_by(WalletTransaction.user_id)
        .subquery()
    )
    wallet_rows = (
        db.session.query(
            User.id,
            User.email,
            User.wallet_balance,
            WalletTransaction.balance_after,
        )
        .outerjoin(latest_txn_ids, latest_txn_ids.c.user_id == User.id)
        .outerjoin(WalletTransaction, WalletTransaction.id == latest_txn_ids.c.max_txn_id)
        .all()
    )

    wallet_mismatches = []
    for row in wallet_rows:
        user_balance = Decimal(row.wallet_balance or 0).quantize(Decimal("0.01"))
        latest_balance = (
            Decimal(row.balance_after or 0).quantize(Decimal("0.01"))
            if row.balance_after is not None
            else None
        )
        if latest_balance is None and user_balance == Decimal("0.00"):
            continue
        if latest_balance is None or latest_balance != user_balance:
            wallet_mismatches.append(
                {
                    "user_id": row.id,
                    "email": row.email,
                    "wallet_balance": _money(user_balance),
                    "latest_transaction_balance": _money(latest_balance or 0),
                }
            )

    signed_net = func.sum(
        case(
            (AccountingEntry.direction == "DEBIT", AccountingEntry.amount),
            else_=-AccountingEntry.amount,
        )
    )
    unbalanced_groups = (
        db.session.query(
            AccountingEntry.entry_group,
            signed_net.label("net_amount"),
            func.count(AccountingEntry.id).label("entry_count"),
        )
        .group_by(AccountingEntry.entry_group)
        .having(signed_net != 0)
        .order_by(AccountingEntry.entry_group.asc())
        .all()
    )

    stale_topups = (
        WalletTopup.query.filter(
            WalletTopup.status == "PENDING",
            WalletTopup.created_at < now - timedelta(minutes=30),
        )
        .order_by(WalletTopup.created_at.asc())
        .all()
    )
    missing_invoices = (
        Booking.query.filter(
            Booking.status == BookingStatus.COMPLETED,
            Booking.payment_status.in_(
                [PaymentStatus.CAPTURED, PaymentStatus.CASH_COLLECTED]
            ),
            Booking.invoice_url.is_(None),
        )
        .order_by(Booking.created_at.desc())
        .all()
    )

    return {
        "summary": {
            "wallet_mismatch_count": len(wallet_mismatches),
            "unbalanced_entry_groups": len(unbalanced_groups),
            "stale_pending_topups": len(stale_topups),
            "completed_bookings_missing_invoice": len(missing_invoices),
        },
        "wallet_mismatches": wallet_mismatches[:25],
        "unbalanced_entry_groups": [
            {
                "entry_group": item.entry_group,
                "net_amount": _money(item.net_amount),
                "entry_count": item.entry_count,
            }
            for item in unbalanced_groups[:25]
        ],
        "stale_pending_topups": [
            {
                "id": item.id,
                "user_id": item.user_id,
                "provider": item.provider,
                "topup_reference": item.topup_reference,
                "gateway_order_id": item.gateway_order_id,
                "amount": _money(item.amount),
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in stale_topups[:25]
        ],
        "missing_invoices": [
            {
                "booking_id": item.id,
                "seeker_id": item.seeker_id,
                "provider_id": item.provider_id,
                "amount_payable": _money(item.amount_payable or item.price or 0),
                "payment_status": item.payment_status.value if item.payment_status else None,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in missing_invoices[:25]
        ],
    }, 200


@ops_bp.route("/admin/promos", methods=["GET"])
@jwt_required()
def admin_list_promos():
    _, error = _require_admin()
    if error:
        return error

    promos = PromoCode.query.order_by(PromoCode.created_at.desc()).all()
    return {
        "items": [
            {
                "id": promo.id,
                "code": promo.code,
                "title": promo.title,
                "discount_type": promo.discount_type.value,
                "discount_value": float(promo.discount_value or 0),
                "usage_limit": promo.usage_limit,
                "used_count": promo.used_count,
                "city": promo.city,
                "active": promo.active,
                "expires_at": promo.expires_at.isoformat() if promo.expires_at else None,
            }
            for promo in promos
        ]
    }, 200


@ops_bp.route("/admin/promos", methods=["POST"])
@jwt_required()
def create_promo():
    _, error = _require_admin()
    if error:
        return error

    data = request.get_json() or {}
    promo = PromoCode(
        code=(data.get("code") or "").strip().upper(),
        title=(data.get("title") or "").strip() or "Promo",
        description=data.get("description"),
        discount_type=PromoDiscountType[(data.get("discount_type") or "PERCENT").upper()],
        discount_value=Decimal(str(data.get("discount_value") or 0)),
        max_discount_amount=Decimal(str(data.get("max_discount_amount"))) if data.get("max_discount_amount") is not None else None,
        min_order_amount=Decimal(str(data.get("min_order_amount") or 0)),
        usage_limit=int(data.get("usage_limit")) if data.get("usage_limit") is not None else None,
        city=data.get("city"),
        first_booking_only=bool(data.get("first_booking_only", False)),
        expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
    )
    db.session.add(promo)
    db.session.commit()
    return {"id": promo.id, "code": promo.code}, 201


@ops_bp.route("/admin/fraud-flags", methods=["POST"])
@jwt_required()
def create_fraud_flag():
    _, error = _require_admin()
    if error:
        return error

    data = request.get_json() or {}
    flag = FraudFlag(
        user_id=data.get("user_id"),
        booking_id=data.get("booking_id"),
        severity=(data.get("severity") or "low").lower(),
        reason=(data.get("reason") or "").strip() or "Needs review",
        status=(data.get("status") or "open").lower(),
    )
    db.session.add(flag)
    db.session.commit()
    return {
        "id": flag.id,
        "severity": flag.severity,
        "reason": flag.reason,
    }, 201


@ops_bp.route("/admin/fraud-flags", methods=["GET"])
@jwt_required()
def list_fraud_flags():
    _, error = _require_admin()
    if error:
        return error

    flags = FraudFlag.query.order_by(FraudFlag.created_at.desc()).all()
    return {
        "items": [
            {
                "id": flag.id,
                "user_id": flag.user_id,
                "booking_id": flag.booking_id,
                "severity": flag.severity,
                "reason": flag.reason,
                "status": flag.status,
                "created_at": flag.created_at.isoformat() if flag.created_at else None,
            }
            for flag in flags
        ]
    }, 200


@ops_bp.route("/admin/users/search", methods=["GET"])
@jwt_required()
def admin_search_users():
    _, error = _require_admin()
    if error:
        return error

    q = (request.args.get("q") or "").strip()
    limit = min(max(request.args.get("limit", type=int) or 20, 1), 50)
    if len(q) < 3:
        return {"items": []}, 200

    booking_counts = dict(
        db.session.query(Booking.seeker_id, func.count(Booking.id))
        .group_by(Booking.seeker_id)
        .all()
    )
    provider_counts = dict(
        db.session.query(Booking.provider_id, func.count(Booking.id))
        .group_by(Booking.provider_id)
        .all()
    )

    users = (
        User.query.filter(
            or_(
                User.email.ilike(f"%{q}%"),
                User.phone.ilike(f"%{q}%"),
                User.name.ilike(f"%{q}%"),
            )
        )
        .order_by(User.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "items": [
            {
                "id": user.id,
                "display_name": user.name,
                "email": user.email,
                "email_masked": _mask_email(user.email),
                "phone_masked": _mask_phone(user.phone),
                "role": getattr(user.role, "value", user.role),
                "kyc_status": user.kyc_status.value if user.kyc_status else None,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "booking_count": int(booking_counts.get(user.id, 0) + provider_counts.get(user.id, 0)),
                "is_suspended": user.kyc_status == KycStatus.suspended,
            }
            for user in users
        ]
    }, 200


@ops_bp.route("/admin/bookings/search", methods=["GET"])
@jwt_required()
def admin_search_bookings():
    _, error = _require_admin()
    if error:
        return error

    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip().upper()
    limit = min(max(request.args.get("limit", type=int) or 20, 1), 50)

    if status:
        try:
            base_status = BookingStatus[status]
        except KeyError:
            return {"error": "invalid status"}, 400
    else:
        base_status = None

    bookings = Booking.query.order_by(Booking.created_at.desc()).limit(200).all()
    items = []
    for booking in bookings:
        if base_status and booking.status != base_status:
            continue
        if q:
            haystack = " ".join(
                [
                    str(booking.id),
                    booking.seeker.email if booking.seeker and booking.seeker.email else "",
                    booking.seeker.name if booking.seeker and booking.seeker.name else "",
                    booking.provider.email if booking.provider and booking.provider.email else "",
                    booking.provider.name if booking.provider and booking.provider.name else "",
                    booking.skill.title if booking.skill and booking.skill.title else "",
                ]
            ).lower()
            if q.lower() not in haystack:
                continue
        items.append(
            {
                "id": booking.id,
                "seeker_name": booking.seeker.name if booking.seeker else None,
                "provider_name": booking.provider.name if booking.provider else None,
                "status": booking.status.value if booking.status else None,
                "amount": float(booking.price or 0),
                "scheduled_at": booking.scheduled_at.isoformat() if booking.scheduled_at else None,
                "category": booking.skill.title if booking.skill else None,
                "created_at": booking.created_at.isoformat() if booking.created_at else None,
            }
        )
        if len(items) >= limit:
            break
    return {
        "items": items
    }, 200


@ops_bp.route("/admin/users/<int:user_id>", methods=["GET"])
@jwt_required()
def admin_user_detail(user_id):
    _, error = _require_admin()
    if error:
        return error

    user = db.session.get(User, user_id)
    if not user:
        return {"error": "user not found"}, 404

    recent_bookings = (
        Booking.query.filter(or_(Booking.seeker_id == user.id, Booking.provider_id == user.id))
        .order_by(Booking.created_at.desc())
        .limit(5)
        .all()
    )
    audit_entries = (
        AuditLog.query.filter(
            or_(
                AuditLog.actor_id == user.id,
                db.and_(AuditLog.target_type == "user", AuditLog.target_id == user.id),
                db.and_(AuditLog.target_type == "provider", AuditLog.target_id == user.id),
            )
        )
        .order_by(AuditLog.created_at.desc())
        .limit(20)
        .all()
    )

    return {
        "user": {
            "id": user.id,
            "display_name": user.name,
            "email": user.email,
            "email_masked": _mask_email(user.email),
            "phone": user.phone,
            "phone_masked": _mask_phone(user.phone),
            "role": getattr(user.role, "value", user.role),
            "is_admin": bool(user.is_admin),
            "is_suspended": user.kyc_status == KycStatus.suspended,
            "kyc_status": user.kyc_status.value if user.kyc_status else None,
            "trust_score": user.trust_score,
            "rating": user.rating,
            "location": user.location,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "recent_bookings": [
            {
                "id": booking.id,
                "status": booking.status.value if booking.status else None,
                "skill": booking.skill.title if booking.skill else None,
                "amount": float(booking.price or 0),
                "scheduled_at": booking.scheduled_at.isoformat() if booking.scheduled_at else None,
                "created_at": booking.created_at.isoformat() if booking.created_at else None,
            }
            for booking in recent_bookings
        ],
        "audit_log": [_serialize_audit_entry(entry) for entry in audit_entries],
    }, 200


@ops_bp.route("/admin/bookings/<int:booking_id>", methods=["GET"])
@jwt_required()
def admin_booking_detail(booking_id):
    _, error = _require_admin()
    if error:
        return error

    booking = db.session.get(Booking, booking_id)
    if not booking:
        return {"error": "booking not found"}, 404

    audit_entries = (
        AuditLog.query.filter(
            db.and_(AuditLog.target_type == "booking", AuditLog.target_id == booking.id)
        )
        .order_by(AuditLog.created_at.desc())
        .all()
    )

    return {
        "booking": {
            "id": booking.id,
            "status": booking.status.value if booking.status else None,
            "amount": float(booking.price or 0),
            "scheduled_at": booking.scheduled_at.isoformat() if booking.scheduled_at else None,
            "created_at": booking.created_at.isoformat() if booking.created_at else None,
            "category": booking.skill.title if booking.skill else None,
            "seeker": {
                "id": booking.seeker.id if booking.seeker else None,
                "name": booking.seeker.name if booking.seeker else None,
                "email_masked": _mask_email(booking.seeker.email if booking.seeker else None),
            },
            "provider": {
                "id": booking.provider.id if booking.provider else None,
                "name": booking.provider.name if booking.provider else None,
                "email_masked": _mask_email(booking.provider.email if booking.provider else None),
            },
            "payment_status": booking.payment_status.value if booking.payment_status else None,
            "payment_ref": booking.payment_ref,
            "platform_fee_amount": float(booking.platform_fee_amount or 0),
            "gst_amount": float(booking.gst_amount or 0),
            "service_amount": float(booking.service_amount or 0),
        },
        "audit_log": [_serialize_audit_entry(entry) for entry in audit_entries],
    }, 200


@ops_bp.route("/ai/job-intake", methods=["POST"])
@jwt_required(optional=True)
def ai_job_intake():
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id)) if user_id is not None else None
    data = request.get_json() or {}
    raw_text = (data.get("text") or "").strip()
    if not raw_text:
        return {"error": "text is required"}, 400

    parsed = infer_job_intake(raw_text, selected_category=data.get("selected_category"))
    log = AIJobIntakeLog(
        user_id=user.id if user else None,
        raw_text=raw_text,
        parsed_payload=parsed,
        confidence=parsed.get("confidence", 0),
    )
    db.session.add(log)
    db.session.commit()
    return parsed, 200


@ops_bp.route("/ai/provider-match", methods=["POST"])
def ai_provider_match():
    data = request.get_json() or {}
    candidates = data.get("candidates") or []
    query_text = data.get("query_text") or ""
    ranked = rank_provider_match(query_text, candidates)
    return {"ranked_provider_ids": [item["provider_id"] for item in ranked], "scores": ranked}, 200


@ops_bp.route("/ai/chat-summary", methods=["POST"])
@jwt_required(optional=True)
def ai_chat_summary():
    data = request.get_json() or {}
    room = (data.get("room") or "").strip()
    messages = data.get("messages")
    if not messages and room:
        messages = [
            item.content
            for item in Message.query.filter_by(room=room).order_by(Message.created_at.asc()).all()
        ]
    result = summarize_chat(messages or [])
    if room:
        insight = ChatInsight.query.filter_by(room=room).first()
        if not insight:
            insight = ChatInsight(room=room)
            db.session.add(insight)
        insight.summary = result["summary"]
        insight.extracted_address = result["extracted"].get("mentioned_address")
        insight.extracted_time = result["extracted"].get("mentioned_time")
        insight.quick_replies = result["reply_suggestions"]
        insight.pinned_summary = result["summary"]
        db.session.commit()
    return result, 200


@ops_bp.route("/ai/review-summary/<int:provider_id>", methods=["GET"])
def ai_review_summary(provider_id):
    provider = db.session.get(User, provider_id)
    if not provider or provider.role != RoleEnum.PROVIDER:
        return {"error": "provider not found"}, 404
    payload = [
        {
            "rating": review.rating,
            "punctuality_rating": review.punctuality_rating,
            "quality_rating": review.quality_rating,
            "communication_rating": review.communication_rating,
            "value_rating": review.value_rating,
            "comment": review.comment,
        }
        for review in Review.query.filter_by(provider_id=provider.id).all()
    ]
    return summarize_reviews(payload), 200
@ops_bp.route("/maintenance/purge", methods=["POST"])
@jwt_required()
def purge_deleted_data():
    _user, error = _require_admin()
    if error:
        return error

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    
    # Purge Messages
    deleted_messages = Message.query.filter(
        Message.is_deleted == True,
        Message.deleted_at < cutoff
    ).delete(synchronize_session=False)
    
    # Purge Bookings
    deleted_bookings = Booking.query.filter(
        Booking.is_deleted == True,
        Booking.deleted_at < cutoff
    ).delete(synchronize_session=False)
    
    db.session.commit()
    
    return jsonify({
        "message": "Purge complete",
        "purged_messages": deleted_messages,
        "purged_bookings": deleted_bookings
    }), 200
