# app/services/wallet_service.py
"""Wallet operations — credit, debit, and transaction history."""

from datetime import datetime, timezone
from decimal import Decimal

from flask import current_app
from sqlalchemy import func

from ..extensions import db, socketio
from ..models import User, WalletTransaction, WalletTransactionType
from .accounting import post_wallet_transaction_entries


class InsufficientBalanceError(Exception):
    pass


def _utc_now():
    return datetime.now(timezone.utc)


def _locked_user(user_id: int) -> User | None:
    query = db.session.query(User).filter(User.id == user_id)
    if db.engine.dialect.name != "sqlite":
        query = query.with_for_update()
    return query.one_or_none()


def credit(
    user_id: int,
    amount: Decimal,
    txn_type: WalletTransactionType,
    description: str,
    reference_type: str = None,
    reference_id: int = None,
) -> WalletTransaction:
    """Add funds to a user's wallet. Returns the transaction record."""
    amount = Decimal(str(amount))
    if amount <= 0:
        raise ValueError("credit amount must be positive")

    user = _locked_user(user_id)
    if not user:
        raise ValueError("user not found")

    user.wallet_balance = Decimal(user.wallet_balance or 0) + amount
    txn = WalletTransaction(
        user_id=user_id,
        txn_type=txn_type,
        amount=amount,
        balance_after=user.wallet_balance,
        reference_type=reference_type,
        reference_id=reference_id,
        description=description,
    )
    db.session.add(txn)
    db.session.flush()
    post_wallet_transaction_entries(txn)
    current_app.logger.info(
        "wallet.credit",
        extra={
            "user_id": user_id,
            "amount": float(amount),
            "type": txn_type.value,
            "balance_after": float(user.wallet_balance),
        },
    )
    return txn


def debit(
    user_id: int,
    amount: Decimal,
    txn_type: WalletTransactionType,
    description: str,
    reference_type: str = None,
    reference_id: int = None,
    allow_negative: bool = False,
) -> WalletTransaction:
    """Remove funds from a user's wallet. Raises InsufficientBalanceError if not enough."""
    amount = Decimal(str(amount))
    if amount <= 0:
        raise ValueError("debit amount must be positive")

    user = _locked_user(user_id)
    if not user:
        raise ValueError("user not found")

    balance = Decimal(user.wallet_balance or 0)
    if not allow_negative and balance < amount:
        raise InsufficientBalanceError(
            f"Insufficient balance: have ₹{balance}, need ₹{amount}"
        )

    user.wallet_balance = balance - amount
    txn = WalletTransaction(
        user_id=user_id,
        txn_type=txn_type,
        amount=-amount,
        balance_after=user.wallet_balance,
        reference_type=reference_type,
        reference_id=reference_id,
        description=description,
    )
    db.session.add(txn)
    db.session.flush()
    post_wallet_transaction_entries(txn)
    current_app.logger.info(
        "wallet.debit",
        extra={
            "user_id": user_id,
            "amount": float(amount),
            "type": txn_type.value,
            "balance_after": float(user.wallet_balance),
        },
    )
    return txn


def get_balance(user_id: int) -> Decimal:
    user = db.session.get(User, user_id)
    if not user:
        raise ValueError("user not found")
    return Decimal(user.wallet_balance or 0)


def emit_wallet_update(user_id: int) -> None:
    try:
        balance = float(get_balance(user_id))
        socketio.emit(
            "wallet_updated",
            {"user_id": user_id, "balance": balance},
            to=f"user_{user_id}",
        )
    except Exception as exc:  # pragma: no cover - realtime best effort
        current_app.logger.warning(
            "wallet.socket_emit_failed",
            extra={"user_id": user_id, "error": str(exc)},
        )


def get_transactions(
    user_id: int,
    limit: int = 50,
    before_id: int = None,
    page: int = None,
    per_page: int = None,
    txn_type: str = None,
) -> dict:
    """Paginated transaction history for a user."""
    query = WalletTransaction.query.filter_by(user_id=user_id)
    if txn_type:
        try:
            enum_type = WalletTransactionType[txn_type]
        except KeyError:
            return {
                "items": [],
                "total": 0,
                "total_pages": 0,
                "current_page": max(page or 1, 1),
            }
        query = query.filter(WalletTransaction.txn_type == enum_type)

    if page is not None or per_page is not None:
        current_page = max(page or 1, 1)
        page_size = min(max(per_page or 10, 1), 100)
        total = query.with_entities(func.count(WalletTransaction.id)).scalar() or 0
        rows = (
            query.order_by(WalletTransaction.created_at.desc(), WalletTransaction.id.desc())
            .offset((current_page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        total_pages = (total + page_size - 1) // page_size if total else 1
        return {
            "items": [_serialize_transaction(txn) for txn in rows],
            "total": total,
            "total_pages": total_pages,
            "current_page": current_page,
            "per_page": page_size,
            "has_more": current_page < total_pages,
        }

    if before_id:
        query = query.filter(WalletTransaction.id < before_id)
    rows = query.order_by(WalletTransaction.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [_serialize_transaction(txn) for txn in rows]

    return {
        "items": items,
        "has_more": has_more,
        "next_before_id": items[-1]["id"] if has_more and items else None,
    }


def _serialize_transaction(txn: WalletTransaction) -> dict:
    reference = None
    if txn.reference_type and txn.reference_id:
        reference = f"{txn.reference_type} #{txn.reference_id}"
    elif txn.reference_type:
        reference = txn.reference_type

    return {
        "id": txn.id,
        "type": txn.txn_type.value,
        "title": txn.description,
        "amount": float(txn.amount),
        "balance_after": float(txn.balance_after),
        "description": txn.description,
        "reference_type": txn.reference_type,
        "reference_id": txn.reference_id,
        "reference": reference,
        "created_at": txn.created_at.isoformat() if txn.created_at else None,
    }
