from decimal import Decimal

from app.extensions import db
from app.models import ReferralReward, ReferralRewardStatus, User


def test_get_referrals_returns_stats_and_items(app, client, register_user, auth_headers):
    referrer, referrer_token = register_user(
        "seeker",
        name="Referrer User",
        email="referrer@example.com",
    )
    referred, _referred_token = register_user(
        "seeker",
        name="Referred User",
        email="referred@example.com",
    )

    with app.app_context():
        referrer_record = db.session.get(User, referrer["id"])
        referred_record = db.session.get(User, referred["id"])
        referred_record.referred_by_id = referrer_record.id
        referrer_record.wallet_balance = Decimal("250")
        db.session.add(
            ReferralReward(
                referrer_user_id=referrer_record.id,
                referred_user_id=referred_record.id,
                status=ReferralRewardStatus.PAID,
                reward_amount=Decimal("100"),
                note="Credited after first completed booking.",
            )
        )
        db.session.commit()

    response = client.get("/api/referrals", headers=auth_headers(referrer_token))
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["code"]
    assert payload["total_referred"] == 1
    assert payload["wallet_credit_earned"] == 100.0
    assert len(payload["items"]) == 1
    assert payload["items"][0]["reward_status"] == "PAID"


def test_apply_referral_code_sets_referrer_and_creates_pending_reward(
    app,
    client,
    register_user,
    auth_headers,
):
    referrer, _referrer_token = register_user(
        "seeker",
        name="Share Owner",
        email="share-owner@example.com",
    )
    friend, friend_token = register_user(
        "seeker",
        name="Joining Friend",
        email="joining-friend@example.com",
    )

    with app.app_context():
        code = db.session.get(User, referrer["id"]).referral_code

    response = client.post(
        "/api/referrals/apply",
        headers=auth_headers(friend_token),
        json={"code": code},
    )
    assert response.status_code == 200

    with app.app_context():
        friend_record = db.session.get(User, friend["id"])
        assert friend_record.referred_by_id == referrer["id"]
        reward = ReferralReward.query.filter_by(referred_user_id=friend["id"]).first()
        assert reward is not None
        assert reward.status == ReferralRewardStatus.PENDING


def test_wallet_endpoint_includes_rewards_and_spends(app, client, register_user, auth_headers):
    user, user_token = register_user(
        "seeker",
        name="Wallet Owner",
        email="wallet-owner@example.com",
    )
    referred, _referred_token = register_user(
        "seeker",
        name="Wallet Friend",
        email="wallet-friend@example.com",
    )

    with app.app_context():
        user_record = db.session.get(User, user["id"])
        user_record.wallet_balance = Decimal("180")
        db.session.add(
            ReferralReward(
                referrer_user_id=user_record.id,
                referred_user_id=referred["id"],
                status=ReferralRewardStatus.EARNED,
                reward_amount=Decimal("100"),
                note="Earned reward.",
            )
        )
        db.session.commit()

    response = client.get("/api/wallet", headers=auth_headers(user_token))
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["balance"] == 180.0
    assert len(payload["transactions"]) == 1
    assert payload["transactions"][0]["type"] == "referral_reward"


def test_referral_reward_processed_on_booking_completion(
    app,
    client,
    register_user,
    auth_headers,
):
    from datetime import datetime, timezone, timedelta
    from app.models import Booking, BookingStatus, PaymentStatus

    # Create referrer, provider, and seeker (referred user)
    referrer, _referrer_token = register_user(
        "seeker",
        name="Referrer Seeker",
        email="ref-seeker@example.com",
    )
    provider, provider_token = register_user(
        "provider",
        name="Referral Provider",
        email="ref-provider@example.com",
    )
    friend, friend_token = register_user(
        "seeker",
        name="Referred Friend",
        email="ref-friend@example.com",
    )

    with app.app_context():
        # Set friend as referred by referrer
        friend_record = db.session.get(User, friend["id"])
        friend_record.referred_by_id = referrer["id"]
        
        # Add a pending ReferralReward row
        db.session.add(
            ReferralReward(
                referrer_user_id=referrer["id"],
                referred_user_id=friend["id"],
                status=ReferralRewardStatus.PENDING,
                reward_amount=Decimal("100"),
                note="Pending first booking.",
            )
        )
        
        # Create a confirmed and paid booking for the friend
        booking = Booking(
            seeker_id=friend["id"],
            provider_id=provider["id"],
            skill_id=1,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            duration_minutes=60,
            price=1200,
            currency="INR",
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.CAPTURED,
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

    # Complete the booking
    response = client.post(
        f"/api/bookings/{booking_id}/complete",
        headers=auth_headers(provider_token),
    )
    assert response.status_code == 200

    # Check referrer's wallet and reward status
    with app.app_context():
        referrer_record = db.session.get(User, referrer["id"])
        assert float(referrer_record.wallet_balance) == 100.0
        
        reward = ReferralReward.query.filter_by(referred_user_id=friend["id"]).first()
        assert reward.status == ReferralRewardStatus.EARNED
        assert reward.booking_id == booking_id

