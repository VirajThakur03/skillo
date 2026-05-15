from decimal import Decimal, ROUND_HALF_UP

from flask import current_app

from ..extensions import db
from ..models import AccountingEntry, WalletTransaction, WalletTransactionType


ACCOUNT_GATEWAY_CLEARING = "asset:gateway_clearing"
ACCOUNT_WALLET_LIABILITY = "liability:wallet_user_balance"
ACCOUNT_PROVIDER_PAYABLE = "liability:provider_payable"
ACCOUNT_GST_PAYABLE = "liability:gst_payable"
ACCOUNT_PLATFORM_COMMISSION_REVENUE = "revenue:platform_commission"
ACCOUNT_SUBSCRIPTION_REVENUE = "revenue:subscription"
ACCOUNT_PAYOUT_CLEARING = "asset:payout_clearing"
ACCOUNT_PROMO_EXPENSE = "expense:promo"
ACCOUNT_REFERRAL_EXPENSE = "expense:referral"
ACCOUNT_REFUND_RESERVE = "expense:refund"
ACCOUNT_EARNINGS_CLEARING = "liability:provider_earnings_clearing"
ACCOUNT_BOOKING_WALLET_CLEARING = "asset:booking_wallet_clearing"


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def post_double_entry(
    *,
    entry_group: str,
    reference_type: str,
    reference_id: int | None,
    description: str,
    entries: list[dict],
    currency: str = "INR",
    metadata: dict | None = None,
) -> list[AccountingEntry]:
    existing = AccountingEntry.query.filter_by(entry_group=entry_group).all()
    if existing:
        return existing

    debit_total = Decimal("0.00")
    credit_total = Decimal("0.00")
    created_entries = []
    for item in entries:
        amount = _money(item.get("amount"))
        direction = str(item.get("direction") or "").upper()
        if amount == Decimal("0.00"):
            continue
        if amount < 0:
            raise ValueError("accounting entry amount must be positive")
        if direction not in {"DEBIT", "CREDIT"}:
            raise ValueError("accounting entry direction must be DEBIT or CREDIT")
        if direction == "DEBIT":
            debit_total += amount
        else:
            credit_total += amount
        created_entries.append(
            AccountingEntry(
                entry_group=entry_group,
                account_code=item["account_code"],
                direction=direction,
                amount=amount,
                currency=(item.get("currency") or currency or "INR").upper(),
                reference_type=reference_type,
                reference_id=reference_id,
                description=item.get("description") or description,
                metadata_json={
                    **(metadata or {}),
                    **(item.get("metadata") or {}),
                },
            )
        )

    if not created_entries:
        return []

    if _money(debit_total) != _money(credit_total):
        raise ValueError(
            f"unbalanced accounting entry group {entry_group}: debits={debit_total} credits={credit_total}"
        )

    db.session.add_all(created_entries)
    current_app.logger.info(
        "accounting.entry_group_posted",
        extra={
            "entry_group": entry_group,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "entries": len(created_entries),
            "amount": float(debit_total),
        },
    )
    return created_entries


def post_wallet_transaction_entries(txn: WalletTransaction) -> list[AccountingEntry]:
    amount = _money(abs(Decimal(txn.amount or 0)))
    if amount <= 0:
        return []

    entry_group = f"wallet_txn:{txn.id}"
    metadata = {
        "wallet_transaction_id": txn.id,
        "wallet_user_id": txn.user_id,
        "txn_type": txn.txn_type.value,
        "balance_after": float(txn.balance_after or 0),
    }
    if txn.txn_type == WalletTransactionType.CREDIT_TOPUP:
        entries = [
            {"account_code": ACCOUNT_GATEWAY_CLEARING, "direction": "DEBIT", "amount": amount},
            {"account_code": ACCOUNT_WALLET_LIABILITY, "direction": "CREDIT", "amount": amount},
        ]
    elif txn.txn_type == WalletTransactionType.CREDIT_EARNING:
        entries = [
            {"account_code": ACCOUNT_EARNINGS_CLEARING, "direction": "DEBIT", "amount": amount},
            {"account_code": ACCOUNT_WALLET_LIABILITY, "direction": "CREDIT", "amount": amount},
        ]
    elif txn.txn_type == WalletTransactionType.CREDIT_REFUND:
        entries = [
            {"account_code": ACCOUNT_REFUND_RESERVE, "direction": "DEBIT", "amount": amount},
            {"account_code": ACCOUNT_WALLET_LIABILITY, "direction": "CREDIT", "amount": amount},
        ]
    elif txn.txn_type == WalletTransactionType.CREDIT_PROMO:
        entries = [
            {"account_code": ACCOUNT_PROMO_EXPENSE, "direction": "DEBIT", "amount": amount},
            {"account_code": ACCOUNT_WALLET_LIABILITY, "direction": "CREDIT", "amount": amount},
        ]
    elif txn.txn_type == WalletTransactionType.CREDIT_REFERRAL:
        entries = [
            {"account_code": ACCOUNT_REFERRAL_EXPENSE, "direction": "DEBIT", "amount": amount},
            {"account_code": ACCOUNT_WALLET_LIABILITY, "direction": "CREDIT", "amount": amount},
        ]
    elif txn.txn_type == WalletTransactionType.DEBIT_BOOKING:
        entries = [
            {"account_code": ACCOUNT_WALLET_LIABILITY, "direction": "DEBIT", "amount": amount},
            {"account_code": ACCOUNT_BOOKING_WALLET_CLEARING, "direction": "CREDIT", "amount": amount},
        ]
    elif txn.txn_type == WalletTransactionType.DEBIT_WITHDRAWAL:
        entries = [
            {"account_code": ACCOUNT_WALLET_LIABILITY, "direction": "DEBIT", "amount": amount},
            {"account_code": ACCOUNT_PAYOUT_CLEARING, "direction": "CREDIT", "amount": amount},
        ]
    elif txn.txn_type == WalletTransactionType.DEBIT_COMMISSION:
        entries = [
            {"account_code": ACCOUNT_WALLET_LIABILITY, "direction": "DEBIT", "amount": amount},
            {
                "account_code": ACCOUNT_PLATFORM_COMMISSION_REVENUE,
                "direction": "CREDIT",
                "amount": amount,
            },
        ]
    elif txn.txn_type == WalletTransactionType.DEBIT_SUBSCRIPTION:
        entries = [
            {"account_code": ACCOUNT_WALLET_LIABILITY, "direction": "DEBIT", "amount": amount},
            {"account_code": ACCOUNT_SUBSCRIPTION_REVENUE, "direction": "CREDIT", "amount": amount},
        ]
    else:
        return []

    return post_double_entry(
        entry_group=entry_group,
        reference_type=txn.reference_type or "wallet_transaction",
        reference_id=txn.reference_id or txn.id,
        description=txn.description,
        entries=entries,
        metadata=metadata,
    )


