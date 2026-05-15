from app.extensions import db
from app.models import KycStatus, User, VerificationStatus


def _create_provider(client, auth_headers, register_user, *, email, phone, skill):
    provider, provider_token = register_user(
        "provider",
        name="Saved Provider",
        email=email,
    )
    profile_response = client.post(
        "/api/provider/profile",
        headers=auth_headers(provider_token),
        json={
            "name": "Saved Provider",
            "phone": phone,
            "skill": skill,
            "price": 900,
            "location": "Pune",
            "description": "Helpful and reliable",
        },
    )
    assert profile_response.status_code == 200, profile_response.get_json()
    with db.session.no_autoflush:
        provider_record = db.session.get(User, provider["id"])
        provider_record.is_verified = True
        provider_record.verification_status = VerificationStatus.completed
        provider_record.kyc_status = KycStatus.approved
        provider_record.avg_response_seconds = 480
        db.session.commit()
    return provider, profile_response.get_json()["skill_id"]


def test_favorites_are_idempotent_and_list_saved_provider_data(
    app,
    client,
    auth_headers,
    register_user,
):
    with app.app_context():
        seeker, seeker_token = register_user(
            "seeker",
            name="Favorites Seeker",
            email="favorites-seeker@example.com",
        )
        provider, skill_id = _create_provider(
            client,
            auth_headers,
            register_user,
            email="favorites-provider@example.com",
            phone="9999999911",
            skill="Cleaner",
        )

        first_save = client.post(
            "/api/favorites",
            headers=auth_headers(seeker_token),
            json={"provider_id": provider["id"]},
        )
        assert first_save.status_code == 201
        assert first_save.get_json()["saved"] is True

        second_save = client.post(
            "/api/favorites",
            headers=auth_headers(seeker_token),
            json={"provider_id": provider["id"]},
        )
        assert second_save.status_code == 200
        assert second_save.get_json()["saved"] is True

        listing = client.get(
            "/api/favorites?limit=10",
            headers=auth_headers(seeker_token),
        )
        assert listing.status_code == 200
        payload = listing.get_json()
        assert payload["total"] == 1
        assert len(payload["items"]) == 1
        item = payload["items"][0]
        assert item["provider"]["id"] == provider["id"]
        assert item["provider"]["is_saved"] is True
        assert item["provider"]["response_label"] == "~8 min"
        assert item["provider"]["acceptance_rate"] is None
        assert item["skill_id"] == skill_id
        assert item["skill_title"] == "Cleaner"
        assert item["starting_price"] == 900.0
        assert item["saved_at"] is not None


def test_favorites_require_seeker_role(app, client, auth_headers, register_user):
    with app.app_context():
        provider_user, provider_token = register_user(
            "provider",
            name="Provider Actor",
            email="provider-actor@example.com",
        )

        response = client.get(
            "/api/favorites",
            headers=auth_headers(provider_token),
        )
        assert response.status_code == 403
        assert response.get_json()["error"] == "only seekers may manage saved providers"

        delete_response = client.delete(
            f"/api/favorites/{provider_user['id']}",
            headers=auth_headers(provider_token),
        )
        assert delete_response.status_code == 403
