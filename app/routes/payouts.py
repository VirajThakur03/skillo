from flask import Blueprint, jsonify, request, current_app, redirect
from flask_jwt_extended import get_jwt_identity, jwt_required
from decimal import Decimal

from ..extensions import db
from ..models import User, RoleEnum, WalletTransactionType
from ..services.wallet_service import debit, emit_wallet_update, InsufficientBalanceError
from ..services.payments import (
    create_stripe_connect_account,
    create_stripe_account_link,
    get_stripe_account,
    trigger_stripe_transfer
)

payouts_bp = Blueprint("payouts", __name__, url_prefix="/api/payouts")

def _current_user():
    return db.session.get(User, int(get_jwt_identity()))

@payouts_bp.route("/onboard", methods=["POST"])
@jwt_required()
def start_onboarding():
    user = _current_user()
    if not user or user.role != RoleEnum.PROVIDER:
        return jsonify({"error": "Only providers can onboard for payouts"}), 403

    if current_app.config.get("PAYMENT_PROVIDER") == "mock":
        user.stripe_account_id = f"acct_mock_{user.id}"
        user.stripe_onboarding_complete = True
        db.session.commit()
        return jsonify({"message": "Mock onboarding complete", "status": "completed"}), 200

    if not user.stripe_account_id:
        try:
            account_id = create_stripe_connect_account(user.email, user.id)
            user.stripe_account_id = account_id
            db.session.commit()
        except Exception as e:
            current_app.logger.error(f"Failed to create Stripe account: {e}")
            return jsonify({"error": "Failed to initialize payout account"}), 500

    # Create account link
    scheme = request.headers.get("X-Forwarded-Proto", "http")
    base_url = f"{scheme}://{request.host}"
    
    refresh_url = f"{base_url}/api/payouts/onboard/refresh"
    return_url = f"{base_url}/api/payouts/onboard/callback"

    try:
        url = create_stripe_account_link(user.stripe_account_id, refresh_url, return_url)
        return jsonify({"url": url}), 200
    except Exception as e:
        current_app.logger.error(f"Failed to create Stripe account link: {e}")
        return jsonify({"error": "Failed to create onboarding link"}), 500

@payouts_bp.route("/onboard/callback", methods=["GET"])
@jwt_required()
def onboarding_callback():
    user = _current_user()
    if not user or not user.stripe_account_id:
        return jsonify({"error": "Account not found"}), 404

    if current_app.config.get("PAYMENT_PROVIDER") == "mock":
        return jsonify({"status": "completed"}), 200

    try:
        account = get_stripe_account(user.stripe_account_id)
        if account.get("details_submitted"):
            user.stripe_onboarding_complete = True
            db.session.commit()
            return jsonify({"status": "completed"}), 200
        else:
            return jsonify({"status": "pending", "message": "Onboarding not finished"}), 200
    except Exception as e:
        current_app.logger.error(f"Failed to verify Stripe onboarding: {e}")
        return jsonify({"error": "Verification failed"}), 500

@payouts_bp.route("/withdraw", methods=["POST"])
@jwt_required()
def withdraw_funds():
    user = _current_user()
    if not user or user.role != RoleEnum.PROVIDER:
        return jsonify({"error": "Unauthorized"}), 403

    if not user.stripe_onboarding_complete:
        return jsonify({"error": "Please complete onboarding first"}), 400

    data = request.get_json() or {}
    amount_str = data.get("amount")
    if not amount_str:
        return jsonify({"error": "Amount required"}), 400

    try:
        amount = Decimal(str(amount_str))
    except Exception:
        return jsonify({"error": "Invalid amount"}), 400

    if amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400

    if current_app.config.get("PAYMENT_PROVIDER") == "mock":
        try:
            txn = debit(
                user_id=user.id,
                amount=amount,
                txn_type=WalletTransactionType.DEBIT_WITHDRAWAL,
                description=f"Wallet withdrawal for provider #{user.id}",
                reference_type="payout",
            )
        except InsufficientBalanceError:
            return jsonify({"error": "Insufficient balance"}), 400
        db.session.commit()
        emit_wallet_update(user.id)
        return jsonify({"message": "Mock payout successful", "payout_id": f"po_mock_{user.id}", "wallet_balance": float(txn.balance_after)}), 200

    try:
        transfer_id = trigger_stripe_transfer(
            user.stripe_account_id,
            amount,
            "INR", # Default for now, could be dynamic
            description=f"Payout for user {user.id}"
        )
        txn = debit(
            user_id=user.id,
            amount=amount,
            txn_type=WalletTransactionType.DEBIT_WITHDRAWAL,
            description=f"Wallet withdrawal transfer {transfer_id}",
            reference_type="payout",
        )
        db.session.commit()
        emit_wallet_update(user.id)

        return jsonify({"message": "Payout initiated", "transfer_id": transfer_id, "wallet_balance": float(txn.balance_after)}), 200
    except InsufficientBalanceError:
        db.session.rollback()
        return jsonify({"error": "Insufficient balance"}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Payout failed: {e}")
        return jsonify({"error": "Payout failed. Please contact support."}), 500
