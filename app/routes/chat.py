from collections import defaultdict
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import parse_qs, quote, urlparse

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import (
    decode_token,
    get_jwt_identity,
    jwt_required,
    verify_jwt_in_request,
)
from flask_jwt_extended.exceptions import InvalidHeaderError, NoAuthorizationError
from flask_socketio import emit, join_room, leave_room
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from ..extensions import db, socketio
from ..models import Booking, Message, MessageType, Skill, User
from ..services.chat_attachment_security import secure_store_chat_attachment
from ..services.notification_triggers import notify_new_chat_message

chat_bp = Blueprint("chat", __name__)
socket_session_users = {}

PRESENCE_TTL_SECONDS = 45
presence_lock = Lock()
inmemory_presence = {}


def _utcnow():
    return datetime.now(timezone.utc)


def _current_user_id_optional():
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        return int(identity) if identity is not None else None
    except (NoAuthorizationError, InvalidHeaderError):
        return None


def _coerce_int(value, default=None, minimum=None, maximum=None):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None and value < minimum:
        return minimum
    if maximum is not None and value > maximum:
        return maximum
    return value


def _redis_presence_client():
    try:
        import redis
    except ImportError:  # pragma: no cover - dependency is expected in runtime
        return None

    url = current_app.config.get("SOCKETIO_MESSAGE_QUEUE") or current_app.config.get("REDIS_URL")
    if not url:
        return None

    try:
        return redis.from_url(url, decode_responses=True)
    except Exception:
        return None


def _presence_key(user_id):
    return f"chat:presence:{user_id}"


def _typing_key(room, user_id):
    return f"chat:typing:{room}:{user_id}"


def _touch_presence(user_id):
    if user_id is None:
        return

    now_ts = int(_utcnow().timestamp())
    with presence_lock:
        inmemory_presence[user_id] = now_ts

    client = _redis_presence_client()
    if not client:
        return

    try:
        client.setex(_presence_key(user_id), PRESENCE_TTL_SECONDS, str(now_ts))
    except Exception:
        current_app.logger.debug("chat.presence.redis_unavailable", extra={"user_id": user_id})


def _clear_presence(user_id):
    if user_id is None:
        return

    with presence_lock:
        inmemory_presence.pop(user_id, None)

    client = _redis_presence_client()
    if not client:
        return

    try:
        client.delete(_presence_key(user_id))
    except Exception:
        current_app.logger.debug("chat.presence.redis_delete_failed", extra={"user_id": user_id})


def _presence_map(user_ids):
    ids = [int(user_id) for user_id in {user_id for user_id in user_ids if user_id}]
    if not ids:
        return {}

    now_ts = int(_utcnow().timestamp())
    result = {user_id: False for user_id in ids}

    client = _redis_presence_client()
    if client:
        try:
            values = client.mget([_presence_key(user_id) for user_id in ids])
            for user_id, value in zip(ids, values):
                if value is not None:
                    result[user_id] = True
        except Exception:
            current_app.logger.debug("chat.presence.redis_lookup_failed")

    with presence_lock:
        for user_id in ids:
            last_seen = inmemory_presence.get(user_id)
            if last_seen and (now_ts - last_seen) <= PRESENCE_TTL_SECONDS:
                result[user_id] = True

    return result


def _set_typing_state(room, user_id, is_typing):
    if not room or not user_id:
        return

    client = _redis_presence_client()
    if not client:
        return

    key = _typing_key(room, user_id)
    try:
        if is_typing:
            client.setex(key, 5, "1")
        else:
            client.delete(key)
    except Exception:
        current_app.logger.debug("chat.typing.redis_unavailable", extra={"room": room, "user_id": user_id})


def _booking_for_room(room):
    if not room.startswith("booking_"):
        return None
    try:
        booking_id = int(room.split("_", 1)[1])
    except (TypeError, ValueError):
        return None
    return db.session.get(Booking, booking_id)


