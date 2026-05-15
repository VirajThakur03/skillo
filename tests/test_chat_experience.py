import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.extensions import db, socketio
from app.models import Booking, BookingStatus, PaymentStatus, Skill, User, VerificationStatus


def test_chat_room_meta_pagination_search_and_pdf_upload(
    app,
    client,
    register_user,
    auth_headers,
):
    provider, provider_token = register_user(
        "provider",
        name="Experience Provider",
        email="experience-provider@example.com",
    )
    seeker, seeker_token = register_user(
        "seeker",
        name="Experience Seeker",
        email="experience-seeker@example.com",
    )

    with app.app_context():
        provider_record = db.session.get(User, provider["id"])
        provider_record.is_verified = True
        provider_record.verification_status = VerificationStatus.completed
        skill = Skill(
            provider_id=provider["id"],
            title="Electrician",
            description="Experience coverage",
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
        db.session.commit()
        booking_id = booking.id

    seeker_socket = socketio.test_client(
        app,
        flask_test_client=app.test_client(),
        auth={"token": seeker_token},
    )
    provider_socket = socketio.test_client(
        app,
        flask_test_client=app.test_client(),
        auth={"token": provider_token},
    )
    seeker_socket.emit("join", {"room": f"booking_{booking_id}"})
    provider_socket.emit("join", {"room": f"booking_{booking_id}"})
    seeker_socket.emit("heartbeat")
    provider_socket.emit("heartbeat")

    for idx in range(3):
        response = client.post(
            f"/api/chat/room/booking_{booking_id}",
            headers=auth_headers(seeker_token),
            json={"content": f"Need update {idx}"},
        )
        assert response.status_code == 201

    meta = client.get(
        f"/api/chat/room/booking_{booking_id}/meta",
        headers=auth_headers(seeker_token),
    )
    assert meta.status_code == 200
    meta_payload = meta.get_json()
    assert meta_payload["other_party_name"] == "Experience Provider"
    assert meta_payload["other_party_online"] is True

    paginated = client.get(
        f"/api/chat/room/booking_{booking_id}?format=paginated&limit=2",
        headers=auth_headers(seeker_token),
    )
    assert paginated.status_code == 200
    page_payload = paginated.get_json()
    assert len(page_payload["items"]) == 2
    assert page_payload["has_more"] is True
    assert page_payload["next_before_id"] is not None

    search = client.get(
        f"/api/chat/room/booking_{booking_id}?format=paginated&q=update 1",
        headers=auth_headers(seeker_token),
    )
    assert search.status_code == 200
    assert len(search.get_json()["items"]) == 1

    global_search = client.get(
        "/api/chat/search?q=update",
        headers=auth_headers(seeker_token),
    )
    assert global_search.status_code == 200
    assert global_search.get_json()["items"]

    upload = client.post(
        f"/api/chat/room/booking_{booking_id}/upload",
        headers=auth_headers(seeker_token),
        data={"file": (io.BytesIO(b"%PDF-1.4 fake pdf"), "quote.pdf")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 201
    upload_payload = upload.get_json()
    assert upload_payload["message_type"] == "file"
    assert "name=quote.pdf" in upload_payload["content"]

    rooms = client.get(
        "/api/chat/rooms?limit=10",
        headers=auth_headers(seeker_token),
    )
    assert rooms.status_code == 200
    room_item = rooms.get_json()["items"][0]
    assert room_item["room"] == f"booking_{booking_id}"
    assert room_item["other_party_online"] is True


def test_chat_upload_quarantines_invalid_pdf(
    app,
    client,
    register_user,
    auth_headers,
):
    provider, provider_token = register_user(
        "provider",
        name="Quarantine Provider",
        email="quarantine-provider@example.com",
    )
    seeker, seeker_token = register_user(
        "seeker",
        name="Quarantine Seeker",
        email="quarantine-seeker@example.com",
    )

    with app.app_context():
        provider_record = db.session.get(User, provider["id"])
        provider_record.is_verified = True
        provider_record.verification_status = VerificationStatus.completed
        skill = Skill(
            provider_id=provider["id"],
            title="Plumber",
            description="Quarantine coverage",
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

    upload = client.post(
        f"/api/chat/room/booking_{booking_id}/upload",
        headers=auth_headers(seeker_token),
        data={"file": (io.BytesIO(b"<script>alert(1)</script>"), "quote.pdf")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 400
    assert "security" in upload.get_json()["error"].lower()

    quarantine_dir = Path(app.config["UPLOAD_FOLDER"]) / "quarantine" / "chat" / f"booking_{booking_id}"
    assert quarantine_dir.exists()
    assert any(path.suffix == ".pdf" for path in quarantine_dir.iterdir())


def test_chat_rest_send_emits_sender_ack(
    app,
    client,
    register_user,
    auth_headers,
):
    provider, provider_token = register_user(
        "provider",
        name="Ack Provider",
        email="ack-provider@example.com",
    )
    seeker, seeker_token = register_user(
        "seeker",
        name="Ack Seeker",
        email="ack-seeker@example.com",
    )

    with app.app_context():
        provider_record = db.session.get(User, provider["id"])
        provider_record.is_verified = True
        provider_record.verification_status = VerificationStatus.completed
        skill = Skill(
            provider_id=provider["id"],
            title="Handyman",
            description="Ack coverage",
            price=600,
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
            price=600,
            currency="INR",
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.CAPTURED,
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

    seeker_socket = socketio.test_client(
        app,
        flask_test_client=app.test_client(),
        auth={"token": seeker_token},
    )
    seeker_socket.emit("join", {"room": f"booking_{booking_id}"})
    seeker_socket.get_received()

    response = client.post(
        f"/api/chat/room/booking_{booking_id}",
        headers=auth_headers(seeker_token),
        json={"content": "Ack message", "client_id": "client-ack-123"},
    )
    assert response.status_code == 201, response.get_json()

    events = seeker_socket.get_received()
    ack_events = [event for event in events if event["name"] == "message_ack"]
    assert ack_events
    ack_payload = ack_events[-1]["args"][0]
    assert ack_payload["room"] == f"booking_{booking_id}"
    assert ack_payload["client_id"] == "client-ack-123"
    assert ack_payload["status"] in {"sent", "delivered", "read"}
