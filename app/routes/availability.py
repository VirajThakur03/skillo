from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from ..extensions import db
from ..models import ProviderAvailabilityRule, ProviderBlackout, RoleEnum, User
from ..services.marketplace import (
    get_or_create_instant_book_setting,
    get_user_timezone,
    list_provider_slots,
    provider_is_available,
)

availability_bp = Blueprint("availability", __name__, url_prefix="/api/availability")


DAY_START_MINUTES = 9 * 60
DAY_END_MINUTES = 18 * 60


def _parse_timezone_name(raw_value, fallback="UTC"):
    timezone_name = (raw_value or fallback or "UTC").strip() or "UTC"
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return None
    return timezone_name


def _minutes_to_clock(total_minutes):
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def _clock_to_minutes(value):
    try:
        hours_text, minutes_text = str(value).split(":", 1)
        hours = int(hours_text)
        minutes = int(minutes_text)
    except (AttributeError, TypeError, ValueError):
        raise ValueError("time must be in HH:MM format")
    total = (hours * 60) + minutes
    if total < 0 or total > 24 * 60:
        raise ValueError("time must be in HH:MM format")
    return total


def _serialize_rule(rule):
    return {
        "id": rule.id,
        "skill_id": rule.skill_id,
        "weekday": rule.weekday,
        "day_of_week": rule.weekday,
        "start_minute_local": rule.start_minute_local,
        "end_minute_local": rule.end_minute_local,
        "start_time": _minutes_to_clock(rule.start_minute_local),
        "end_time": _minutes_to_clock(rule.end_minute_local),
        "slot_duration": None,
        "buffer_before_minutes": rule.buffer_before_minutes,
        "buffer_after_minutes": rule.buffer_after_minutes,
        "min_notice_minutes": rule.min_notice_minutes,
        "max_advance_days": rule.max_advance_days,
        "enabled": rule.enabled,
        "is_active": rule.enabled,
    }


def _serialize_blackout(blackout):
    return {
        "id": blackout.id,
        "date": blackout.start_at.date().isoformat(),
        "start_at": blackout.start_at.isoformat(),
        "end_at": blackout.end_at.isoformat(),
        "reason": blackout.note or blackout.reason_code,
        "reason_code": blackout.reason_code,
        "note": blackout.note,
    }


def _provider_settings_payload(provider):
    setting = get_or_create_instant_book_setting(provider.id)
    rules = ProviderAvailabilityRule.query.filter_by(
        provider_id=provider.id,
        deleted_at=None,
    ).order_by(ProviderAvailabilityRule.weekday.asc(), ProviderAvailabilityRule.start_minute_local.asc()).all()
    blackout_cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    blackouts = ProviderBlackout.query.filter(
        ProviderBlackout.provider_id == provider.id,
        ProviderBlackout.deleted_at.is_(None),
        ProviderBlackout.end_at >= blackout_cutoff,
    ).order_by(ProviderBlackout.start_at.asc()).all()
    return {
        "timezone": provider.timezone,
        "rules": [_serialize_rule(rule) for rule in rules],
        "blackouts": [_serialize_blackout(blackout) for blackout in blackouts],
        "instant_book": {
            "instant_book_enabled": setting.instant_book_enabled,
            "slot_duration_minutes": setting.slot_duration_minutes,
            "slot_hold_minutes": setting.slot_hold_minutes,
            "enabled_skill_ids": setting.enabled_skill_ids or [],
        },
    }


def _normalize_rules_payload(rules_payload):
    normalized = []
    for item in rules_payload:
        day_of_week = item.get("day_of_week", item.get("weekday"))
        if day_of_week is None:
            raise ValueError("day_of_week is required")
        weekday = int(day_of_week)
        if weekday < 0 or weekday > 6:
            raise ValueError("day_of_week must be between 0 and 6")

        if item.get("start_time") is not None or item.get("end_time") is not None:
            start_minute = _clock_to_minutes(item.get("start_time"))
            end_minute = _clock_to_minutes(item.get("end_time"))
        else:
            start_minute = int(item.get("start_minute_local"))
            end_minute = int(item.get("end_minute_local"))

        if start_minute < 0 or end_minute > 24 * 60 or start_minute >= end_minute:
            raise ValueError("invalid time range for weekly rule")

        normalized.append(
            {
                "skill_id": item.get("skill_id"),
                "weekday": weekday,
                "start_minute_local": start_minute,
                "end_minute_local": end_minute,
                "buffer_before_minutes": int(item.get("buffer_before_minutes") or 0),
                "buffer_after_minutes": int(item.get("buffer_after_minutes") or 0),
                "min_notice_minutes": int(item.get("min_notice_minutes") or 60),
                "max_advance_days": int(item.get("max_advance_days") or 30),
                "enabled": bool(item.get("is_active", item.get("enabled", True))),
            }
        )
    return normalized