def _parse_skill_room(room):
    if not room.startswith("skill_"):
        return None, None

    parts = room.split("_")
    if len(parts) == 2:
        skill_id = _coerce_int(parts[1])
        return skill_id, None
    if len(parts) == 3:
        skill_id = _coerce_int(parts[1])
        seeker_id = _coerce_int(parts[2])
        return skill_id, seeker_id
    return None, None


def _user_can_access_room(room, user_id):
    if room.startswith("skill_"):
        skill_id, seeker_id = _parse_skill_room(room)
        skill = db.session.get(Skill, skill_id) if skill_id else None
        if skill is None or user_id is None:
            return False
        if user_id == skill.provider_id:
            return True
        if seeker_id is not None:
            return user_id == seeker_id
        return False

    if room.startswith("user_"):
        try:
            target_id = int(room.split("_", 1)[1])
            return user_id == target_id
        except (TypeError, ValueError):
            return False

    booking = _booking_for_room(room)
    if booking is None or user_id is None:
        return False
    return user_id in {booking.seeker_id, booking.provider_id}


def _parse_attachment_name(content):
    if not isinstance(content, str) or not content.startswith("/api/system/upload?"):
        return None
    try:
        parsed = urlparse(content)
        return parse_qs(parsed.query).get("name", [None])[0]
    except Exception:
        return None


def _serialize_message(message):
    status = "sent"
    if message.read_at:
        status = "read"
    elif message.delivered_at:
        status = "delivered"

    return {
        "id": message.id,
        "room": message.room,
        "sender_id": message.sender_id,
        "sender_name": message.sender.name if message.sender else None,
        "content": message.content,
        "message_type": message.message_type.value if message.message_type else "text",
        "attachment_name": _parse_attachment_name(message.content),
        "created_at": message.created_at.isoformat() + "Z" if message.created_at else None,
        "delivered_at": message.delivered_at.isoformat() + "Z" if message.delivered_at else None,
        "read_at": message.read_at.isoformat() + "Z" if message.read_at else None,
        "status": status,
    }


def _message_status(message):
    if not message:
        return None
    if message.read_at:
        return "read"
    if message.delivered_at:
        return "delivered"
    return "sent"


