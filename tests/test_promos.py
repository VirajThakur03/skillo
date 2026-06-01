from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.extensions import db
from app.models import (
    KycStatus,
    PromoCode,
    PromoDiscountType,
    Skill,
    User,
    VerificationStatus,
)


def _create_provider_and_skill(client, auth_headers, register_user):
    provider, provider_token = register_user(
        "provider",
        name="Promo Provider",
        email="promo-provider@example.com",
    )
    profile_response = client.post(
        "/api/provider/profile",
        headers=auth_headers(provider_token),
        json={
            "name": "Promo Provider",
            "phone": "9999999941",
            "skill": "Cleaning",
            "price": 1200,
            "location": "Pune",
            "description": "Deep home cleaning",
        },
    )
    assert profile_response.status_code == 200, profile_response.get_json()
    skill_id = profile_response.get_json()["skill_id"]

    with db.session.no_autoflush:
        provider_record = db.session.get(User, provider["id"])
        provider_record.is_verified = True
        provider_record.verification_status = VerificationStatus.completed
        provider_record.kyc_status = KycStatus.approved
        db.session.commit()

    return provider, skill_id


def test_validate_promo_returns_checkout_shape(app, client):
    with app.app_context():
        promo = PromoCode(
            code="FIRST20",
            title="First Booking",
            discount_type=PromoDiscountType.PERCENT,
            discount_value=Decimal("20"),
            min_order_amount=Decimal("500"),
            active=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=5),
        )
        db.session.add(promo)
        db.session.commit()

    response = client.post(
        "/api/promos/validate",
        json={"code": "first20", "booking_amount": 1299},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["valid"] is True
    assert payload["discount_type"] == "percent"
    assert payload["discount_value"] == 20.0
    assert payload["discount_amount"] == 259.8
    assert payload["final_amount"] == 1039.2
    assert payload["expires_at"] is not None


def test_booking_creation_applies_valid_promo(
    app,
    client,
    auth_headers,
    register_user,
):
    provider, skill_id = _create_provider_and_skill(client, auth_headers, register_user)
    seeker, seeker_token = register_user(
        "seeker",
        name="Promo Seeker",
        email="promo-seeker@example.com",
    )

    with app.app_context():
        seeker_record = db.session.get(User, seeker["id"])
        seeker_record.wallet_balance = Decimal("100")
        db.session.add(
            PromoCode(
                code="SAVE200",
                title="Flat Save",
                discount_type=PromoDiscountType.FIXED,
                discount_value=Decimal("200"),
                min_order_amount=Decimal("500"),
                active=True,
                expires_at=datetime.now(timezone.utc) + timedelta(days=5),
            )
        )
        db.session.commit()

    scheduled_at = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0).isoformat()
    response = client.post(
        "/api/bookings",
        headers=auth_headers(seeker_token),
        json={
            "skill_id": skill_id,
            "provider_id": provider["id"],
            "scheduled_at": scheduled_at,
            "duration_minutes": 60,
            "promo_code": "save200",
        },
    )

    assert response.status_code == 201, response.get_json()
    payload = response.get_json()
    assert payload["wallet_used"] == 100.0
    assert payload["promo_code"] == "SAVE200"
    assert payload["promo_discount"] == 200.0
    assert payload["payable_amount"] == 900.0


def test_validate_promo_rejects_minimum_amount(app, client):
    with app.app_context():
        db.session.add(
            PromoCode(
                code="MIN500",
                title="Threshold Promo",
                discount_type=PromoDiscountType.FIXED,
                discount_value=Decimal("100"),
                min_order_amount=Decimal("500"),
                active=True,
                expires_at=datetime.now(timezone.utc) + timedelta(days=5),
            )
        )
        db.session.commit()

    response = client.post(
        "/api/promos/validate",
        json={"code": "MIN500", "booking_amount": 300},
    )

    assert response.status_code == 409
    assert response.get_json() == {"valid": False, "message": "Minimum INR 500 required"}


def test_validate_promo_with_jwt_auth(
    app,
    client,
    register_user,
    auth_headers,
):
    seeker, seeker_token = register_user(
        "seeker",
        name="Auth Seeker",
        email="auth-seeker-promo@example.com",
    )

    with app.app_context():
        db.session.add(
            PromoCode(
                code="AUTH100",
                title="Auth User Discount",
                discount_type=PromoDiscountType.FIXED,
                discount_value=Decimal("100"),
                min_order_amount=Decimal("500"),
                active=True,
                expires_at=datetime.now(timezone.utc) + timedelta(days=5),
            )
        )
        db.session.commit()

    response = client.post(
        "/api/promos/validate",
        headers=auth_headers(seeker_token),
        json={"code": "AUTH100", "booking_amount": 600},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["valid"] is True
    assert payload["discount_amount"] == 100.0

