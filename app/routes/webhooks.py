from flask import Blueprint, current_app, jsonify, request
from decimal import Decimal

from ..extensions import db, limiter
from datetime import datetime, timezone

from ..models import (
    Booking,
    BookingStatus,
    PaymentStatus,
    WalletTopup,
    WalletTransactionType,
    WebhookEvent,
)
from ..services.accounting import (
    record_booking_capture_entries,
    record_booking_refund_entries,
)
from ..services.marketplace import record_booking_event
from ..services.notification_triggers import notify_booking_status_change
from ..services.payments import PaymentProviderError, construct_webhook_event


webhooks_bp = Blueprint("webhooks", __name__)


def _booking_for_event(event_type, payload_object):
    metadata = payload_object.get("metadata") or {}
    booking_id = metadata.get("booking_id")
    payment_intent = payload_object.get("payment_intent") or payload_object.get("id")
    checkout_session_id = payload_object.get("id") if event_type.startswith("checkout.session.") else None

    booking = None
    if booking_id:
        booking = db.session.get(Booking, int(booking_id))
    if not booking and payment_intent:
        booking = Booking.query.filter_by(payment_intent_id=payment_intent).first()
    if not booking and checkout_session_id:
        booking = Booking.query.filter_by(payment_checkout_session_id=checkout_session_id).first()
    return booking


def _wallet_topup_for_event(payload_object):
    metadata = payload_object.get("metadata") or {}
    topup_reference = metadata.get("topup_reference")
    user_id = metadata.get("user_id")
    checkout_session_id = payload_object.get("id")
    payment_intent = payload_object.get("payment_intent") or payload_object.get("id")

    query = WalletTopup.query
    topup = None
    if topup_reference:
        query = query.filter_by(topup_reference=str(topup_reference))
        if user_id:
            query = query.filter_by(user_id=int(user_id))
        topup = query.first()
    if not topup and checkout_session_id:
        topup = WalletTopup.query.filter_by(gateway_order_id=str(checkout_session_id)).first()
    if not topup and payment_intent:
        topup = WalletTopup.query.filter_by(gateway_payment_id=str(payment_intent)).first()
    return topup


def _mark_confirmed(booking, payment_intent_id, payment_reference):
    booking.payment_provider = "stripe"
    booking.payment_intent_id = payment_intent_id or booking.payment_intent_id
    booking.payment_ref = payment_reference or booking.payment_ref
    booking.payment_status = PaymentStatus.CAPTURED
    record_booking_capture_entries(booking, payment_reference)
    record_booking_event(
        booking,
        "payment_captured",
        payload={"summary": "Payment captured from Stripe webhook"},
    )
    if booking.status == BookingStatus.PENDING:
        booking.status = BookingStatus.CONFIRMED
        record_booking_event(
            booking,
            "confirmed",
            payload={"status": BookingStatus.CONFIRMED.value, "summary": "Booking confirmed by payment webhook"},
        )
        notify_booking_status_change(
            booking=booking,
            new_status="confirmed",
            changed_by_role="system",
        )


def _complete_wallet_topup(topup, payload_object, event_id):
    from ..services.wallet_service import credit, emit_wallet_update

    if topup.status == "COMPLETED":
        db.session.add(WebhookEvent(event_id=event_id, provider="stripe"))
        db.session.commit()
        return "duplicate_topup"

    amount_minor = payload_object.get("amount_total") or payload_object.get("amount")
    amount_major = (
        Decimal(amount_minor or 0) / Decimal("100")
        if amount_minor is not None
        else Decimal(topup.amount or 0)
    )
    payment_intent = payload_object.get("payment_intent") or payload_object.get("id")
    txn = credit(
        user_id=topup.user_id,
        amount=amount_major,
        txn_type=WalletTransactionType.CREDIT_TOPUP,
        description=f"Wallet Top-up (Stripe {payment_intent})",
        reference_type="topup",
        reference_id=topup.id,
    )
    topup.gateway_order_id = str(payload_object.get("id") or topup.gateway_order_id)
    topup.gateway_payment_id = str(payment_intent or topup.gateway_payment_id)
    topup.wallet_transaction_id = txn.id
    topup.status = "COMPLETED"
    topup.completed_at = datetime.now(timezone.utc)
    topup.metadata_json = {
        **(topup.metadata_json or {}),
        "webhook_event_id": event_id,
        "provider": "stripe",
        "captured_amount_minor": int(amount_minor or 0),
    }
    current_app.logger.info(
        "wallet.topup_success",
        extra={
            "provider": "stripe",
            "user_id": topup.user_id,
            "topup_reference": topup.topup_reference,
            "amount": float(amount_major),
        },
    )
    db.session.add(WebhookEvent(event_id=event_id, provider="stripe"))
    db.session.commit()
    emit_wallet_update(topup.user_id)
    return "ok"


