from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from ..extensions import db
from ..models import (
    Booking,
    BookingStatus,
    NotificationCategory,
    PaymentStatus,
    ProviderQuote,
    ProviderQuoteStatus,
    QuoteMessage,
    QuoteMessageType,
    QuoteRequest,
    QuoteRequestProviderTarget,
    QuoteRequestStatus,
    QuoteTargetStatus,
    RefundStatus,
    RoleEnum,
    Skill,
    User,
)
from ..services.marketplace import (
    create_notification,
    list_provider_slots,
    provider_is_available,
)

quotes_bp = Blueprint("quotes", __name__, url_prefix="/api/quote-requests")


def _current_user():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return None, ({"error": "user not found"}, 404)
    return user, None


def _serialize_quote_request(item):
    return {
        "id": item.id,
        "seeker_id": item.seeker_id,
        "skill_id": item.skill_id,
        "service_title": item.service_title,
        "description": item.description,
        "address_text": item.address_text,
        "preferred_window_start": (
            item.preferred_window_start.isoformat()
            if item.preferred_window_start
            else None
        ),
        "preferred_window_end": (
            item.preferred_window_end.isoformat()
            if item.preferred_window_end
            else None
        ),
        "budget_min": float(item.budget_min or 0) if item.budget_min is not None else None,
        "budget_max": float(item.budget_max or 0) if item.budget_max is not None else None,
        "attachments": item.attachments or [],
        "status": item.status.value,
        "accepted_provider_quote_id": item.accepted_provider_quote_id,
        "created_at": item.created_at.isoformat(),
    }


def _serialize_provider_quote(item):
    return {
        "id": item.id,
        "provider_id": item.provider_id,
        "revision_number": item.revision_number,
        "currency": item.currency,
        "total_amount": float(item.total_amount or 0),
        "line_items": item.line_items or [],
        "estimated_duration_minutes": item.estimated_duration_minutes,
        "earliest_available_at": (
            item.earliest_available_at.isoformat()
            if item.earliest_available_at
            else None
        ),
        "note": item.note,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "status": item.status.value,
    }


def _parse_datetime(raw_value, field_name):
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(raw_value)
    except Exception:
        raise ValueError(f"{field_name} must be a valid ISO datetime")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _can_view_quote_request(user, quote_request):
    if user.role == RoleEnum.SEEKER and quote_request.seeker_id == user.id:
        return True
    if user.role == RoleEnum.PROVIDER:
        return QuoteRequestProviderTarget.query.filter_by(
            quote_request_id=quote_request.id,
            provider_id=user.id,
        ).first() is not None
    return False


@quotes_bp.route("", methods=["POST"])
@jwt_required()
def create_quote_request():
    user, error = _current_user()
    if error:
        return error
    if user.role != RoleEnum.SEEKER:
        return {"error": "only seekers can create quote requests"}, 403

    data = request.get_json() or {}
    provider_ids = data.get("provider_ids") or []
    if not provider_ids or len(provider_ids) > 3:
        return {"error": "provider_ids must include between 1 and 3 providers"}, 400

    try:
        skill = db.session.get(Skill, data.get("skill_id")) if data.get("skill_id") else None
        preferred_window_start = _parse_datetime(
            data.get("preferred_window_start"),
            "preferred_window_start",
        )
        preferred_window_end = _parse_datetime(
            data.get("preferred_window_end"),
            "preferred_window_end",
        )
    except ValueError as exc:
        return {"error": str(exc)}, 400

    service_title = (data.get("service_title") or (skill.title if skill else "")).strip()
    description = (data.get("description") or "").strip()
    if not service_title or not description:
        return {"error": "service_title and description are required"}, 400

    try:
        budget_min = Decimal(str(data["budget_min"])) if data.get("budget_min") is not None else None
        budget_max = Decimal(str(data["budget_max"])) if data.get("budget_max") is not None else None
    except Exception:
        return {"error": "budget_min and budget_max must be numeric"}, 400

    quote_request = QuoteRequest(
        seeker_id=user.id,
        skill_id=skill.id if skill else None,
        service_title=service_title,
        description=description,
        address_text=data.get("address_text") or user.location,
        preferred_window_start=preferred_window_start,
        preferred_window_end=preferred_window_end,
        budget_min=budget_min,
        budget_max=budget_max,
        attachments=data.get("attachments") or [],
        status=QuoteRequestStatus.OPEN,
    )
    db.session.add(quote_request)
    db.session.flush()

    for raw_provider_id in provider_ids:
        try:
            provider_id = int(raw_provider_id)
        except (TypeError, ValueError):
            db.session.rollback()
            return {"error": "provider_ids must contain integers"}, 400
        provider = db.session.get(User, provider_id)
        if not provider or provider.role != RoleEnum.PROVIDER:
            db.session.rollback()
            return {"error": f"provider {provider_id} is invalid"}, 400
        target = QuoteRequestProviderTarget(
            quote_request_id=quote_request.id,
            provider_id=provider_id,
            target_status=QuoteTargetStatus.PENDING_RESPONSE,
            first_notified_at=datetime.now(timezone.utc),
            response_due_at=datetime.now(timezone.utc) + timedelta(hours=12),
        )
        db.session.add(target)
        create_notification(
            recipient_id=provider_id,
            category=NotificationCategory.QUOTE_UPDATE,
            title="New quote request",
            body=f"{user.name} requested a quote for {service_title}.",
            entity_type="quote_request",
            entity_id=quote_request.id,
            deep_link=f"/quotes/{quote_request.id}",
            template_key="quote_request.created",
        )

    db.session.commit()
    return _serialize_quote_request(quote_request), 201


