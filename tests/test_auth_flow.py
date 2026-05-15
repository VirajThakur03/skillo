from app.extensions import db
from app.models import KycStatus, User, VerificationStatus
from app.routes import auth as auth_routes


def test_provider_verification_retry_flow(
    app,
    client,
    register_user,
    auth_headers,
    image_upload,
    video_upload,
    monkeypatch,
):
    provider, provider_token = register_user(
        "provider",
        name="Provider Retry",
        email="provider-retry@example.com",
    )

    monkeypatch.setattr(auth_routes, "is_blurry", lambda path: False)
    monkeypatch.setattr(auth_routes, "is_screenshot", lambda path: False)
    monkeypatch.setattr(auth_routes, "extract_text", lambda path: "DL01202300000000000")
    monkeypatch.setattr(auth_routes, "validate_document", lambda text, doc_type: doc_type == "driving")
    monkeypatch.setattr(auth_routes, "extract_and_save_document_face", lambda path, out: False)
    monkeypatch.setattr(auth_routes, "extract_face_from_image", lambda path: [[1, 2], [3, 4]])
    monkeypatch.setattr(auth_routes, "load_document_face", lambda path: None)
    monkeypatch.setattr(auth_routes, "extract_video_faces", lambda path: [[[1, 2], [3, 4]]])

    face_match_results = iter([False, True])
    monkeypatch.setattr(
        auth_routes,
        "faces_match",
        lambda reference_face, video_faces: next(face_match_results),
    )

    response = client.post(
        "/api/auth/upload_document",
        headers=auth_headers(provider_token),
        data={
            "document_type": "driving",
            "file": image_upload("license.jpg"),
        },
    )
    assert response.status_code == 201
    document_data = response.get_json()
    assert document_data["requires_selfie"] is True
    assert document_data["next"] == "/provider_verification_selfie"

    selfie_response = client.post(
        "/api/auth/upload_selfie",
        headers=auth_headers(provider_token),
        data={"file": image_upload("selfie.jpg")},
    )
    assert selfie_response.status_code == 201
    assert selfie_response.get_json()["next"] == "/provider_verification_video"

    mismatch_response = client.post(
        "/api/auth/upload_verification_video",
        headers=auth_headers(provider_token),
        data={"file": video_upload()},
    )
    assert mismatch_response.status_code == 400
    assert mismatch_response.get_json()["error"] == "Face does not match reference"

    me_response = client.get("/api/auth/me", headers=auth_headers(provider_token))
    assert me_response.status_code == 200
    assert me_response.get_json()["verification_status"] == "rejected"

    retry_document_response = client.post(
        "/api/auth/upload_document",
        headers=auth_headers(provider_token),
        data={
            "document_type": "driving license",
            "file": image_upload("license-retry.jpg"),
        },
    )
    assert retry_document_response.status_code == 201

    retry_selfie_response = client.post(
        "/api/auth/upload_selfie",
        headers=auth_headers(provider_token),
        data={"file": image_upload("selfie-retry.jpg")},
    )
    assert retry_selfie_response.status_code == 201

    success_video_response = client.post(
        "/api/auth/upload_verification_video",
        headers=auth_headers(provider_token),
        data={"file": video_upload("verification-retry.mp4")},
    )
    assert success_video_response.status_code == 201
    assert success_video_response.get_json()["next"] == "/confirm_location"

    location_response = client.post(
        "/api/auth/confirm_location",
        headers=auth_headers(provider_token),
        json={"latitude": 19.076, "longitude": 72.8777},
    )
    assert location_response.status_code == 200
    assert location_response.get_json()["trust_score"] == 30

    with app.app_context():
        user = User.query.filter_by(email=provider["email"]).first()
        assert user.document_type == "driving"
        assert user.is_verified is True
        assert user.verification_status.value == "completed"


def test_refresh_and_password_reset_flow(client, register_user):
    user, _access_token = register_user(
        "seeker",
        name="Reset Ready User",
        email="reset-ready@example.com",
        password="secret123",
    )

    login_response = client.post(
        "/api/auth/login",
        json={"email": user["email"], "password": "secret123"},
    )
    assert login_response.status_code == 200
    refresh_token = login_response.get_json()["refresh_token"]

    refresh_response = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert refresh_response.status_code == 200
    assert refresh_response.get_json()["access_token"]

    reset_request = client.post(
        "/api/auth/password-reset/request",
        json={"email": user["email"]},
    )
    assert reset_request.status_code == 202
    reset_token = reset_request.get_json()["reset_token"]

    reset_confirm = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": reset_token, "password": "newsecret456"},
    )
    assert reset_confirm.status_code == 200

    relogin = client.post(
        "/api/auth/login",
        json={"email": user["email"], "password": "newsecret456"},
    )
    assert relogin.status_code == 200


def test_auth_entrypoints_render_and_role_apis_enforce_access(client, register_user, auth_headers):
    seeker, seeker_token = register_user(
        "seeker",
        name="Route Seeker",
        email="route-seeker@example.com",
    )
    provider, provider_token = register_user(
        "provider",
        name="Route Provider",
        email="route-provider@example.com",
    )

    for path in ("/login", "/register", "/demo_login"):
        response = client.get(path)
        assert response.status_code == 200

    seeker_dashboard = client.get("/api/bookings/my", headers=auth_headers(seeker_token))
    assert seeker_dashboard.status_code == 200

    provider_dashboard = client.get("/api/provider/dashboard", headers=auth_headers(provider_token))
    assert provider_dashboard.status_code in {200, 403}

    seeker_forbidden = client.get("/api/provider/dashboard", headers=auth_headers(seeker_token))
    assert seeker_forbidden.status_code == 403

    provider_forbidden = client.get("/api/bookings/my", headers=auth_headers(provider_token))
    assert provider_forbidden.status_code == 403


def test_provider_auth_me_exposes_centralized_next_route_contract(
    app,
    client,
    register_user,
    auth_headers,
):
    provider, token = register_user(
        "provider",
        name="Contract Provider",
        email="contract-provider@example.com",
    )

    with app.app_context():
        provider_record = db.session.get(User, provider["id"])
        provider_record.is_provider_profile_complete = True
        provider_record.verification_status = VerificationStatus.completed
        provider_record.kyc_status = KycStatus.pending
        provider_record.is_verified = True
        db.session.commit()

    response = client.get("/api/auth/me", headers=auth_headers(token))
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["provider_access_state"] == "kyc_pending"
    assert payload["provider_next_route"] == "/provider/dashboard"
    assert "/provider/dashboard" in payload["provider_allowed_paths"]
    assert "/provider/kyc-status" in payload["provider_allowed_paths"]