def record_booking_capture_entries(booking, payment_reference: str | None = None) -> list[AccountingEntry]:
    total_paid = _money(getattr(booking, "amount_payable", None) or booking.price or 0)
    if total_paid <= 0:
        return []

    platform_fee = _money(getattr(booking, "platform_fee_amount", 0))
    gst_amount = _money(getattr(booking, "gst_amount", 0))
    provider_payable_raw = getattr(booking, "worker_earnings", None)
    provider_payable = _money(
        provider_payable_raw
        if provider_payable_raw not in (None, "")
        else (total_paid - platform_fee - gst_amount)
    )
    if provider_payable == Decimal("0.00") and total_paid > Decimal("0.00"):
        provider_payable = _money(total_paid - platform_fee - gst_amount)
    if provider_payable < Decimal("0.00"):
        provider_payable = Decimal("0.00")
    return post_double_entry(
        entry_group=f"booking_capture:{booking.id}",
        reference_type="booking",
        reference_id=booking.id,
        description=f"Booking payment captured for booking #{booking.id}",
        entries=[
            {"account_code": ACCOUNT_GATEWAY_CLEARING, "direction": "DEBIT", "amount": total_paid},
            {
                "account_code": ACCOUNT_PLATFORM_COMMISSION_REVENUE,
                "direction": "CREDIT",
                "amount": platform_fee,
            },
            {"account_code": ACCOUNT_GST_PAYABLE, "direction": "CREDIT", "amount": gst_amount},
            {"account_code": ACCOUNT_PROVIDER_PAYABLE, "direction": "CREDIT", "amount": provider_payable},
        ],
        metadata={
            "payment_reference": payment_reference,
            "payment_provider": getattr(booking, "payment_provider", None),
        },
    )


def record_booking_refund_entries(booking, payment_reference: str | None = None) -> list[AccountingEntry]:
    total_paid = _money(getattr(booking, "amount_payable", None) or booking.price or 0)
    if total_paid <= 0:
        return []

    platform_fee = _money(getattr(booking, "platform_fee_amount", 0))
    gst_amount = _money(getattr(booking, "gst_amount", 0))
    provider_payable_raw = getattr(booking, "worker_earnings", None)
    provider_payable = _money(
        provider_payable_raw
        if provider_payable_raw not in (None, "")
        else (total_paid - platform_fee - gst_amount)
    )
    if provider_payable == Decimal("0.00") and total_paid > Decimal("0.00"):
        provider_payable = _money(total_paid - platform_fee - gst_amount)
    if provider_payable < Decimal("0.00"):
        provider_payable = Decimal("0.00")
    return post_double_entry(
        entry_group=f"booking_refund:{booking.id}",
        reference_type="booking_refund",
        reference_id=booking.id,
        description=f"Booking payment refunded for booking #{booking.id}",
        entries=[
            {
                "account_code": ACCOUNT_PLATFORM_COMMISSION_REVENUE,
                "direction": "DEBIT",
                "amount": platform_fee,
            },
            {"account_code": ACCOUNT_GST_PAYABLE, "direction": "DEBIT", "amount": gst_amount},
            {"account_code": ACCOUNT_PROVIDER_PAYABLE, "direction": "DEBIT", "amount": provider_payable},
            {"account_code": ACCOUNT_GATEWAY_CLEARING, "direction": "CREDIT", "amount": total_paid},
        ],
        metadata={
            "payment_reference": payment_reference,
            "payment_provider": getattr(booking, "payment_provider", None),
        },
    )
