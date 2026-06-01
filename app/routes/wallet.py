# app/routes/wallet.py
"""Wallet API for balance, transaction history, and top-up initiation."""

from datetime import datetime, timezone
from decimal import Decimal
import uuid

from flask import Blueprint, current_app, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import func

from ..extensions import db
from ..models import (
    Booking,
    BookingStatus,
    PaymentStatus,
    User,
    WalletTopup,
    WalletTransactionType,
)
from ..services.payments import (
    PaymentConfigurationError,
    PaymentProviderError,
    create_wallet_topup_checkout_session,
)
from ..services.wallet_service import credit, emit_wallet_update, get_balance, get_transactions

wallet_v2_bp = Blueprint("wallet_v2", __name__, url_prefix="/api/wallet/v2")


def _current_user():
    return db.session.get(User, int(get_jwt_identity()))


def _absolute_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return request.host_url.rstrip("/")
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if not value.startswith("/"):
        value = f"/{value}"
    return f"{request.host_url.rstrip('/')}{value}"


@wallet_v2_bp.route("/balance", methods=["GET"])
@jwt_required()
def balance():
    user_id = int(get_jwt_identity())
    wallet_balance = get_balance(user_id)
    pending_earnings = (
        db.session.query(func.sum(Booking.worker_earnings))
        .filter(
            Booking.provider_id == user_id,
            Booking.is_deleted.is_(False),
            Booking.payment_status.in_(
                [PaymentStatus.CAPTURED, PaymentStatus.CASH_COLLECTED]
            ),
            Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.IN_PROGRESS]),
        )
        .scalar()
        or Decimal("0.00")
    )
    return {
        "balance": float(wallet_balance),
        "pending_earnings": float(pending_earnings),
        "currency": "INR",
    }, 200


@wallet_v2_bp.route("/transactions", methods=["GET"])
@jwt_required()
def transactions():
    user_id = int(get_jwt_identity())
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 10)), 1), 100)
    txn_type = (request.args.get("type") or "").strip().upper() or None
    limit = min(int(request.args.get("limit", per_page)), 100)
    before_id = request.args.get("before_id")
    before_id = int(before_id) if before_id else None

    result = get_transactions(
        user_id,
        limit=limit,
        before_id=before_id,
        page=page,
        per_page=per_page,
        txn_type=txn_type,
    )
    return result, 200