def _mark_room_messages_read(room, user_id):
    if user_id is None:
        return []

    unread_messages = (
        Message.query.filter(
            Message.room == room,
            Message.sender_id.isnot(None),
            Message.sender_id != user_id,
            Message.read_at.is_(None),
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )

    if not unread_messages:
        return []

    read_at = _utcnow()
    for message in unread_messages:
        message.read_at = read_at
    db.session.commit()

    socketio.emit(
        "messages_read",
        {
            "room": room,
            "reader_id": user_id,
            "message_ids": [message.id for message in unread_messages],
            "read_at": read_at.isoformat() + "Z",
        },
        to=room,
    )
    current_app.logger.info(
        "chat.messages_read",
        extra={"user_id": user_id, "room": room, "message_count": len(unread_messages)},
    )
    return unread_messages


def _attachment_url(storage_ref, original_filename=None):
    encoded_ref = quote(storage_ref, safe="")
    if original_filename:
        return f"/api/system/upload?ref={encoded_ref}&name={quote(original_filename, safe='')}"
    return f"/api/system/upload?ref={encoded_ref}"


def _persist_message(room, sender_id, content, *, message_type=MessageType.TEXT, commit=True):
    now = _utcnow()
    message = Message(
        room=room,
        sender_id=sender_id,
        content=content,
        message_type=message_type,
        created_at=now,
        delivered_at=now,
    )
    db.session.add(message)
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return message


def _other_booking_user(room, sender_id):
    booking = _booking_for_room(room)
    if booking is None or sender_id is None:
        return None
    recipient_id = (
        booking.provider_id if booking.seeker_id == sender_id else booking.seeker_id
    )
    return db.session.get(User, recipient_id)


def _create_and_broadcast_message(room, sender_id, content, message_type=MessageType.TEXT, client_id=None):
    user = db.session.get(User, sender_id) if sender_id else None
    message = _persist_message(room, sender_id, content, message_type=message_type)
    payload = _serialize_message(message)
    if client_id:
        payload["client_id"] = client_id
 
    _notify_room_recipient(room, sender_id, user, message)
    socketio.emit("message", payload, to=room)
    if sender_id:
        socketio.emit(
            "message_ack",
            {
                "room": room,
                "message_id": message.id,
                "client_id": client_id,
                "status": payload.get("status", "sent"),
                "created_at": payload.get("created_at"),
                "delivered_at": payload.get("delivered_at"),
            },
            to=f"user_{sender_id}",
        )
    
    current_app.logger.info(
        "chat.message_broadcast",
        extra={
            "room": room,
            "user_id": sender_id,
            "message_id": message.id,
            "client_id": client_id,
            "message_type": message_type.value if hasattr(message_type, 'value') else message_type
        }
    )
    
    return payload, message


def _other_skill_user(room, sender_id):
    skill_id, seeker_id = _parse_skill_room(room)
    skill = db.session.get(Skill, skill_id) if skill_id else None
    if skill is None or sender_id is None:
        return None
    if sender_id == skill.provider_id:
        return db.session.get(User, seeker_id) if seeker_id is not None else None
    return db.session.get(User, skill.provider_id)


def _notify_room_recipient(room, sender_id, user, message):
    recipient = _other_skill_user(room, sender_id) if room.startswith("skill_") else _other_booking_user(room, sender_id)
    if room.startswith("skill_") and recipient and recipient.id == sender_id:
        first_msg = Message.query.filter_by(room=room).order_by(Message.created_at.asc(), Message.id.asc()).first()
        if first_msg and first_msg.sender_id != sender_id:
            recipient = db.session.get(User, first_msg.sender_id)
        else:
            recipient = None

    if not recipient or not user:
        return

    preview = "[Attachment]" if message.message_type == MessageType.FILE else "[Image]" if message.message_type == MessageType.IMAGE else message.content
    try:
        notify_new_chat_message(
            recipient_id=recipient.id,
            sender_name=user.name,
            content=preview,
            conversation_id=room,
            booking_id=_booking_for_room(room).id if room.startswith("booking_") and _booking_for_room(room) else None,
        )
    except Exception:
        current_app.logger.debug("chat.notification_failed", extra={"room": room, "recipient_id": recipient.id})


def _raw_inquiry_room_defs():
    raw_rooms = (
        db.session.query(Message.room)
        .filter(Message.room.like("skill_%"))
        .distinct()
        .all()
    )
    parsed = []
    for (room_name,) in raw_rooms:
        skill_id, seeker_id = _parse_skill_room(room_name)
        if not skill_id:
            continue
        parsed.append((room_name, skill_id, seeker_id))
    return parsed


def _accessible_room_descriptors(user_id):
    bookings = (
        Booking.query.options(
            joinedload(Booking.provider),
            joinedload(Booking.seeker),
            joinedload(Booking.skill),
        )
        .filter((Booking.seeker_id == user_id) | (Booking.provider_id == user_id))
        .order_by(Booking.updated_at.desc(), Booking.id.desc())
        .limit(250)
        .all()
    )

    descriptors = {}
    for booking in bookings:
        room = f"booking_{booking.id}"
        other_party = booking.provider if booking.seeker_id == user_id else booking.seeker
        descriptors[room] = {
            "room": room,
            "room_type": "booking",
            "booking_id": booking.id,
            "skill": booking.skill.title if booking.skill else "",
            "other_party_id": other_party.id if other_party else None,
            "other_party_name": other_party.name if other_party else "Conversation",
            "sort_at": booking.updated_at or booking.created_at or booking.scheduled_at,
        }

    inquiry_defs = _raw_inquiry_room_defs()
    skill_ids = {skill_id for _, skill_id, _ in inquiry_defs}
    seeker_ids = {seeker_id for _, _, seeker_id in inquiry_defs if seeker_id is not None}

    skills = {
        skill.id: skill
        for skill in Skill.query.options(joinedload(Skill.provider))
        .filter(Skill.id.in_(skill_ids))
        .all()
    } if skill_ids else {}
    seekers = {
        seeker.id: seeker
        for seeker in User.query.filter(User.id.in_(seeker_ids)).all()
    } if seeker_ids else {}

    for room_name, skill_id, seeker_id in inquiry_defs:
        skill = skills.get(skill_id)
        if skill is None:
            continue
        if seeker_id is None:
            if user_id != skill.provider_id:
                continue
            other_party_id = None
            other_party_name = "Legacy inquiry"
        elif user_id == skill.provider_id:
            seeker = seekers.get(seeker_id)
            other_party_id = seeker_id
            other_party_name = f"Inquiry from {seeker.name}" if seeker else "Inquiry"
        elif user_id == seeker_id:
            other_party_id = skill.provider_id
            other_party_name = skill.provider.name if skill.provider else "Provider"
        else:
            continue

        descriptors[room_name] = {
            "room": room_name,
            "room_type": "inquiry",
            "booking_id": None,
            "skill": skill.title if skill else "Deleted skill",
            "other_party_id": other_party_id,
            "other_party_name": other_party_name,
            "sort_at": skill.created_at if hasattr(skill, "created_at") else None,
        }

    room_names = list(descriptors.keys())
    if not room_names:
        return {}

    latest_ids = (
        db.session.query(
            Message.room.label("room"),
            func.max(Message.id).label("latest_id"),
        )
        .filter(Message.room.in_(room_names))
        .group_by(Message.room)
        .subquery()
    )

    latest_messages = (
        db.session.query(Message)
        .options(joinedload(Message.sender))
        .join(latest_ids, Message.id == latest_ids.c.latest_id)
        .all()
    )
    latest_map = {message.room: message for message in latest_messages}

    unread_rows = (
        db.session.query(Message.room, func.count(Message.id))
        .filter(
            Message.room.in_(room_names),
            Message.sender_id.isnot(None),
            Message.sender_id != user_id,
            Message.read_at.is_(None),
        )
        .group_by(Message.room)
        .all()
    )
    unread_map = {room: int(count) for room, count in unread_rows}

    presence = _presence_map(
        descriptor["other_party_id"]
        for descriptor in descriptors.values()
    )

    for room_name, descriptor in descriptors.items():
        latest = latest_map.get(room_name)
        descriptor["latest_message"] = latest.content if latest else None
        descriptor["latest_message_type"] = latest.message_type.value if latest and latest.message_type else None
        descriptor["latest_message_id"] = latest.id if latest else None
        descriptor["latest_at"] = latest.created_at.isoformat() + "Z" if latest and latest.created_at else None
        descriptor["latest_status"] = _message_status(latest)
        descriptor["unread_count"] = unread_map.get(room_name, 0)
        descriptor["other_party_online"] = presence.get(descriptor["other_party_id"], False)
        if latest and latest.created_at:
            descriptor["sort_at"] = latest.created_at

    return descriptors


def _room_descriptor_for_user(room, user_id):
    if not _user_can_access_room(room, user_id):
        return None
    
    # Try getting from existing descriptors (messages/bookings)
    descriptor = _accessible_room_descriptors(user_id).get(room)
    if descriptor:
        return descriptor
        
    # If not found but user has access, it's a new empty room
    if room.startswith("skill_"):
        skill_id, seeker_id = _parse_skill_room(room)
        skill = db.session.get(Skill, skill_id)
        if skill:
            other_party_id = skill.provider_id if user_id == seeker_id else seeker_id
            other_party = db.session.get(User, other_party_id) if other_party_id else None
            return {
                "room": room,
                "room_type": "inquiry",
                "booking_id": None,
                "skill": skill.title,
                "other_party_id": other_party_id,
                "other_party_name": other_party.name if other_party else "Conversation",
                "sort_at": _utcnow(),
            }
            
    if room.startswith("booking_"):
        booking = _booking_for_room(room)
        if booking:
            other_party = booking.provider if booking.seeker_id == user_id else booking.seeker
            return {
                "room": room,
                "room_type": "booking",
                "booking_id": booking.id,
                "skill": booking.skill.title if booking.skill else "",
                "other_party_id": other_party.id if other_party else None,
                "other_party_name": other_party.name if other_party else "Conversation",
                "sort_at": booking.updated_at or booking.created_at,
            }

    return None


def _accessible_room_names(user_id):
    return list(_accessible_room_descriptors(user_id).keys())


def _broadcast_presence_update(user_id):
    room_names = _accessible_room_names(user_id)
    if not room_names:
        return

    online = _presence_map([user_id]).get(user_id, False)
    payload = {
        "user_id": user_id,
        "online": online,
        "last_seen_at": _utcnow().isoformat() + "Z",
    }
    for room_name in room_names:
        socketio.emit("presence_update", {"room": room_name, **payload}, to=room_name)


def _public_room_descriptor(descriptor):
    if descriptor is None:
        return None
    return {key: value for key, value in descriptor.items() if key != "sort_at"}


def _sort_timestamp(value):
    if value is None:
        return 0
    if hasattr(value, "timestamp"):
        try:
            return value.timestamp()
        except Exception:
            return 0
    return 0


@chat_bp.route("/room/<room>", methods=["GET"])
def get_room_history(room):
    user_id = _current_user_id_optional()
    if not _user_can_access_room(room, user_id):
        return {"error": "forbidden"}, 403

    if user_id is not None:
        _mark_room_messages_read(room, user_id)

    query_text = (request.args.get("q") or "").strip()
    limit = _coerce_int(request.args.get("limit"), default=50, minimum=1, maximum=100)
    before_id = _coerce_int(request.args.get("before_id"))
    paginated = (
        request.args.get("format") == "paginated"
        or bool(query_text)
        or before_id is not None
        or request.args.get("limit") is not None
    )

    query = Message.query.options(joinedload(Message.sender)).filter(Message.room == room)
    if before_id is not None:
        query = query.filter(Message.id < before_id)
    if query_text:
        query = query.filter(Message.content.ilike(f"%{query_text}%"))

    rows = query.order_by(Message.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()
    payload = [_serialize_message(message) for message in rows]

    if paginated:
        next_before_id = payload[0]["id"] if has_more and payload else None
        return {
            "items": payload,
            "has_more": has_more,
            "next_before_id": next_before_id,
            "query": query_text,
            "limit": limit,
        }, 200

    return jsonify(payload)


@chat_bp.route("/room/<room>/meta", methods=["GET"])
@jwt_required()
def room_meta(room):
    user_id = int(get_jwt_identity())
    descriptor = _room_descriptor_for_user(room, user_id)
    if descriptor is None:
        return {"error": "forbidden"}, 403

    return _public_room_descriptor(descriptor), 200


@chat_bp.route("/room/<room>", methods=["POST"])
@jwt_required()
def send_room_message(room):
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return {"error": "unauthenticated"}, 401
    if not _user_can_access_room(room, user_id):
        return {"error": "forbidden"}, 403

    data = request.get_json() or {}
    content = (data.get("content") or data.get("message") or "").strip()
    if not content:
        return {"error": "message required"}, 400

    payload, _ = _create_and_broadcast_message(
        room, user_id, content, client_id=data.get("client_id")
    )
    return payload, 201


@chat_bp.route("/room/<room>/upload", methods=["POST"])
@jwt_required()
def upload_chat_attachment(room):
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return {"error": "unauthenticated"}, 401
    if not _user_can_access_room(room, user_id):
        return {"error": "forbidden"}, 403

    if "file" not in request.files:
        return jsonify({"error": "no file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "empty file"}), 400

    original_name = file.filename
    extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    message_type = MessageType.FILE if extension == "pdf" else MessageType.IMAGE
    max_size_mb = 10 if message_type == MessageType.FILE else 5

    try:
        result = secure_store_chat_attachment(
            file,
            room=room,
            user_id=user_id,
            allowed_extensions={"jpg", "jpeg", "png", "webp", "gif", "pdf"},
            max_size_mb=max_size_mb,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - defensive logging path
        current_app.logger.error("chat.upload_failed", extra={"user_id": user_id, "room": room, "error": str(exc)})
        return jsonify({"error": "Upload failed"}), 500

    content_url = _attachment_url(result["storage_ref"], original_name)
    payload, _ = _create_and_broadcast_message(room, user_id, content_url, message_type=message_type)
    return payload, 201


@chat_bp.route("/rooms", methods=["GET"])
@jwt_required()
def list_user_rooms():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return {"error": "unauthenticated"}, 401

    query_text = (request.args.get("q") or "").strip().lower()
    exact_room = (request.args.get("room") or "").strip()
    limit = _coerce_int(request.args.get("limit"), default=20, minimum=1, maximum=100)
    offset = _coerce_int(request.args.get("offset"), default=0, minimum=0)

    items = list(_accessible_room_descriptors(user_id).values())
    if exact_room:
        items = [item for item in items if item["room"] == exact_room]
    if query_text:
        items = [
            item
            for item in items
            if query_text in (item.get("other_party_name") or "").lower()
            or query_text in (item.get("skill") or "").lower()
            or query_text in (item.get("latest_message") or "").lower()
            or query_text in item["room"].lower()
        ]

    items.sort(
        key=lambda item: (
            _sort_timestamp(item.get("sort_at")),
            item.get("latest_message_id") or 0,
        ),
        reverse=True,
    )

    total = len(items)
    paginated = [_public_room_descriptor(item) for item in items[offset: offset + limit]]
    return {
        "items": paginated,
        "total": total,
        "has_more": offset + limit < total,
        "next_offset": offset + limit if offset + limit < total else None,
        "query": query_text,
    }, 200


@chat_bp.route("/search", methods=["GET"])
@jwt_required()
def search_messages():
    user_id = int(get_jwt_identity())
    query_text = (request.args.get("q") or "").strip()
    limit = _coerce_int(request.args.get("limit"), default=20, minimum=1, maximum=100)
    offset = _coerce_int(request.args.get("offset"), default=0, minimum=0)

    if not query_text:
        return {"items": [], "total": 0, "has_more": False, "next_offset": None}, 200

    room_names = _accessible_room_names(user_id)
    if not room_names:
        return {"items": [], "total": 0, "has_more": False, "next_offset": None}, 200

    query = (
        Message.query.options(joinedload(Message.sender))
        .filter(
            Message.room.in_(room_names),
            Message.content.ilike(f"%{query_text}%"),
        )
        .order_by(Message.id.desc())
    )
    total = query.count()
    rows = query.offset(offset).limit(limit).all()
    descriptors = _accessible_room_descriptors(user_id)

    items = []
    for message in rows:
        descriptor = descriptors.get(message.room)
        if not descriptor:
            continue
        items.append(
            {
                "room": message.room,
                "message": _serialize_message(message),
                "room_meta": {
                    "room_type": descriptor["room_type"],
                    "booking_id": descriptor["booking_id"],
                    "skill": descriptor["skill"],
                    "other_party_id": descriptor["other_party_id"],
                    "other_party_name": descriptor["other_party_name"],
                    "other_party_online": descriptor["other_party_online"],
                },
            }
        )

    return {
        "items": items,
        "total": total,
        "has_more": offset + limit < total,
        "next_offset": offset + limit if offset + limit < total else None,
        "query": query_text,
    }, 200


@chat_bp.route("/unread-count", methods=["GET"])
@jwt_required()
def unread_count():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return {"error": "unauthenticated"}, 401

    rooms = _accessible_room_names(user_id)
    if not rooms:
        return {"count": 0}, 200

    count = (
        Message.query.filter(
            Message.room.in_(rooms),
            Message.sender_id.isnot(None),
            Message.sender_id != user_id,
            Message.read_at.is_(None),
        )
        .count()
    )
    return {"count": count}, 200


def socket_handlers(app):
    # ---- Socket.IO per-SID rate limiting ----
    import collections
    _rate_counters = {}  # sid -> {event_type -> deque of timestamps}
    _RATE_LIMITS = {
        "message": (30, 60),    # 30 messages per 60 seconds
        "typing": (60, 60),     # 60 typing events per 60 seconds
        "heartbeat": (120, 60), # 120 heartbeats per 60 seconds
    }

    def _check_rate_limit(sid, event_type):
        """Return True if allowed, False if rate-limited."""
        limit_cfg = _RATE_LIMITS.get(event_type)
        if not limit_cfg:
            return True
        max_count, window_seconds = limit_cfg
        now = _utcnow().timestamp()
        if sid not in _rate_counters:
            _rate_counters[sid] = {}
        if event_type not in _rate_counters[sid]:
            _rate_counters[sid][event_type] = collections.deque()
        dq = _rate_counters[sid][event_type]
        # Evict expired entries
        while dq and dq[0] < now - window_seconds:
            dq.popleft()
        if len(dq) >= max_count:
            return False
        dq.append(now)
        return True

    def _cleanup_rate_counters(sid):
        _rate_counters.pop(sid, None)

    @socketio.on("connect")
    def handle_connect(auth):
        sid = request.sid
        token = auth.get("token") if isinstance(auth, dict) else None
        if not token:
            current_app.logger.warning("chat.socket_connect_missing_token", extra={"sid": sid})
            return False

        try:
            decoded = decode_token(token)
            user_id = int(decoded.get("sub"))
            user = db.session.get(User, user_id)
            if not user:
                current_app.logger.warning("chat.socket_connect_unknown_user", extra={"sid": sid, "user_id": user_id})
                return False
        except Exception:
            current_app.logger.warning("chat.socket_connect_invalid_token", extra={"sid": sid})
            return False

        socket_session_users[sid] = user_id
        join_room(f"user_{user_id}")
        _touch_presence(user_id)
        _broadcast_presence_update(user_id)
        current_app.logger.info("chat.socket_connected", extra={"sid": sid, "user_id": user_id})
        emit("connected", {"msg": "connected", "user_id": user_id, "presence_ttl_seconds": PRESENCE_TTL_SECONDS})
        return True

    @socketio.on("heartbeat")
    def handle_heartbeat(data=None):
        if not _check_rate_limit(request.sid, "heartbeat"):
            return
        user_id = socket_session_users.get(request.sid)
        token = (data or {}).get("token") if isinstance(data, dict) else None
        if token and not user_id:
            try:
                decoded = decode_token(token)
                user_id = int(decoded.get("sub"))
            except Exception:
                pass
        if not user_id:
            return
        _touch_presence(user_id)
        _broadcast_presence_update(user_id)
        emit("heartbeat_ack", {"user_id": user_id, "ttl_seconds": PRESENCE_TTL_SECONDS})

    @socketio.on("join")
    def handle_join(data):
        room = (data or {}).get("room")
        if not room:
            emit("room_error", {"error": "room required"})
            return

        user_id = socket_session_users.get(request.sid)
        token = (data or {}).get("token")
        if token and not user_id:
            try:
                decoded = decode_token(token)
                user_id = int(decoded.get("sub"))
            except Exception:
                pass

        if not _user_can_access_room(room, user_id):
            current_app.logger.warning("chat.join_forbidden", extra={"sid": request.sid, "user_id": user_id, "room": room})
            emit("room_error", {"error": "forbidden"})
            return

        join_room(room)
        descriptor = _room_descriptor_for_user(room, user_id)
        emit("joined", {"room": room, "meta": _public_room_descriptor(descriptor)}, to=request.sid)
        current_app.logger.info("chat.joined_room", extra={"sid": request.sid, "user_id": user_id, "room": room})

    @socketio.on("leave")
    def handle_leave(data):
        room = (data or {}).get("room")
        if not room:
            return
        leave_room(room)
        emit("left", {"room": room}, to=request.sid)

    @socketio.on("message")
    def handle_message(data):
        if not _check_rate_limit(request.sid, "message"):
            emit("room_error", {"error": "rate_limited"})
            return
        room = (data or {}).get("room")
        msg_text = ((data or {}).get("message") or (data or {}).get("content") or "").strip()
        client_id = (data or {}).get("client_id")

        if not room or not msg_text:
            emit("room_error", {"error": "message required"})
            return

        sender_id = socket_session_users.get(request.sid)
        token = (data or {}).get("token")
        if token:
            try:
                decoded = decode_token(token)
                sender_id = int(decoded.get("sub"))
            except Exception:
                sender_id = None

        if not _user_can_access_room(room, sender_id):
            current_app.logger.warning("chat.message_forbidden", extra={"sid": request.sid, "user_id": sender_id, "room": room})
            emit("room_error", {"error": "forbidden"})
            return

        payload, message = _create_and_broadcast_message(room, sender_id, msg_text, client_id=client_id)
        current_app.logger.info(
            "chat.socket_message_created",
            extra={"sid": request.sid, "user_id": sender_id, "room": room, "message_id": message.id},
        )

    @socketio.on("worker_location")
    def handle_worker_location(data):
        booking_id = (data or {}).get("booking_id")
        lat = (data or {}).get("latitude")
        lon = (data or {}).get("longitude")
        token = (data or {}).get("token")

        if not booking_id or lat is None or lon is None or not token:
            return

        try:
            decoded = decode_token(token)
            user_id = int(decoded.get("sub"))
        except Exception:
            return

        booking = db.session.get(Booking, booking_id)
        if not booking or booking.provider_id != user_id:
            return

        try:
            booking.worker_latitude = float(lat)
            booking.worker_longitude = float(lon)
        except Exception:
            return

        booking.worker_last_seen_at = _utcnow()
        db.session.commit()

        room = f"booking_{booking.id}"
        emit(
            "worker_location_update",
            {
                "booking_id": booking.id,
                "latitude": booking.worker_latitude,
                "longitude": booking.worker_longitude,
                "last_seen_at": booking.worker_last_seen_at.isoformat() + "Z",
            },
            to=room,
        )

    @socketio.on("typing")
    def handle_typing(data):
        if not _check_rate_limit(request.sid, "typing"):
            return
        room = (data or {}).get("room")
        if not room:
            return

        sender_id = socket_session_users.get(request.sid)
        token = (data or {}).get("token")
        if token and not sender_id:
            try:
                decoded = decode_token(token)
                sender_id = int(decoded.get("sub"))
            except Exception:
                pass

        if not _user_can_access_room(room, sender_id):
            emit("room_error", {"error": "forbidden"})
            return

        sender_name = "Someone"
        if sender_id:
            user = db.session.get(User, sender_id)
            if user:
                sender_name = user.name.split(" ")[0]
        _set_typing_state(room, sender_id, True)

        emit(
            "typing",
            {"room": room, "sender_name": sender_name, "is_typing": True},
            to=room,
            include_self=False,
        )

    @socketio.on("typing_stop")
    def handle_typing_stop(data):
        room = (data or {}).get("room")
        if not room:
            return

        sender_id = socket_session_users.get(request.sid)
        token = (data or {}).get("token")
        if token and not sender_id:
            try:
                decoded = decode_token(token)
                sender_id = int(decoded.get("sub"))
            except Exception:
                pass

        if not _user_can_access_room(room, sender_id):
            emit("room_error", {"error": "forbidden"})
            return

        sender_name = "Someone"
        if sender_id:
            user = db.session.get(User, sender_id)
            if user:
                sender_name = user.name.split(" ")[0]
        _set_typing_state(room, sender_id, False)

        emit(
            "typing",
            {"room": room, "sender_name": sender_name, "is_typing": False},
            to=room,
            include_self=False,
        )

    @socketio.on("disconnect")
    def handle_disconnect():
        _cleanup_rate_counters(request.sid)
        user_id = socket_session_users.pop(request.sid, None)
        if not user_id:
            return
        _clear_presence(user_id)
        _broadcast_presence_update(user_id)
        current_app.logger.info("chat.socket_disconnected", extra={"sid": request.sid, "user_id": user_id})