@quotes_bp.route("", methods=["GET"])
@jwt_required()
def list_quote_requests():
    user, error = _current_user()
    if error:
        return error

    if user.role == RoleEnum.SEEKER:
        items = (
            QuoteRequest.query.filter_by(seeker_id=user.id, deleted_at=None)
            .order_by(QuoteRequest.created_at.desc())
            .all()
        )
    else:
        items = (
            QuoteRequest.query.join(
                QuoteRequestProviderTarget,
                QuoteRequestProviderTarget.quote_request_id == QuoteRequest.id,
            )
            .filter(
                QuoteRequestProviderTarget.provider_id == user.id,
                QuoteRequest.deleted_at.is_(None),
            )
            .order_by(QuoteRequest.created_at.desc())
            .all()
        )

    return {"items": [_serialize_quote_request(item) for item in items]}, 200


@quotes_bp.route("/<int:quote_request_id>", methods=["GET"])
@jwt_required()
def get_quote_request(quote_request_id):
    user, error = _current_user()
    if error:
        return error

    quote_request = db.session.get(QuoteRequest, quote_request_id)
    if not quote_request or quote_request.deleted_at is not None:
        return {"error": "quote request not found"}, 404
    if not _can_view_quote_request(user, quote_request):
        return {"error": "forbidden"}, 403

    return {
        "quote_request": _serialize_quote_request(quote_request),
        "targets": [
            {
                "provider_id": target.provider_id,
                "target_status": target.target_status.value,
                "response_due_at": (
                    target.response_due_at.isoformat()
                    if target.response_due_at
                    else None
                ),
            }
            for target in quote_request.targets
        ],
        "quotes": [_serialize_provider_quote(item) for item in quote_request.quotes],
        "messages": [
            {
                "id": message.id,
                "sender_id": message.sender_id,
                "message_type": message.message_type.value,
                "body": message.body,
                "attachments": message.attachments or [],
                "created_at": message.created_at.isoformat(),
            }
            for message in quote_request.messages
        ],
    }, 200


