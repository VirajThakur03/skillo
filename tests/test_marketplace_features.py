from datetime import datetime, timedelta

from app.extensions import db
from app.models import User, VerificationStatus


def _setup_verified_provider(app, client, auth_headers, register_user, *, email, phone):
    provider, provider_token = register_user(
        "provider",
        name="Marketplace Provider",
        email=email,
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
            "name": "Marketplace Provider",
            "phone": phone,
            "skill": "AC Repair",
            "price": 1200,
            "location": "Mumbai",
            "description": "Cooling and service",
            "tags": ["ac", "repair"],
            "service_areas": ["Andheri", "Bandra"],
        },
    )
    assert profile_response.status_code == 200
    skill_id = profile_response.get_json()["skill_id"]

    weekday = (datetime.now(timezone.utc) + timedelta(days=1)).weekday()
    availability_response = client.put(
        "/api/availability/provider/weekly-rules",
        headers=auth_headers(provider_token),
        json={
            "timezone": "UTC",
            "rules": [
                {
                    "weekday": weekday,
                    "skill_id": skill_id,
                    "start_minute_local": 540,
                    "end_minute_local": 1080,
                    "min_notice_minutes": 0,
                    "enabled": True,
                }
            ],
        },
    )
    assert availability_response.status_code == 200
    return provider, provider_token, skill_id


def _setup_seeker(app, register_user, *, email):
    seeker, seeker_token = register_user(
        "seeker",
        name="Marketplace Seeker",
        email=email,
    )
    with app.app_context():
        seeker_record = User.query.filter_by(email=seeker["email"]).first()
        seeker_record.latitude = 19.12
        seeker_record.longitude = 72.89
        db.session.commit()
    return seeker, seeker_token


def test_availability_search_and_notifications(
    app,
    client,
    register_user,
    auth_headers,
):
    provider, provider_token, skill_id = _setup_verified_provider(
        app,
        client,
        auth_headers,
        register_user,
        email="availability-provider@example.com",
        phone="9999999995",
    )
    _, seeker_token = _setup_seeker(
        app,
        register_user,
        email="availability-seeker@example.com",
    )

    availability_response = client.get(
        f"/api/availability/providers/{provider['id']}?skill_id={skill_id}&days=3"
    )
    assert availability_response.status_code == 200
    availability_data = availability_response.get_json()
    assert availability_data["slots"]
    assert availability_data["next_available_at"] == availability_data["slots"][0]["start_at"]

    search_response = client.get(
        "/api/search/providers?q=AC&verified_only=true&sort=rating",
        headers=auth_headers(seeker_token),
    )
    assert search_response.status_code == 200
    search_items = search_response.get_json()["items"]
    assert len(search_items) == 1
    assert search_items[0]["provider_id"] == provider["id"]
    assert "identity_verified" in search_items[0]["verified_badges"]
    assert search_items[0]["next_available_at"] is not None

    preferences_response = client.put(
        "/api/notifications/preferences",
        headers=auth_headers(provider_token),
        json={
            "push_enabled": True,
            "email_enabled": True,
            "whatsapp_enabled": False,
            "category_channels": {
                "QUOTE_UPDATE": ["in_app", "push"],
            },
            "quiet_hours_enabled": True,
            "quiet_start_local": "22:00",
            "quiet_end_local": "07:00",
        },
    )
    assert preferences_response.status_code == 200

    quote_response = client.post(
        "/api/quote-requests",
        headers=auth_headers(seeker_token),
        json={
            "skill_id": skill_id,
            "service_title": "AC Repair",
            "description": "AC is not cooling",
            "address_text": "Andheri East",
            "provider_ids": [provider["id"]],
            "preferred_window_start": availability_data["slots"][0]["start_at"],
        },
    )
    assert quote_response.status_code == 201

    provider_notifications = client.get(
        "/api/notifications",
        headers=auth_headers(provider_token),
    )
    assert provider_notifications.status_code == 200
    notification_items = provider_notifications.get_json()["items"]
    assert notification_items[0]["category"] == "QUOTE_UPDATE"

    read_response = client.post(
        f"/api/notifications/{notification_items[0]['id']}/read",
        headers=auth_headers(provider_token),
    )
    assert read_response.status_code == 200


