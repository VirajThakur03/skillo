from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import Booking, BookingStatus, Message, PaymentStatus, RoleEnum, Skill


def test_chat_history_marks_messages_read_and_updates_unread_counts(
    app,
    client,
    register_user,
    auth_headers,
):
    seeker, seeker_token = register_user(
        "seeker",
        name="Chat Seeker",
        email="chat-seeker@example.com",
    )
    provider, provider_token = register_user(
        "provider",
        name="Chat Provider",
        email="chat-provider@example.com",
    )

    with app.app_context():
        skill = Skill(
            provider_id=provider["id"],
            title="Electrician",
            description="Wiring and fixtures",
            price=800,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()

        booking = Booking(
            seeker_id=seeker["id"],
            provider_id=provider["id"],
            skill_id=skill.id,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            duration_minutes=60,
            price=800,
            currency="INR",
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.CAPTURED,
        )
        db.session.add(booking)
        db.session.flush()

        db.session.add(
            Message(
                room=f"booking_{booking.id}",
                sender_id=seeker["id"],
                content="Please bring spare switches.",
                delivered_at=datetime.now(timezone.utc),
            )
        )
        db.session.commit()
        booking_id = booking.id

    unread_before = client.get(
        "/api/chat/unread-count",
        headers=auth_headers(provider_token),
    )
    assert unread_before.status_code == 200
    assert unread_before.get_json()["count"] == 1

    room_response = client.get(
        f"/api/chat/room/booking_{booking_id}",
        headers=auth_headers(provider_token),
    )
    assert room_response.status_code == 200
    messages = room_response.get_json()
    assert messages[0]["status"] == "read"
    assert messages[0]["read_at"] is not None
    assert messages[0]["delivered_at"] is not None

    unread_after = client.get(
        "/api/chat/unread-count",
        headers=auth_headers(provider_token),
    )
    assert unread_after.status_code == 200
    assert unread_after.get_json()["count"] == 0


def test_chat_history_emits_read_receipt_event_to_room(
    app,
    client,
    register_user,
    auth_headers,
    socket_client,
):
    seeker, seeker_token = register_user(
        "seeker",
        name="Receipt Seeker",
        email="receipt-seeker@example.com",
    )
    provider, provider_token = register_user(
        "provider",
        name="Receipt Provider",
        email="receipt-provider@example.com",
    )

    with app.app_context():
        skill = Skill(
            provider_id=provider["id"],
            title="Carpenter",
            description="Cabinet install",
            price=1200,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()

        booking = Booking(
            seeker_id=seeker["id"],
            provider_id=provider["id"],
            skill_id=skill.id,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            duration_minutes=90,
            price=1200,
            currency="INR",
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.CAPTURED,
        )
        db.session.add(booking)
        db.session.flush()

        message = Message(
            room=f"booking_{booking.id}",
            sender_id=seeker["id"],
            content="Please park near the side gate.",
            delivered_at=datetime.now(timezone.utc),
        )
        db.session.add(message)
        db.session.commit()
        booking_id = booking.id
        message_id = message.id

    seeker_socket = socket_client(seeker_token)
    provider_socket = socket_client(provider_token)
    seeker_socket.emit("join", {"room": f"booking_{booking_id}"})
    provider_socket.emit("join", {"room": f"booking_{booking_id}"})
    seeker_socket.get_received()
    provider_socket.get_received()

    room_response = client.get(
        f"/api/chat/room/booking_{booking_id}",
        headers=auth_headers(provider_token),
    )
    assert room_response.status_code == 200

    seeker_events = seeker_socket.get_received()
    read_events = [event for event in seeker_events if event["name"] == "messages_read"]
    assert read_events, seeker_events
    payload = read_events[-1]["args"][0]
    assert payload["room"] == f"booking_{booking_id}"
    assert payload["reader_id"] == provider["id"]
    assert payload["message_ids"] == [message_id]
    assert payload["read_at"] is not None


def test_chat_post_returns_delivered_status(
    app,
    client,
    register_user,
    auth_headers,
):
    seeker, seeker_token = register_user(
        "seeker",
        name="Chat Sender",
        email="chat-sender@example.com",
    )
    provider, _provider_token = register_user(
        "provider",
        name="Chat Receiver",
        email="chat-receiver@example.com",
    )

    with app.app_context():
        skill = Skill(
            provider_id=provider["id"],
            title="Plumber",
            description="Leak fixing",
            price=700,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()

        booking = Booking(
            seeker_id=seeker["id"],
            provider_id=provider["id"],
            skill_id=skill.id,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            duration_minutes=60,
            price=700,
            currency="INR",
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.CAPTURED,
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

    response = client.post(
        f"/api/chat/room/booking_{booking_id}",
        headers=auth_headers(seeker_token),
        json={"content": "I will be home after 4 PM."},
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["status"] == "delivered"
    assert payload["delivered_at"] is not None
    assert payload["read_at"] is None


def test_typing_requires_room_access(
    app,
    register_user,
    socket_client,
):
    provider, provider_token = register_user(
        "provider",
        name="Typing Provider",
        email="typing-provider@example.com",
    )
    seeker, seeker_token = register_user(
        "seeker",
        name="Typing Seeker",
        email="typing-seeker@example.com",
    )

    with app.app_context():
        skill = Skill(
            provider_id=provider["id"],
            title="Painter",
            description="Walls and touch-ups",
            price=950,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.commit()
        skill_id = skill.id

    provider_socket = socket_client(provider_token)
    seeker_socket = socket_client(seeker_token)
    provider_socket.get_received()
    seeker_socket.get_received()

    seeker_socket.emit("typing", {"room": f"skill_{skill_id}_999999"})
    events = seeker_socket.get_received()
    assert any(
        event["name"] == "room_error" and event["args"][0]["error"] == "forbidden"
        for event in events
    ), events