@quotes_bp.route("/<int:quote_request_id>/provider-responses", methods=["POST"])
@jwt_required()
def provider_quote_response(quote_request_id):
    user, error = _current_user()
    if error:
        return error
    if user.role != RoleEnum.PROVIDER:
        return {"error": "only providers can respond"}, 403

    quote_request = db.session.get(QuoteRequest, quote_request_id)
    if not quote_request or quote_request.deleted_at is not None:
        return {"error": "quote request not found"}, 404

    target = QuoteRequestProviderTarget.query.filter_by(
        quote_request_id=quote_request.id,
        provider_id=user.id,
    ).first()
    if not target:
        return {"error": "provider is not targeted for this request"}, 403

    data = request.get_json() or {}
    response_type = (data.get("response_type") or "").strip().upper()
    if response_type == "DECLINED":
        target.target_status = QuoteTargetStatus.DECLINED
        db.session.commit()
        return {"success": True, "target_status": target.target_status.value}, 200

    if response_type == "NEEDS_INFO":
        target.target_status = QuoteTargetStatus.NEEDS_INFO
        message = QuoteMessage(
            quote_request_id=quote_request.id,
            sender_id=user.id,
            message_type=QuoteMessageType.PROVIDER_REPLY,
            body=(data.get("body") or "Please share more details for an accurate quote.").strip(),
            attachments=data.get("attachments") or [],
        )
        db.session.add(message)
        create_notification(
            recipient_id=quote_request.seeker_id,
            category=NotificationCategory.QUOTE_UPDATE,
            title="Provider needs more information",
            body=f"{user.name} requested more details for your quote request.",
            entity_type="quote_request",
            entity_id=quote_request.id,
            deep_link=f"/quotes/{quote_request.id}",
            template_key="quote_request.needs_info",
        )
        db.session.commit()
        return {"success": True, "target_status": target.target_status.value}, 200

    if response_type != "QUOTE_SENT":
        return {"error": "response_type must be QUOTE_SENT, NEEDS_INFO or DECLINED"}, 400

    total_amount = data.get("total_amount")
    estimated_duration_minutes = data.get("estimated_duration_minutes")
    try:
        total_amount = Decimal(str(total_amount))
        estimated_duration_minutes = int(estimated_duration_minutes)
    except (ArithmeticError, TypeError, ValueError):
        return {"error": "total_amount must be numeric and estimated_duration_minutes must be an integer"}, 400

    try:
        expires_at = _parse_datetime(data.get("expires_at"), "expires_at") or (
            datetime.now(timezone.utc) + timedelta(days=1)
        )
        earliest_available_at = _parse_datetime(
            data.get("earliest_available_at"),
            "earliest_available_at",
        )
    except ValueError as exc:
        return {"error": str(exc)}, 400

    if earliest_available_at:
        available, availability_error = provider_is_available(
            user.id,
            earliest_available_at,
            estimated_duration_minutes,
            skill_id=quote_request.skill_id,
        )
        if not available:
            return {"error": availability_error or "quoted time is not available"}, 409

    quote = ProviderQuote(
        quote_request_id=quote_request.id,
        provider_id=user.id,
        revision_number=(
            ProviderQuote.query.filter_by(
                quote_request_id=quote_request.id,
                provider_id=user.id,
            ).count()
            + 1
        ),
        currency=data.get("currency") or "INR",
        total_amount=total_amount,
        line_items=data.get("line_items") or [],
        estimated_duration_minutes=estimated_duration_minutes,
        earliest_available_at=earliest_available_at,
        note=data.get("note"),
        expires_at=expires_at,
        status=ProviderQuoteStatus.ACTIVE,
    )
    db.session.add(quote)
    target.target_status = QuoteTargetStatus.QUOTE_SENT
    quote_request.status = QuoteRequestStatus.WAITING_FOR_SEEKER
    create_notification(
        recipient_id=quote_request.seeker_id,
        category=NotificationCategory.QUOTE_UPDATE,
        title="New quote received",
        body=f"{user.name} sent a quote for {quote_request.service_title}.",
        entity_type="quote_request",
        entity_id=quote_request.id,
        deep_link=f"/quotes/{quote_request.id}",
        template_key="quote_request.quote_sent",
    )
    db.session.commit()
    return _serialize_provider_quote(quote), 201


@quotes_bp.route("/<int:quote_request_id>/messages", methods=["POST"])
@jwt_required()
def quote_messages(quote_request_id):
    user, error = _current_user()
    if error:
        return error
    quote_request = db.session.get(QuoteRequest, quote_request_id)
    if not quote_request or quote_request.deleted_at is not None:
        return {"error": "quote request not found"}, 404
    if not _can_view_quote_request(user, quote_request):
        return {"error": "forbidden"}, 403

    data = request.get_json() or {}
    body = (data.get("body") or "").strip()
    if not body:
        return {"error": "body is required"}, 400

    message_type = (
        QuoteMessageType.SEEKER_REPLY
        if user.role == RoleEnum.SEEKER
        else QuoteMessageType.PROVIDER_REPLY
    )
    message = QuoteMessage(
        quote_request_id=quote_request.id,
        sender_id=user.id,
        message_type=message_type,
        body=body,
        attachments=data.get("attachments") or [],
    )
    db.session.add(message)
    db.session.commit()
    return {"success": True, "message_id": message.id}, 201