def _provider_user():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return None, ({"error": "unauthenticated"}, 401)
    if user.role != RoleEnum.PROVIDER:
        return None, ({"error": "only providers allowed"}, 403)
    return user, None


@availability_bp.route("/providers/<int:provider_id>", methods=["GET"])
def public_provider_availability(provider_id):
    provider = db.session.get(User, provider_id)
    if not provider or provider.role != RoleEnum.PROVIDER:
        return {"error": "provider not found"}, 404

    week_start_raw = request.args.get("week_start")
    days = request.args.get("days", type=int) or 14
    skill_id = request.args.get("skill_id", type=int)
    if week_start_raw:
        try:
            start_on = date.fromisoformat(week_start_raw)
        except ValueError:
            return {"error": "week_start must be a valid ISO date"}, 400
        days = 7
    else:
        start_on = date.today()
        days = max(min(days, 30), 1)

    setting = get_or_create_instant_book_setting(provider_id)
    provider_tz = get_user_timezone(provider)
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
    next_available_at = None
    for offset in range(days):
        day = start_on + timedelta(days=offset)
        day_slots = []

        if rules:
            applicable_rules = [rule for rule in rules if rule.weekday == day.weekday()]
            for rule in applicable_rules:
                local_cursor = datetime.combine(day, time.min, tzinfo=provider_tz) + timedelta(
                    minutes=rule.start_minute_local
                )
                local_end = datetime.combine(day, time.min, tzinfo=provider_tz) + timedelta(
                    minutes=rule.end_minute_local
                )
                while local_cursor + timedelta(minutes=duration_minutes) <= local_end:
                    slot_start = local_cursor.astimezone(timezone.utc).replace(tzinfo=None)
                    available, reason = provider_is_available(
                        provider_id,
                        slot_start,
                        duration_minutes,
                        skill_id=skill_id,
                    )
                    slot_end = slot_start + timedelta(minutes=duration_minutes)
                    day_slots.append(
                        {
                            "date": day.isoformat(),
                            "time": local_cursor.strftime("%H:%M"),
                            "available": available,
                            "instant_book": bool(setting.instant_book_enabled and available),
                            "reason": None if available else ("booked" if "booking" in (reason or "") else "unavailable"),
                            "start_at": slot_start.replace(tzinfo=timezone.utc).isoformat(),
                            "end_at": slot_end.replace(tzinfo=timezone.utc).isoformat(),
                        }
                    )
                    if available and next_available_at is None:
                        next_available_at = slot_start.replace(tzinfo=timezone.utc).isoformat()
                    local_cursor += timedelta(minutes=duration_minutes)
        else:
            for hour in (9, 11, 13, 15):
                if day.weekday() == 6:
                    continue
                local_cursor = datetime.combine(day, time(hour=hour), tzinfo=provider_tz)
                slot_start = local_cursor.astimezone(timezone.utc).replace(tzinfo=None)
                available, reason = provider_is_available(
                    provider_id,
                    slot_start,
                    120,
                    skill_id=skill_id,
                )
                slot_end = slot_start + timedelta(minutes=120)
                day_slots.append(
                    {
                        "date": day.isoformat(),
                        "time": local_cursor.strftime("%H:%M"),
                        "available": available,
                        "instant_book": bool(setting.instant_book_enabled and available),
                        "reason": None if available else ("booked" if "booking" in (reason or "") else "unavailable"),
                        "start_at": slot_start.replace(tzinfo=timezone.utc).isoformat(),
                        "end_at": slot_end.replace(tzinfo=timezone.utc).isoformat(),
                    }
                )
                if available and next_available_at is None:
                    next_available_at = slot_start.replace(tzinfo=timezone.utc).isoformat()

        slots.extend(sorted(day_slots, key=lambda item: item["start_at"]))

    base_payload = list_provider_slots(
        provider_id,
        start_on=start_on,
        days=days,
        skill_id=skill_id,
    )
    base_payload["timezone"] = provider.timezone or "UTC"
    base_payload["slots"] = slots
    base_payload["next_available_at"] = next_available_at
    return base_payload, 200


@availability_bp.route("/provider/settings", methods=["GET"])
@jwt_required()
def get_provider_settings():
    provider, error = _provider_user()
    if error:
        return error
    return _provider_settings_payload(provider), 200


@availability_bp.route("/provider/availability", methods=["GET"])
@jwt_required()
def provider_availability_overview():
    provider, error = _provider_user()
    if error:
        return error
    return _provider_settings_payload(provider), 200