@wallet_v2_bp.route("/topup", methods=["POST"])
@jwt_required()
def topup():
    """Create a gateway-backed wallet top-up or credit instantly in mock mode."""
    user = _current_user()
    if not user:
        return {"error": "user not found"}, 404

    data = request.get_json() or {}
    try:
        amount = Decimal(str(data.get("amount", 0)))
    except Exception:
        return {"error": "invalid amount"}, 400

    if amount < 100:
        return {"error": "minimum top-up is Rs 100"}, 400
    if amount > 50000:
        return {"error": "maximum top-up is Rs 50,000"}, 400

    provider = (current_app.config.get("WALLET_TOPUP_PROVIDER") or "mock").lower()

    if provider == "mock":
        env = (current_app.config.get("ENV") or "development").lower()
        if env != "development":
            return {"error": "mock top-ups are disabled outside development"}, 403
        topup_ref = f"mock_topup_{user.id}_{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:8]}"
        topup = WalletTopup(
            user_id=user.id,
            provider="mock",
            topup_reference=topup_ref,
            gateway_order_id=f"mock_session_{topup_ref}",
            gateway_payment_id=f"mock_pi_{topup_ref}",
            amount=amount,
            currency="INR",
            status="PENDING",
        )
        db.session.add(topup)
        db.session.commit()
        return {
            "provider": "mock",
            "topup_reference": topup_ref,
            "amount": float(amount),
            "currency": "INR",
            "message": "Mock top-up initialized (requires verification via mock pay endpoint)"
        }, 201

    topup_ref = f"topup_{user.id}_{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:8]}"
    topup = WalletTopup(
        user_id=user.id,
        provider=provider,
        topup_reference=topup_ref,
        amount=amount,
        currency="INR",
        status="PENDING",
    )
    db.session.add(topup)
    db.session.flush()

    if provider == "stripe":
        try:
            session = create_wallet_topup_checkout_session(
                user,
                amount,
                success_url=_absolute_url(
                    current_app.config.get("WALLET_TOPUP_SUCCESS_URL")
                ),
                cancel_url=_absolute_url(
                    current_app.config.get("WALLET_TOPUP_CANCEL_URL")
                ),
                topup_reference=topup_ref,
            )
            topup.gateway_order_id = session.session_id
            topup.gateway_payment_id = session.payment_intent_id
            topup.metadata_json = {
                "checkout_url": session.checkout_url,
                "currency": session.currency,
            }
            db.session.commit()
            return {
                "provider": "stripe",
                "session_id": session.session_id,
                "checkout_url": session.checkout_url,
                "payment_intent_id": session.payment_intent_id,
                "amount": float(amount),
                "currency": session.currency,
                "topup_reference": topup_ref,
            }, 201
        except (PaymentConfigurationError, PaymentProviderError) as exc:
            db.session.rollback()
            current_app.logger.error(
                "wallet.topup_failed",
                extra={"provider": "stripe", "error": str(exc)},
            )
            return {"error": str(exc)}, 400
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception(
                "wallet.topup_failed",
                extra={"provider": "stripe", "error": str(exc)},
            )
            return {"error": "Failed to create top-up checkout session"}, 500

    if provider != "razorpay":
        db.session.rollback()
        return {"error": "unsupported wallet top-up provider"}, 400

    try:
        from ..services.payment_service import create_order

        amount_paise = int(amount * 100)
        order = create_order(
            amount_paise=amount_paise,
            currency="INR",
            booking_id=topup_ref,
            notes={
                "user_id": str(user.id),
                "topup_id": topup_ref,
            },
        )
        topup.gateway_order_id = order.get("id")
        topup.metadata_json = {
            "order_payload": {
                "receipt": topup_ref,
                "amount_paise": amount_paise,
            }
        }
        db.session.commit()
        return {
            "provider": "razorpay",
            "order_id": order.get("id"),
            "amount": float(amount),
            "amount_paise": amount_paise,
            "currency": "INR",
            "razorpay_key_id": current_app.config.get("RAZORPAY_KEY_ID", ""),
            "topup_reference": topup_ref,
        }, 201
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f"wallet.topup_failed: {exc}")
        return {"error": "Failed to create top-up order"}, 500



@wallet_v2_bp.route("/topup/<topup_ref>/pay", methods=["POST"])
@jwt_required()
def pay_mock_topup(topup_ref):
    if (current_app.config.get("ENV") or "development") != "development":
        return {"error": "mock top-up payment is disabled outside development"}, 403
    if not current_app.config.get("ALLOW_MOCK_PAYMENTS", False):
        return {"error": "mock payments are disabled"}, 403

    user_id = int(get_jwt_identity())
    topup = WalletTopup.query.filter_by(topup_reference=topup_ref, user_id=user_id).first()
    if not topup:
        return {"error": "top-up record not found"}, 404
    if topup.status == "COMPLETED":
        return {"error": "already completed"}, 400

    # Reconcile mock topup securely via the webhook handler helper
    from .webhooks import _complete_wallet_topup
    
    payload_object = {
        "id": topup.gateway_order_id or f"mock_session_{topup_ref}",
        "payment_intent": topup.gateway_payment_id or f"mock_pi_{topup_ref}",
        "amount_total": int(topup.amount * 100),
        "metadata": {
            "flow": "wallet_topup",
            "topup_reference": topup.topup_reference,
            "user_id": str(user_id)
        }
    }
    event_id = f"evt_mock_{topup_ref}"
    
    status = _complete_wallet_topup(topup, payload_object, event_id)
    return {
        "status": status,
        "message": "Mock top-up payment completed successfully via webhook reconciliation"
    }, 200
