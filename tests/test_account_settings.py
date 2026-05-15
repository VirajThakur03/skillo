from app.extensions import db
from app.models import User


def test_account_settings_profile_update_and_export(
    app,
    client,
    register_user,
    auth_headers,
):
    seeker, token = register_user(
        "seeker",
        name="Settings Seeker",
        email="settings-seeker@example.com",
    )

    settings_page = client.get("/settings")
    assert settings_page.status_code == 200
    assert b"settingsRoleSections" in settings_page.data

    update_response = client.patch(
        "/api/account/profile",
        headers=auth_headers(token),
        json={"name": "Updated Seeker", "phone": "9999999999"},
    )
    assert update_response.status_code == 200, update_response.get_json()
    assert update_response.get_json()["name"] == "Updated Seeker"
    assert update_response.get_json()["phone"] == "9999999999"

    me_response = client.get("/api/auth/me", headers=auth_headers(token))
    assert me_response.status_code == 200, me_response.get_json()
    assert me_response.get_json()["name"] == "Updated Seeker"

    export_response = client.get("/api/account/export", headers=auth_headers(token))
    assert export_response.status_code == 200, export_response.get_json()
    export_payload = export_response.get_json()
    assert export_payload["user"]["name"] == "Updated Seeker"
    assert export_payload["user"]["phone"] == "9999999999"


def test_account_delete_soft_deletes_user_and_related_content(
    app,
    client,
    register_user,
    auth_headers,
):
    provider, token = register_user(
        "provider",
        name="Delete Me",
        email="delete-me@example.com",
    )

    delete_response = client.delete("/api/account", headers=auth_headers(token))
    assert delete_response.status_code == 204

    with app.app_context():
        user = User.query.filter_by(id=provider["id"]).one()
        assert user.name == "Deleted User"
        assert user.phone is None
        assert user.wallet_balance == 0
