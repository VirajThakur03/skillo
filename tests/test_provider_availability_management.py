from datetime import date, timedelta


def test_provider_availability_overview_defaults(client, register_user, auth_headers):
    _, provider_token = register_user(
        "provider",
        name="Availability Provider",
        email="availability-overview@example.com",
    )

    response = client.get(
        "/api/availability/provider/availability",
        headers=auth_headers(provider_token),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["timezone"] == "UTC"
    assert payload["rules"] == []
    assert payload["blackouts"] == []
    assert "instant_book" in payload


def test_provider_can_replace_weekly_rules_with_clock_fields(client, register_user, auth_headers):
    _, provider_token = register_user(
        "provider",
        name="Schedule Provider",
        email="availability-rules@example.com",
    )

    save_response = client.put(
        "/api/availability/provider/availability/rules",
        headers=auth_headers(provider_token),
        json={
            "timezone": "Asia/Kolkata",
            "rules": [
                {
                    "day_of_week": 0,
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "is_active": True,
                },
                {
                    "day_of_week": 6,
                    "start_time": "10:00",
                    "end_time": "14:00",
                    "is_active": False,
                },
            ],
        },
    )

    assert save_response.status_code == 200

    overview_response = client.get(
        "/api/availability/provider/availability",
        headers=auth_headers(provider_token),
    )
    assert overview_response.status_code == 200
    payload = overview_response.get_json()
    assert payload["timezone"] == "Asia/Kolkata"
    assert len(payload["rules"]) == 2
    monday_rule = next(item for item in payload["rules"] if item["day_of_week"] == 0)
    assert monday_rule["start_time"] == "09:00"
    assert monday_rule["end_time"] == "17:00"
    assert monday_rule["is_active"] is True


def test_provider_can_add_date_blackout(client, register_user, auth_headers):
    _, provider_token = register_user(
        "provider",
        name="Blackout Provider",
        email="availability-blackout@example.com",
    )
    blackout_date = (date.today() + timedelta(days=5)).isoformat()

    create_response = client.post(
        "/api/availability/provider/availability/blackouts",
        headers=auth_headers(provider_token),
        json={
            "date": blackout_date,
            "reason": "Vacation",
        },
    )

    assert create_response.status_code == 201
    blackout = create_response.get_json()
    assert blackout["date"] == blackout_date
    assert blackout["reason"] == "Vacation"

    overview_response = client.get(
        "/api/availability/provider/availability",
        headers=auth_headers(provider_token),
    )
    assert overview_response.status_code == 200
    blackouts = overview_response.get_json()["blackouts"]
    assert any(item["date"] == blackout_date for item in blackouts)
