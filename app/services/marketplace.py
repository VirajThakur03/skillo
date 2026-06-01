from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import current_app

from ..extensions import db, socketio
from ..models import (
    Booking,
    BookingChangePolicy,
    BookingStatus,
    BookingTimelineEvent,
    Notification,
    NotificationCategory,
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationPreference,
    NotificationPriority,
    ProviderAvailabilityRule,
    ProviderBlackout,
    ProviderInstantBookSetting,
    QuoteRequestStatus,
    RefundStatus,
    User,
)
from ..utils import haversine
from .notification_delivery import send_email, send_push


ACTIVE_BOOKING_STATUSES = {
    BookingStatus.PENDING,
    BookingStatus.CONFIRMED,
    BookingStatus.IN_PROGRESS,
}


@dataclass
class ResolvedChangePolicy:
    free_cancel_until_hours: int = 24
    partial_fee_until_hours: int = 2
    partial_fee_percent: float = 10.0
    partial_fee_min_amount: float = 100.0
    late_fee_percent: float = 25.0
    late_fee_min_amount: float = 250.0
    max_reschedules: int = 2


def utcnow():
    return datetime.now(timezone.utc)


def as_utc_naive(value):
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def get_user_timezone(user):
    timezone_name = (user.timezone or "UTC").strip()
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return ZoneInfo("UTC")


def compute_provider_badges(user):
    badges = set(user.badges or [])
    if user.is_verified:
        badges.add("identity_verified")
    if user.verification_status.value in {"face_verified", "completed"}:
        badges.add("skill_verified")
    if (user.completed_jobs or 0) >= 10 and (user.rating or 0) >= 4.8:
        badges.add("top_rated")
    return sorted(badges)


def get_or_create_instant_book_setting(provider_id):
    setting = ProviderInstantBookSetting.query.filter_by(provider_id=provider_id).first()
    if not setting:
        setting = ProviderInstantBookSetting(provider_id=provider_id)
        db.session.add(setting)
        db.session.flush()
    return setting


def get_or_create_notification_preference(user_id):
    preference = NotificationPreference.query.filter_by(user_id=user_id).first()
    if not preference:
        preference = NotificationPreference(
            user_id=user_id,
            category_channels={
                NotificationCategory.BOOKING_UPDATE.value: ["in_app", "push", "email"],
                NotificationCategory.QUOTE_UPDATE.value: ["in_app", "push"],
                NotificationCategory.PAYMENT_UPDATE.value: ["in_app", "push", "email"],
                NotificationCategory.CHAT_MENTION.value: ["in_app", "push"],
                NotificationCategory.PROMOTION.value: ["in_app"],
            },
        )
        db.session.add(preference)
        db.session.flush()
    return preference