@webhooks_bp.route("/webhooks/stripe", methods=["POST"])
@limiter.limit(lambda: current_app.config.get("WEBHOOK_RATE_LIMIT", "120 per minute"))
def stripe_webhook():
    payload = request.get_data()
    signature = request.headers.get("Stripe-Signature")
    secret = current_app.config.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        return jsonify({"error": "stripe webhook secret not configured"}), 500

    try:
        event = construct_webhook_event(payload, signature, secret)
    except PaymentProviderError as exc:
        current_app.logger.error(
            "webhook.signature_invalid",
            extra={"provider": "stripe", "error": str(exc)},
        )
        return jsonify({"error": "invalid signature"}), 400
    except Exception as exc:  # pragma: no cover - third-party parse failures
        current_app.logger.error(
            "webhook.payload_invalid",
            extra={"provider": "stripe", "error": str(exc)},
        )
        return jsonify({"error": "invalid payload"}), 400

    event_id = event["id"]
    if WebhookEvent.query.filter_by(event_id=event_id).first():
        return jsonify({"status": "duplicate"}), 200

    event_type = event["type"]
    payload_object = dict(event["data"]["object"])
    booking = _booking_for_event(event_type, payload_object)
    wallet_topup = _wallet_topup_for_event(payload_object)

    current_app.logger.info(
        "webhook.received",
        extra={"provider": "stripe", "event": event_type, "event_id": event_id},
    )

    try:
        if wallet_topup and event_type in {"checkout.session.completed", "payment_intent.succeeded"}:
            status = _complete_wallet_topup(wallet_topup, payload_object, event_id)
            return jsonify({"status": status}), 200

        if booking:
            if event_type == "checkout.session.completed":
                booking.payment_checkout_session_id = payload_object.get("id") or booking.payment_checkout_session_id
                payment_intent_id = payload_object.get("payment_intent")
                _mark_confirmed(booking, payment_intent_id, payment_intent_id)
            elif event_type == "payment_intent.succeeded":
                payment_intent_id = payload_object.get("id")
                latest_charge = payload_object.get("latest_charge")
                _mark_confirmed(booking, payment_intent_id, latest_charge or payment_intent_id)
            elif event_type == "payment_intent.payment_failed":
                booking.payment_provider = "stripe"
                booking.payment_intent_id = payload_object.get("id") or booking.payment_intent_id
                booking.payment_status = PaymentStatus.NONE
                record_booking_event(
                    booking,
                    "payment_failed",
                    payload={"summary": "Stripe reported a payment failure"},
                )
                current_app.logger.error(
                    "booking.payment_failed",
                    extra={"booking_id": booking.id, "payment_id": booking.payment_intent_id},
                )
            elif event_type in {"charge.refunded", "charge.refund.updated"}:
                booking.payment_provider = "stripe"
                booking.payment_status = PaymentStatus.REFUNDED
                record_booking_refund_entries(booking, payload_object.get("id"))
                record_booking_event(
                    booking,
                    "refunded",
                    payload={"summary": "Payment refunded"},
                )

        db.session.add(WebhookEvent(event_id=event_id, provider="stripe"))
        db.session.commit()
        return jsonify({"status": "ok"}), 200
    except Exception as exc:  # pragma: no cover - operational safety net
        db.session.rollback()
        current_app.logger.exception(
            "webhook.processing_failed",
            extra={"event_id": event_id, "event_type": event_type, "error": str(exc)},
        )
        raise


@webhooks_bp.route("/webhooks/razorpay", methods=["POST"])
def razorpay_webhook():
    payload = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature")
    secret = current_app.config.get("RAZORPAY_WEBHOOK_SECRET")
    
    if not secret:
        current_app.logger.error("razorpay.webhook_secret_missing")
        return jsonify({"error": "not configured"}), 500

    from ..services.payment_service import verify_webhook_signature
    if not verify_webhook_signature(payload, signature, secret):
        current_app.logger.warning("razorpay.signature_invalid")
        return jsonify({"error": "invalid signature"}), 400

    import json
    event = json.loads(payload)
    event_id = event.get("id")
    
    if WebhookEvent.query.filter_by(event_id=event_id).first():
        return jsonify({"status": "duplicate"}), 200

    event_type = event.get("event")
    payload_object = event.get("payload", {}).get("payment", {}).get("entity", {})
    
    current_app.logger.info(f"razorpay.webhook_received: {event_type}")

    try:
        if event_type == "payment.captured":
            notes = payload_object.get("notes") or {}
            user_id = notes.get("user_id")
            topup_id = notes.get("topup_id")
            amount_paise = payload_object.get("amount")
            order_id = payload_object.get("order_id")
            payment_id = payload_object.get("id")
            
            if user_id and topup_id:
                from ..services.wallet_service import credit, emit_wallet_update

                topup = WalletTopup.query.filter_by(
                    topup_reference=str(topup_id),
                    user_id=int(user_id),
                ).first()
                if not topup and order_id:
                    topup = WalletTopup.query.filter_by(
                        gateway_order_id=str(order_id),
                        user_id=int(user_id),
                    ).first()

                if not topup:
                    raise ValueError(f"unknown wallet topup reference: {topup_id}")

                if topup.status == "COMPLETED":
                    db.session.add(WebhookEvent(event_id=event_id, provider="razorpay"))
                    db.session.commit()
                    return jsonify({"status": "duplicate_topup"}), 200

                amount_rs = Decimal(amount_paise) / 100
                txn = credit(
                    user_id=int(user_id),
                    amount=amount_rs,
                    txn_type=WalletTransactionType.CREDIT_TOPUP,
                    description=f"Wallet Top-up (Razorpay {payment_id})",
                    reference_type="topup",
                    reference_id=topup.id,
                )
                topup.gateway_order_id = str(order_id) if order_id else topup.gateway_order_id
                topup.gateway_payment_id = str(payment_id) if payment_id else topup.gateway_payment_id
                topup.wallet_transaction_id = txn.id
                topup.status = "COMPLETED"
                topup.completed_at = datetime.now(timezone.utc)
                topup.metadata_json = {
                    **(topup.metadata_json or {}),
                    "webhook_event_id": event_id,
                    "captured_amount_paise": int(amount_paise or 0),
                }
                current_app.logger.info(f"wallet.topup_success: user={user_id}, amount={amount_rs}")

        db.session.add(WebhookEvent(event_id=event_id, provider="razorpay"))
        db.session.commit()
        if event_type == "payment.captured" and user_id and topup_id:
            emit_wallet_update(int(user_id))
        return jsonify({"status": "ok"}), 200
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(f"razorpay.webhook_processing_failed: {exc}")
        return jsonify({"error": str(exc)}), 500