@availability_bp.route("/provider/weekly-rules", methods=["PUT"])
@jwt_required()
def replace_weekly_rules():
    provider, error = _provider_user()
    if error:
        return error

    data = request.get_json() or {}
    rules_payload = data.get("rules") or []
    timezone_name = _parse_timezone_name(data.get("timezone"), provider.timezone or "UTC")
    if not timezone_name:
        return {"error": "timezone must be a valid IANA timezone"}, 400

    try:
        normalized_rules = _normalize_rules_payload(rules_payload)
    except ValueError as exc:
        db.session.rollback()
        return {"error": str(exc)}, 400

    existing = ProviderAvailabilityRule.query.filter_by(provider_id=provider.id, deleted_at=None).all()
    for rule in existing:
        db.session.delete(rule)

    for item in normalized_rules:
        db.session.add(
            ProviderAvailabilityRule(
                provider_id=provider.id,
                skill_id=item.get("skill_id"),
                weekday=item["weekday"],
                start_minute_local=item["start_minute_local"],
                end_minute_local=item["end_minute_local"],
                buffer_before_minutes=int(item.get("buffer_before_minutes") or 0),
                buffer_after_minutes=int(item.get("buffer_after_minutes") or 0),
                min_notice_minutes=int(item.get("min_notice_minutes") or 60),
                max_advance_days=int(item.get("max_advance_days") or 30),
                enabled=bool(item.get("enabled", True)),
            )
        )

    provider.timezone = timezone_name or "UTC"
    db.session.commit()
    return {"success": True, "message": "Availability rules updated"}, 200


@availability_bp.route("/provider/availability/rules", methods=["PUT"])
@jwt_required()
def replace_provider_availability_rules():
    return replace_weekly_rules()


@availability_bp.route("/provider/blackouts", methods=["POST"])
@jwt_required()
def create_blackout():
    provider, error = _provider_user()
    if error:
        return error

    data = request.get_json() or {}
    if data.get("date"):
        try:
            blackout_date = date.fromisoformat(data.get("date"))
        except ValueError:
            return {"error": "date must be a valid ISO date"}, 400
        start_at = datetime.combine(blackout_date, time.min)
        end_at = datetime.combine(blackout_date, time.min) + timedelta(days=1)
    else:
        try:
            start_at = datetime.fromisoformat(data.get("start_at"))
            end_at = datetime.fromisoformat(data.get("end_at"))
        except Exception:
            return {"error": "start_at and end_at must be valid ISO datetimes"}, 400

    if end_at <= start_at:
        return {"error": "end_at must be after start_at"}, 400

    blackout = ProviderBlackout(
        provider_id=provider.id,
        start_at=start_at,
        end_at=end_at,
        reason_code=(data.get("reason_code") or "OTHER").upper(),
        note=data.get("note") or data.get("reason"),
    )
    db.session.add(blackout)
    db.session.commit()
    return _serialize_blackout(blackout), 201


@availability_bp.route("/provider/availability/blackouts", methods=["POST"])
@jwt_required()
def create_provider_availability_blackout():
    return create_blackout()


@availability_bp.route("/provider/blackouts/<int:blackout_id>", methods=["PATCH"])
@jwt_required()
def update_blackout(blackout_id):
    provider, error = _provider_user()
    if error:
        return error

    blackout = ProviderBlackout.query.filter_by(id=blackout_id, provider_id=provider.id, deleted_at=None).first()
    if not blackout:
        return {"error": "blackout not found"}, 404

    data = request.get_json() or {}
    if data.get("start_at"):
        blackout.start_at = datetime.fromisoformat(data["start_at"])
    if data.get("end_at"):
        blackout.end_at = datetime.fromisoformat(data["end_at"])
    blackout.reason_code = (data.get("reason_code") or blackout.reason_code or "OTHER").upper()
    blackout.note = data.get("note", blackout.note)
    if blackout.end_at <= blackout.start_at:
        return {"error": "end_at must be after start_at"}, 400

    db.session.commit()
    return {"success": True}, 200


@availability_bp.route("/provider/blackouts/<int:blackout_id>", methods=["DELETE"])
@jwt_required()
def delete_blackout(blackout_id):
    provider, error = _provider_user()
    if error:
        return error

    blackout = ProviderBlackout.query.filter_by(id=blackout_id, provider_id=provider.id, deleted_at=None).first()
    if not blackout:
        return {"error": "blackout not found"}, 404

    blackout.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    return {"success": True}, 200


@availability_bp.route("/provider/availability/blackouts/<int:blackout_id>", methods=["DELETE"])
@jwt_required()
def delete_provider_availability_blackout(blackout_id):
    return delete_blackout(blackout_id)


@availability_bp.route("/provider/instant-book", methods=["PUT"])
@jwt_required()
def update_instant_book():
    provider, error = _provider_user()
    if error:
        return error

    data = request.get_json() or {}
    setting = get_or_create_instant_book_setting(provider.id)
    setting.instant_book_enabled = bool(data.get("instant_book_enabled", setting.instant_book_enabled))
    setting.slot_duration_minutes = int(data.get("slot_duration_minutes") or setting.slot_duration_minutes or 60)
    setting.slot_hold_minutes = int(data.get("slot_hold_minutes") or setting.slot_hold_minutes or 5)
    setting.enabled_skill_ids = data.get("enabled_skill_ids") or []
    db.session.commit()
    return {"success": True}, 200