def create_notification(
    *,
    recipient_id,
    category,
    title,
    body,
    priority=NotificationPriority.NORMAL,
    deep_link=None,
    entity_type=None,
    entity_id=None,
    template_key="generic",
):
    recipient = db.session.get(User, recipient_id)
    notification = Notification(
        recipient_user_id=recipient_id,
        category=category,
        priority=priority,
        title=title,
        body=body,
        deep_link=deep_link,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.session.add(notification)
    db.session.flush()

    live_emit_status = "delivered"
    try:
        socketio.emit("notification", {
            "id": notification.id,
            "category": category.value,
            "title": title,
            "body": body,
            "deep_link": deep_link,
            "created_at": notification.created_at.isoformat() if hasattr(notification, 'created_at') and notification.created_at else datetime.now(timezone.utc).isoformat()
        }, to=f"user_{recipient_id}")
    except Exception as e:
        live_emit_status = "failed"
        current_app.logger.info(
            "notification.socket_emit_failed",
            extra={
                "recipient_id": recipient_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "environment": current_app.config.get("ENV", "development"),
                "error_type": e.__class__.__name__,
                "error": str(e),
            },
        )
    else:
        current_app.logger.debug(
            "notification.socket_emit_attempted",
            extra={
                "recipient_id": recipient_id,
                "notification_id": notification.id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "live_emit_status": live_emit_status,
            },
        )

    preference = get_or_create_notification_preference(recipient_id)
    configured_channels = set(
        preference.category_channels.get(category.value, ["in_app"])
        if preference.category_channels
        else ["in_app"]
    )
    configured_channels.add("in_app")

    for channel_name, enabled in (
        ("push", preference.push_enabled),
        ("email", preference.email_enabled),
        ("whatsapp", preference.whatsapp_enabled),
        ("in_app", True),
    ):
        if channel_name != "in_app" and not enabled:
            continue
        if channel_name not in configured_channels:
            continue

        delivery = NotificationDelivery(
            notification_id=notification.id,
            channel=NotificationChannel[channel_name.upper()],
            status=NotificationDeliveryStatus.DELIVERED
            if channel_name == "in_app"
            else NotificationDeliveryStatus.QUEUED,
            template_key=template_key,
            attempted_at=utcnow(),
            delivered_at=utcnow() if channel_name == "in_app" else None,
            payload={},
        )
        if channel_name == "push" and recipient:
            outcome = send_push(
                recipient,
                title,
                body,
                data={"deep_link": deep_link, "entity_type": entity_type, "entity_id": entity_id},
            )
            delivery.status = NotificationDeliveryStatus[outcome.get("status", "skipped").upper()]
            delivery.error_code = outcome.get("error_code")
            delivery.error_message = outcome.get("error_message")
            delivery.payload = outcome.get("payload") or {}
            delivery.delivered_at = utcnow() if delivery.status == NotificationDeliveryStatus.DELIVERED else None
        elif channel_name == "email" and recipient:
            outcome = send_email(recipient, title, body)
            delivery.status = NotificationDeliveryStatus[outcome.get("status", "skipped").upper()]
            delivery.error_code = outcome.get("error_code")
            delivery.error_message = outcome.get("error_message")
            delivery.payload = outcome.get("payload") or {}
            delivery.delivered_at = utcnow() if delivery.status == NotificationDeliveryStatus.DELIVERED else None
        db.session.add(delivery)

    return notification


def record_booking_event(booking, event_type, actor_user_id=None, payload=None):
    event = BookingTimelineEvent(
        booking_id=booking.id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        payload=payload or {},
    )
    db.session.add(event)
    return event


def resolve_change_policy(provider_id=None):
    policy = None
    if provider_id is not None:
        policy = BookingChangePolicy.query.filter_by(provider_id=provider_id, active=True).first()
    if not policy:
        return ResolvedChangePolicy()
    return ResolvedChangePolicy(
        free_cancel_until_hours=policy.free_cancel_until_hours,
        partial_fee_until_hours=policy.partial_fee_until_hours,
        partial_fee_percent=float(policy.partial_fee_percent or 10),
        partial_fee_min_amount=float(policy.partial_fee_min_amount or 100),
        late_fee_percent=float(policy.late_fee_percent or 25),
        late_fee_min_amount=float(policy.late_fee_min_amount or 250),
        max_reschedules=policy.max_reschedules,
    )


def preview_cancellation(booking, actor_user_id=None):
    policy = resolve_change_policy(booking.provider_id)
    now = utcnow()
    delta_hours = max((booking.scheduled_at - now).total_seconds() / 3600.0, 0)
    promo_discount = float(getattr(booking, "promo_discount_amount", 0) or 0)
    price = max(float(booking.price or 0) - promo_discount, 0.0)
    fee = 0.0
    goodwill_credit = 0.0

    if actor_user_id == booking.provider_id:
        goodwill_credit = 100.0
    elif delta_hours > policy.free_cancel_until_hours:
        fee = 0.0
    elif delta_hours > policy.partial_fee_until_hours:
        fee = max(price * (policy.partial_fee_percent / 100.0), policy.partial_fee_min_amount)
    else:
        fee = max(price * (policy.late_fee_percent / 100.0), policy.late_fee_min_amount)

    fee = min(fee, price)
    refund_amount = max(price - fee, 0.0)
    return {
        "fee_amount": round(fee, 2),
        "refund_amount": round(refund_amount, 2),
        "goodwill_credit_amount": round(goodwill_credit, 2),
        "policy_label": (
            "provider initiated cancellation"
            if actor_user_id == booking.provider_id
            else "free cancellation"
            if fee == 0
            else "partial cancellation fee"
        ),
        "lock_reason": None,
        "reschedule_allowed": booking.status in {BookingStatus.PENDING, BookingStatus.CONFIRMED},
        "cancel_allowed": booking.status not in {BookingStatus.COMPLETED, BookingStatus.CANCELLED, BookingStatus.DECLINED},
    }


def _booking_overlap(existing_start, existing_duration, new_start, new_duration):
    existing_end = existing_start + timedelta(minutes=existing_duration)
    new_end = new_start + timedelta(minutes=new_duration)
    return existing_start < new_end and new_start < existing_end


def provider_is_available(provider_id, scheduled_dt, duration_minutes=60, skill_id=None, exclude_booking_id=None):
    scheduled_dt = as_utc_naive(scheduled_dt)
    provider = db.session.get(User, provider_id)
    if not provider:
        return False, "provider not found"

    start_utc = scheduled_dt
    end_utc = start_utc + timedelta(minutes=duration_minutes)

    blackout = (
        ProviderBlackout.query.filter(
            ProviderBlackout.provider_id == provider_id,
            ProviderBlackout.deleted_at.is_(None),
            ProviderBlackout.start_at < end_utc,
            ProviderBlackout.end_at > start_utc,
        )
        .order_by(ProviderBlackout.start_at.asc())
        .first()
    )
    if blackout:
        return False, "provider is unavailable for the selected time"

    booking_query = Booking.query.filter(
        Booking.provider_id == provider_id,
        Booking.status.in_(list(ACTIVE_BOOKING_STATUSES)),
    )
    if exclude_booking_id is not None:
        booking_query = booking_query.filter(Booking.id != exclude_booking_id)

    for booking in booking_query.all():
        if _booking_overlap(booking.scheduled_at, booking.duration_minutes or 60, start_utc, duration_minutes):
            return False, "provider already has a booking in that time range"

    rules_query = ProviderAvailabilityRule.query.filter(
        ProviderAvailabilityRule.provider_id == provider_id,
        ProviderAvailabilityRule.deleted_at.is_(None),
        ProviderAvailabilityRule.enabled.is_(True),
    )
    if skill_id is not None:
        rules = rules_query.filter(
            (ProviderAvailabilityRule.skill_id == None) | (ProviderAvailabilityRule.skill_id == skill_id)
        ).all()
    else:
        rules = rules_query.all()

    if not rules:
        return True, None

    provider_tz = get_user_timezone(provider)
    local_start = start_utc.replace(tzinfo=timezone.utc).astimezone(provider_tz)
    local_end = end_utc.replace(tzinfo=timezone.utc).astimezone(provider_tz)

    for rule in rules:
        if rule.weekday != local_start.weekday():
            continue
        start_minutes = local_start.hour * 60 + local_start.minute
        end_minutes = local_end.hour * 60 + local_end.minute
        rule_start = rule.start_minute_local
        rule_end = rule.end_minute_local
        buffered_start = start_minutes - (rule.buffer_before_minutes or 0)
        buffered_end = end_minutes + (rule.buffer_after_minutes or 0)
        notice_cutoff = utcnow() + timedelta(minutes=rule.min_notice_minutes or 0)
        max_advance_cutoff = utcnow() + timedelta(days=rule.max_advance_days or 30)

        if start_utc < notice_cutoff:
            continue
        if start_utc > max_advance_cutoff:
            continue
        if local_start.date() != local_end.date():
            continue
        if buffered_start >= rule_start and buffered_end <= rule_end:
            return True, None

    return False, "scheduled_at is not available for this provider"


def _slot_from_rule(day, rule, provider_tz, duration_minutes):
    local_start = datetime.combine(day, time.min, tzinfo=provider_tz) + timedelta(minutes=rule.start_minute_local)
    local_end = datetime.combine(day, time.min, tzinfo=provider_tz) + timedelta(minutes=rule.end_minute_local)
    current = local_start
    slots = []
    while current + timedelta(minutes=duration_minutes) <= local_end:
        slots.append(current.astimezone(timezone.utc).replace(tzinfo=None))
        current += timedelta(minutes=duration_minutes)
    return slots


def list_provider_slots(provider_id, *, start_on=None, days=14, skill_id=None):
    provider = db.session.get(User, provider_id)
    if not provider:
        return {"provider_id": provider_id, "slots": [], "open_now": False, "next_available_at": None}

    provider_tz = get_user_timezone(provider)
    start_on = start_on or date.today()
    setting = get_or_create_instant_book_setting(provider_id)
    duration_minutes = setting.slot_duration_minutes or 60

    rules_query = ProviderAvailabilityRule.query.filter(
        ProviderAvailabilityRule.provider_id == provider_id,
        ProviderAvailabilityRule.deleted_at.is_(None),
        ProviderAvailabilityRule.enabled.is_(True),
    )
    if skill_id is not None:
        rules = rules_query.filter(
            (ProviderAvailabilityRule.skill_id == None) | (ProviderAvailabilityRule.skill_id == skill_id)
        ).all()
    else:
        rules = rules_query.all()

    slots = []
    if not rules:
        baseline = as_utc_naive(datetime.now(timezone.utc)) + timedelta(hours=1)
        for offset in range(days):
            day = start_on + timedelta(days=offset)
            for hour in range(9, 18):
                slot_start = datetime.combine(day, time(hour=hour))
                slot_start = slot_start.replace(tzinfo=provider_tz).astimezone(timezone.utc).replace(tzinfo=None)
                if slot_start >= baseline:
                    available, _ = provider_is_available(provider_id, slot_start, duration_minutes, skill_id=skill_id)
                    if available:
                        slots.append(slot_start)
    else:
        for offset in range(days):
            day = start_on + timedelta(days=offset)
            for rule in rules:
                if rule.weekday != day.weekday():
                    continue
                for slot_start in _slot_from_rule(day, rule, provider_tz, duration_minutes):
                    available, _ = provider_is_available(provider_id, slot_start, duration_minutes, skill_id=skill_id)
                    if available:
                        slots.append(slot_start)

    slots = sorted(slots)
    now_available, _ = provider_is_available(provider_id, utcnow(), max(duration_minutes, 30), skill_id=skill_id)
    next_available = (
        slots[0].replace(tzinfo=timezone.utc).isoformat()
        if slots
        else None
    )
    return {
        "provider_id": provider_id,
        "timezone": provider.timezone,
        "open_now": now_available,
        "next_available_at": next_available,
        "slots": [
            {
                "start_at": slot.replace(tzinfo=timezone.utc).isoformat(),
                "end_at": (
                    slot + timedelta(minutes=duration_minutes)
                ).replace(tzinfo=timezone.utc).isoformat(),
                "instant_book": setting.instant_book_enabled,
            }
            for slot in slots
        ],
    }


def compute_booking_eta(booking):
    if not booking.worker_latitude or not booking.worker_longitude:
        return None
    if not booking.seeker or booking.seeker.latitude is None or booking.seeker.longitude is None:
        return None

    distance = haversine(
        booking.worker_latitude,
        booking.worker_longitude,
        booking.seeker.latitude,
        booking.seeker.longitude,
    )
    booking.distance_km = distance
    eta_minutes = max(int((distance / 25.0) * 60), 1)
    booking.eta_minutes = eta_minutes
    return eta_minutes


def close_quote_request_if_needed(quote_request):
    active_quotes = [quote for quote in quote_request.quotes if quote.status.value == "ACTIVE"]
    if not active_quotes and quote_request.status == QuoteRequestStatus.OPEN:
        quote_request.status = QuoteRequestStatus.WAITING_FOR_SEEKER


def is_admin_user(user):
    return bool(user and user.is_admin)
