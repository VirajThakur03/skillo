from app.extensions import db
from app.models import User, VerificationStatus


def event_payload(event):
    args = event.get("args")
    if isinstance(args, list):
        return args[0] if args else {}
    return args or {}


def test_public_browse_booking_chat_tracking_and_dashboard(
    app,
    client,
    register_user,
    auth_headers,
    socket_client,
    future_schedule,
):
    provider, provider_token = register_user(
        "provider",
        name="Verified Provider",
        email="provider-flow@example.com",
    )

    with app.app_context():
        provider_record = User.query.filter_by(email=provider["email"]).first()
        provider_record.is_verified = True
        provider_record.verification_status = VerificationStatus.completed
        provider_record.latitude = 19.11
        provider_record.longitude = 72.88
        db.session.commit()

    profile_response = client.post(
        "/api/provider/profile",
        headers=auth_headers(provider_token),
        json={
            "name": "Verified Provider",
            "phone": "9999999999",
            "skill": "Electrician",
            "price": 800,
            "location": "Mumbai",
            "description": "Repairs and installation",
        },
    )
    assert profile_response.status_code == 200
    skill_id = profile_response.get_json()["skill_id"]

    assert client.get("/").status_code == 200
    assert client.get("/home").status_code == 200
    assert client.get(f"/skill/{skill_id}").status_code == 200
    assert client.get(f"/providers?skill_id={skill_id}").status_code == 200
    assert client.get(f"/chat/skill_{skill_id}").status_code == 200

    seeker, seeker_token = register_user(
        "seeker",
        name="Journey Seeker",
        email="seeker-flow@example.com",
    )

    with app.app_context():
        seeker_record = User.query.filter_by(email=seeker["email"]).first()
        seeker_record.wallet_balance = 50
        seeker_record.latitude = 19.20
        seeker_record.longitude = 72.90
        db.session.commit()

    providers_api_response = client.get(
        f"/api/skills/providers?skill_id={skill_id}",
        headers=auth_headers(seeker_token),
    )
    assert providers_api_response.status_code == 200
    providers_data = providers_api_response.get_json()
    assert providers_data[0]["id"] == provider["id"]

    booking_response = client.post(
        "/api/bookings",
        headers=auth_headers(seeker_token),
        json={
            "skill_id": skill_id,
            "provider_id": provider["id"],
            "scheduled_at": future_schedule,
            "duration_minutes": 60,
        },
    )
    assert booking_response.status_code == 201
    booking_data = booking_response.get_json()
    booking_id = booking_data["id"]
    assert booking_data["wallet_used"] == 50.0

    pending_dashboard_response = client.get(
        "/api/provider/dashboard",
        headers=auth_headers(provider_token),
    )
    assert pending_dashboard_response.status_code == 200
    assert pending_dashboard_response.get_json()["bookings"]["pending"][0]["id"] == booking_id

    seeker_booking_response = client.get(
        f"/api/bookings/{booking_id}",
        headers=auth_headers(seeker_token),
    )
    provider_booking_response = client.get(
        f"/api/bookings/{booking_id}",
        headers=auth_headers(provider_token),
    )
    assert seeker_booking_response.status_code == 200
    assert provider_booking_response.status_code == 200

    anonymous_history_response = client.get(f"/api/chat/room/booking_{booking_id}")
    assert anonymous_history_response.status_code == 403
    public_skill_history_response = client.get(f"/api/chat/room/skill_{skill_id}")
    assert public_skill_history_response.status_code == 403

    anonymous_socket = socket_client()
    anonymous_socket.get_received()
    anonymous_socket.emit("join", {"room": f"booking_{booking_id}"})
    anonymous_events = anonymous_socket.get_received()
    assert any(event["name"] == "room_error" for event in anonymous_events)

    seeker_socket = socket_client(seeker_token)
    provider_socket = socket_client(provider_token)
    seeker_socket.get_received()
    provider_socket.get_received()

    seeker_socket.emit("join", {"room": f"booking_{booking_id}"})
    provider_socket.emit("join", {"room": f"booking_{booking_id}"})
    seeker_socket.get_received()
    provider_socket.get_received()

    seeker_socket.emit(
        "message",
        {"room": f"booking_{booking_id}", "message": "On my way?"},
    )
    provider_events = provider_socket.get_received()
    assert any(
        event["name"] == "message"
        and event_payload(event).get("content") == "On my way?"
        for event in provider_events
    )

    pay_response = client.post(
        f"/api/bookings/{booking_id}/pay",
        headers=auth_headers(seeker_token),
        json={"payment_ref": f"PAY-{booking_id}"},
    )
    assert pay_response.status_code == 200

    active_dashboard_response = client.get(
        "/api/provider/dashboard",
        headers=auth_headers(provider_token),
    )
    assert active_dashboard_response.status_code == 200
    assert active_dashboard_response.get_json()["bookings"]["active"][0]["id"] == booking_id

    seeker_socket.get_received()
    location_response = client.post(
        f"/api/bookings/{booking_id}/location",
        headers=auth_headers(provider_token),
        json={"latitude": 19.15, "longitude": 72.91},
    )
    assert location_response.status_code == 200

    seeker_location_events = seeker_socket.get_received()
    assert any(event["name"] == "worker_location_update" for event in seeker_location_events)

    tracked_booking_response = client.get(
        f"/api/bookings/{booking_id}",
        headers=auth_headers(seeker_token),
    )
    tracked_booking = tracked_booking_response.get_json()
    assert tracked_booking["worker_latitude"] == 19.15
    assert tracked_booking["status"] == "IN_PROGRESS"

    history_response = client.get(
        f"/api/chat/room/booking_{booking_id}",
        headers=auth_headers(seeker_token),
    )
    assert history_response.status_code == 200
    assert history_response.get_json()[0]["content"] == "On my way?"

    complete_response = client.post(
        f"/api/bookings/{booking_id}/complete",
        headers=auth_headers(provider_token),
    )
    assert complete_response.status_code == 200

    review_response = client.post(
        f"/api/bookings/{booking_id}/review",
        headers=auth_headers(seeker_token),
        json={"rating": 5, "comment": "Great work"},
    )
    assert review_response.status_code == 200
    assert review_response.get_json()["provider_rating"] == 5.0

    my_bookings_response = client.get(
        "/api/bookings/my",
        headers=auth_headers(seeker_token),
    )
    provider_bookings_response = client.get(
        "/api/bookings/provider",
        headers=auth_headers(provider_token),
    )
    assert my_bookings_response.status_code == 200
    assert provider_bookings_response.status_code == 200
    assert my_bookings_response.get_json()[0]["id"] == booking_id
    assert provider_bookings_response.get_json()[0]["id"] == booking_id