def test_quote_accept_reschedule_cancel_flow(
    app,
    client,
    register_user,
    auth_headers,
):
    provider, provider_token, skill_id = _setup_verified_provider(
        app,
        client,
        auth_headers,
        register_user,
        email="quote-provider@example.com",
        phone="9999999994",
    )
    seeker, seeker_token = _setup_seeker(
        app,
        register_user,
        email="quote-seeker@example.com",
    )

    availability_data = client.get(
        f"/api/availability/providers/{provider['id']}?skill_id={skill_id}&days=3"
    ).get_json()
    first_slot = availability_data["slots"][0]["start_at"]
    second_slot = availability_data["slots"][1]["start_at"]

    create_quote_response = client.post(
        "/api/quote-requests",
        headers=auth_headers(seeker_token),
        json={
            "skill_id": skill_id,
            "service_title": "AC Repair",
            "description": "Need inspection and refill",
            "address_text": "Andheri East",
            "provider_ids": [provider["id"]],
            "preferred_window_start": first_slot,
        },
    )
    assert create_quote_response.status_code == 201
    quote_id = create_quote_response.get_json()["id"]

    provider_quote_response = client.post(
        f"/api/quote-requests/{quote_id}/provider-responses",
        headers=auth_headers(provider_token),
        json={
            "response_type": "QUOTE_SENT",
            "total_amount": 1500,
            "estimated_duration_minutes": 60,
            "earliest_available_at": first_slot,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0).isoformat(),
            "note": "Includes inspection and refill",
        },
    )
    assert provider_quote_response.status_code == 201
    provider_quote_id = provider_quote_response.get_json()["id"]

    accept_response = client.post(
        f"/api/quote-requests/{quote_id}/accept",
        headers=auth_headers(seeker_token),
        json={"provider_quote_id": provider_quote_id},
    )
    assert accept_response.status_code == 200
    booking_id = accept_response.get_json()["booking_id"]

    preview_response = client.get(
        f"/api/bookings/{booking_id}/change-policy-preview",
        headers=auth_headers(seeker_token),
    )
    assert preview_response.status_code == 200
    assert preview_response.get_json()["reschedule_allowed"] is True

    reschedule_response = client.post(
        f"/api/bookings/{booking_id}/reschedule-requests",
        headers=auth_headers(seeker_token),
        json={
            "proposed_start_at": second_slot,
            "reason_code": "PLANS_CHANGED",
        },
    )
    assert reschedule_response.status_code == 201
    change_request_id = reschedule_response.get_json()["id"]

    respond_response = client.post(
        f"/api/bookings/{booking_id}/reschedule-requests/{change_request_id}/respond",
        headers=auth_headers(provider_token),
        json={"decision": "ACCEPT"},
    )
    assert respond_response.status_code == 200
    assert respond_response.get_json()["booking"]["scheduled_at"] == second_slot

    cancel_response = client.post(
        f"/api/bookings/{booking_id}/cancel",
        headers=auth_headers(seeker_token),
        json={"reason_code": "PLANS_CHANGED"},
    )
    assert cancel_response.status_code == 200
    assert cancel_response.get_json()["refund_status"] == "PROCESSED"

    change_log_response = client.get(
        f"/api/bookings/{booking_id}/change-log",
        headers=auth_headers(seeker_token),
    )
    assert change_log_response.status_code == 200
    change_log = change_log_response.get_json()
    assert len(change_log["change_requests"]) == 2
    assert any(
        event["event_type"] == "RESCHEDULE_ACCEPTED"
        for event in change_log["timeline"]
    )

    seeker_notifications = client.get(
        "/api/notifications",
        headers=auth_headers(seeker_token),
    )
    assert seeker_notifications.status_code == 200
    assert any(
        item["title"] == "Reschedule accepted"
        for item in seeker_notifications.get_json()["items"]
    )

    with app.app_context():
        seeker_record = db.session.get(User, seeker["id"])
        assert seeker_record.wallet_balance >= 0