@quotes_bp.route("/<int:quote_request_id>/accept", methods=["POST"])
@jwt_required()
def accept_quote(quote_request_id):
    user, error = _current_user()
    if error:
        return error
    if user.role != RoleEnum.SEEKER:
        return {"error": "only seekers can accept quotes"}, 403

    quote_request = db.session.get(QuoteRequest, quote_request_id)
    if not quote_request or quote_request.deleted_at is not None:
        return {"error": "quote request not found"}, 404
    if quote_request.seeker_id != user.id:
        return {"error": "forbidden"}, 403

    data = request.get_json() or {}
    provider_quote = ProviderQuote.query.filter_by(
        id=data.get("provider_quote_id"),
        quote_request_id=quote_request.id,
    ).first()
    if not provider_quote:
        return {"error": "provider quote not found"}, 404
    if provider_quote.status != ProviderQuoteStatus.ACTIVE:
        return {"error": "quote is no longer active"}, 409
    if provider_quote.expires_at and provider_quote.expires_at < datetime.now(timezone.utc):
        provider_quote.status = ProviderQuoteStatus.EXPIRED
        db.session.commit()
        return {"error": "This quote has expired. Request a new quote."}, 409

    scheduled_at = (
        provider_quote.earliest_available_at
        or quote_request.preferred_window_start
        or (datetime.now(timezone.utc) + timedelta(days=1))
    )
    available, availability_error = provider_is_available(
        provider_quote.provider_id,
        scheduled_at,
        provider_quote.estimated_duration_minutes,
        skill_id=quote_request.skill_id,
    )
    if not available:
        replacement = list_provider_slots(
            provider_quote.provider_id,
            days=14,
            skill_id=quote_request.skill_id,
        )
        replacement_slots = replacement.get("slots") or []
        if not replacement_slots:
            return {"error": availability_error or "provider is no longer available"}, 409
        scheduled_at = datetime.fromisoformat(replacement_slots[0]["start_at"])

    skill = quote_request.skill or Skill.query.filter_by(provider_id=provider_quote.provider_id, is_active=True).first()
    if not skill:
        return {"error": "provider has no active skill to attach to the booking"}, 409

    from app.services.booking_service import calculate_booking_fees
    fees = calculate_booking_fees(
        provider_quote.total_amount,
        provider_quote.total_amount,
        provider=provider_quote.provider_id,
        seeker=user,
    )

    booking = Booking(
        seeker_id=user.id,
        provider_id=provider_quote.provider_id,
        skill_id=skill.id,
        quote_request_id=quote_request.id,
        scheduled_at=scheduled_at,
        original_scheduled_at=scheduled_at,
        duration_minutes=provider_quote.estimated_duration_minutes,
        price=provider_quote.total_amount,
        currency=provider_quote.currency or "INR",
        status=BookingStatus.PENDING,
        payment_status=PaymentStatus.NONE,
        refund_status=RefundStatus.NONE,
        platform_fee_pct=fees["platform_fee_pct"],
        platform_fee_amount=fees["platform_fee_amount"],
        gst_amount=fees["gst_amount"],
        cgst_amount=fees["cgst_amount"],
        sgst_amount=fees["sgst_amount"],
        igst_amount=fees["igst_amount"],
        sac_code=current_app.config.get("PLATFORM_SAC_CODE", "998599"),
        service_amount=fees["service_amount"],
        worker_earnings=fees["worker_earnings"],
        amount_payable=provider_quote.total_amount,
    )
    db.session.add(booking)
    db.session.flush()

    quote_request.accepted_provider_quote_id = provider_quote.id
    quote_request.status = QuoteRequestStatus.BOOKED
    provider_quote.status = ProviderQuoteStatus.ACCEPTED
    for quote in quote_request.quotes:
        if quote.id != provider_quote.id and quote.status == ProviderQuoteStatus.ACTIVE:
            quote.status = ProviderQuoteStatus.SUPERSEDED
    for target in quote_request.targets:
        if target.provider_id == provider_quote.provider_id:
            target.target_status = QuoteTargetStatus.QUOTE_SENT
        else:
            target.target_status = QuoteTargetStatus.CLOSED_OTHER_ACCEPTED

    create_notification(
        recipient_id=provider_quote.provider_id,
        category=NotificationCategory.QUOTE_UPDATE,
        title="Quote accepted",
        body=f"Your quote for {quote_request.service_title} was accepted.",
        entity_type="booking",
        entity_id=booking.id,
        deep_link=f"/provider/dashboard?booking_id={booking.id}",
        template_key="quote_request.accepted",
    )
    db.session.commit()
    return {
        "quote_request_id": quote_request.id,
        "provider_quote_id": provider_quote.id,
        "booking_id": booking.id,
        "booking_status": booking.status.value,
        "message": "Quote accepted. Complete payment to confirm your booking.",
    }, 200


@quotes_bp.route("/<int:quote_request_id>/cancel", methods=["POST"])
@jwt_required()
def cancel_quote_request(quote_request_id):
    user, error = _current_user()
    if error:
        return error
    quote_request = db.session.get(QuoteRequest, quote_request_id)
    if not quote_request or quote_request.deleted_at is not None:
        return {"error": "quote request not found"}, 404
    if quote_request.seeker_id != user.id:
        return {"error": "forbidden"}, 403

    quote_request.status = QuoteRequestStatus.CANCELLED
    for target in quote_request.targets:
        if target.target_status in {
            QuoteTargetStatus.PENDING_RESPONSE,
            QuoteTargetStatus.NEEDS_INFO,
            QuoteTargetStatus.QUOTE_SENT,
        }:
            target.target_status = QuoteTargetStatus.EXPIRED
    db.session.commit()
    return {"success": True, "status": quote_request.status.value}, 200