def test_socket_chat_message_preserves_client_id_for_reconciliation(
    app,
    register_user,
    socket_client,
    future_schedule,
    client,
    auth_headers,
):
    provider, provider_token = register_user(
        "provider",
        name="Socket Provider",
        email="socket-provider@example.com",
    )

    with app.app_context():
        provider_record = User.query.filter_by(email=provider["email"]).first()
        provider_record.is_verified = True
        provider_record.verification_status = VerificationStatus.completed
        db.session.commit()

    profile_response = client.post(
        "/api/provider/profile",
        headers=auth_headers(provider_token),
        json={
            "name": "Socket Provider",
            "phone": "9999999996",
            "skill": "Electrician",
            "price": 800,
            "location": "Mumbai",
            "description": "Socket message reconciliation check",
        },
    )
    assert profile_response.status_code == 200
    skill_id = profile_response.get_json()["skill_id"]

    seeker, seeker_token = register_user(
        "seeker",
        name="Socket Seeker",
        email="socket-seeker@example.com",
    )

    booking_response = client.post(
        "/api/bookings",
        headers=auth_headers(seeker_token),
        json={
            "skill_id": skill_id,
            "provider_id": provider["id"],
            "scheduled_at": future_schedule,
            "duration_minutes": 60,
        },
    )
    assert booking_response.status_code == 201
    booking_id = booking_response.get_json()["id"]

    seeker_socket = socket_client(seeker_token)
    provider_socket = socket_client(provider_token)
    seeker_socket.emit("join", {"room": f"booking_{booking_id}"})
    provider_socket.emit("join", {"room": f"booking_{booking_id}"})
    seeker_socket.get_received()
    provider_socket.get_received()

    seeker_socket.emit(
        "message",
        {
            "room": f"booking_{booking_id}",
            "message": "Testing reconciliation",
            "client_id": "tmp-client-123",
        },
    )
    provider_events = provider_socket.get_received()
    matched = [
        event_payload(event)
        for event in provider_events
        if event["name"] == "message"
        and event_payload(event).get("content") == "Testing reconciliation"
    ]
    assert matched, provider_events
    assert matched[-1]["client_id"] == "tmp-client-123"
