from app.extensions import db
from app.models import Booking, KycStatus, User, VerificationStatus
from app.routes import auth as auth_routes


def _event_payload(event):
    args = event.get("args")
    if isinstance(args, list):
        return args[0] if args else {}
    return args or {}


def test_provider_kyc_gate_and_account_rights(
    app,
    client,
    register_user,
    auth_headers,
):
    provider, provider_token = register_user(
        "provider",
        name="KYC Smoke Provider",
        email="smoke-kyc-provider@example.com",
    )

    with app.app_context():
        provider_record = db.session.get(User, provider["id"])
        provider_record.is_verified = True
        provider_record.verification_status = VerificationStatus.completed
        provider_record.kyc_status = KycStatus.rejected
        provider_record.kyc_rejection_reason = "Document edges were cropped."
        db.session.commit()

    blocked_dashboard = client.get(
        "/api/provider/dashboard",
        headers=auth_headers(provider_token),
    )
    assert blocked_dashboard.status_code == 403
    assert blocked_dashboard.get_json()["reason"] == "Document edges were cropped."

    with app.app_context():
        provider_record = db.session.get(User, provider["id"])
        provider_record.kyc_status = KycStatus.approved
        provider_record.kyc_rejection_reason = None
        db.session.commit()

    profile_response = client.post(
        "/api/provider/profile",
        headers=auth_headers(provider_token),
        json={
            "name": "KYC Smoke Provider",
            "phone": "9999999988",
            "skill": "Painter",
            "price": 700,
            "location": "Pune",
            "description": "Interior wall painting",
        },
    )
    assert profile_response.status_code == 200

    dashboard_response = client.get(
        "/api/provider/dashboard",
        headers=auth_headers(provider_token),
    )
    assert dashboard_response.status_code == 200
    assert dashboard_response.get_json()["provider"]["kyc_status"] == "approved"

    consent_response = client.post(
        "/api/account/consent",
        headers=auth_headers(provider_token),
        json={"consent_type": "privacy_policy", "version": "2026-04-09"},
    )
    assert consent_response.status_code == 201

    export_response = client.get(
        "/api/account/export",
        headers=auth_headers(provider_token),
    )
    assert export_response.status_code == 200
    export_data = export_response.get_json()
    assert export_data["user"]["email"] == provider["email"]
    assert export_data["consents"][0]["consent_type"] == "privacy_policy"


def test_auth_booking_chat_and_invoice_smoke(
    app,
    client,
    register_user,
    auth_headers,
    image_upload,
    video_upload,
    socket_client,
    future_schedule,
    monkeypatch,
):
    provider, provider_token = register_user(
        "provider",
        name="Smoke Verified Provider",
        email="smoke-provider@example.com",
    )

    monkeypatch.setattr(auth_routes, "is_blurry", lambda path: False)
    monkeypatch.setattr(auth_routes, "is_screenshot", lambda path: False)
    monkeypatch.setattr(auth_routes, "extract_text", lambda path: "MH12 12345678901")
    monkeypatch.setattr(auth_routes, "extract_and_save_document_face", lambda path, out: False)
    monkeypatch.setattr(auth_routes, "extract_face_from_image", lambda path: [[1, 2], [3, 4]])
    monkeypatch.setattr(auth_routes, "load_document_face", lambda path: None)
    monkeypatch.setattr(auth_routes, "extract_video_faces", lambda path: [[[1, 2], [3, 4]]])
    monkeypatch.setattr(auth_routes, "faces_match", lambda reference_face, video_faces: True)

    document_response = client.post(
        "/api/auth/upload_document",
        headers=auth_headers(provider_token),
        data={
            "document_type": "driving license",
            "file": image_upload("license.jpg"),
        },
    )
    assert document_response.status_code == 201, f"Upload failed: {document_response.get_json()}"

    selfie_response = client.post(
        "/api/auth/upload_selfie",
        headers=auth_headers(provider_token),
        data={"file": image_upload("selfie.jpg")},
    )
    assert selfie_response.status_code == 201

    video_response = client.post(
        "/api/auth/upload_verification_video",
        headers=auth_headers(provider_token),
        data={"file": video_upload("verification.mp4")},
    )
    assert video_response.status_code == 201

    location_response = client.post(
        "/api/auth/confirm_location",
        headers=auth_headers(provider_token),
        json={"latitude": 18.5204, "longitude": 73.8567},
    )
    assert location_response.status_code == 200

    with app.app_context():
        provider_record = db.session.get(User, provider["id"])
        provider_record.kyc_status = KycStatus.approved
        provider_record.phone = "9999999987"
        db.session.commit()

    profile_response = client.post(
        "/api/provider/profile",
        headers=auth_headers(provider_token),
        json={
            "name": "Smoke Verified Provider",
            "phone": "9999999987",
            "skill": "Electrician",
            "price": 850,
            "location": "Pune",
            "description": "Repairs and installation",
        },
    )
    assert profile_response.status_code == 200
    skill_id = profile_response.get_json()["skill_id"]

    seeker, seeker_token = register_user(
        "seeker",
        name="Smoke Seeker",
        email="smoke-seeker@example.com",
    )

    providers_response = client.get(
        f"/api/skills/providers?skill_id={skill_id}",
        headers=auth_headers(seeker_token),
    )
    assert providers_response.status_code == 200
    assert any(item["id"] == provider["id"] for item in providers_response.get_json())

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
            "message": "Please call when you arrive.",
            "token": seeker_token,
        },
    )
    provider_events = provider_socket.get_received()
    assert any(
        event["name"] == "message"
        and _event_payload(event).get("content") == "Please call when you arrive."
        for event in provider_events
    )

    pay_response = client.post(
        f"/api/bookings/{booking_id}/pay",
        headers=auth_headers(seeker_token),
        json={"payment_ref": f"SMOKE-{booking_id}"},
    )
    assert pay_response.status_code == 200

    decision_response = client.post(
        f"/api/bookings/{booking_id}/decision",
        headers=auth_headers(provider_token),
        json={"action": "accept"},
    )
    assert decision_response.status_code == 400

    location_ping = client.post(
        f"/api/bookings/{booking_id}/location",
        headers=auth_headers(provider_token),
        json={"latitude": 18.521, "longitude": 73.857},
    )
    assert location_ping.status_code == 200

    complete_response = client.post(
        f"/api/bookings/{booking_id}/complete",
        headers=auth_headers(provider_token),
    )
    assert complete_response.status_code == 200

    final_booking = client.get(
        f"/api/bookings/{booking_id}",
        headers=auth_headers(seeker_token),
    )
    assert final_booking.status_code == 200
    final_data = final_booking.get_json()
    assert final_data["status"] == "COMPLETED"

    with app.app_context():
        booking = db.session.get(Booking, booking_id)
        assert booking.invoice_url is not None
        assert booking.invoice_url.startswith("invoices/")
