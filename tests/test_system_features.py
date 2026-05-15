def test_system_features_endpoint_returns_expected_shape(app, client):
    app.config.update(
        FEATURE_AVAILABILITY_CALENDAR=True,
        FEATURE_PUSH_NOTIFICATIONS=False,
        FEATURE_EMAIL_NOTIFICATIONS=True,
        FEATURE_PROMO_CODES=True,
        FEATURE_REFERRAL_REWARDS=True,
        FEATURE_WALLET=False,
        FEATURE_WEEKLY_AVAILABILITY=True,
        FEATURE_CHAT_READ_RECEIPTS=True,
        FEATURE_PROVIDER_REPLY_REVIEW=False,
        FEATURE_JOB_POSTS=True,
    )

    response = client.get("/api/system/features")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=60"
    payload = response.get_json()
    assert payload == {
        "availability_calendar": True,
        "push_notifications": False,
        "email_notifications": True,
        "promo_codes": True,
        "referral_rewards": True,
        "wallet": False,
        "weekly_availability": True,
        "chat_read_receipts": True,
        "provider_reply_review": False,
        "job_posts": True,
    }


def test_base_template_exposes_feature_flag_and_jobs_fallback_link(client, app):
    app.config["FEATURE_JOB_POSTS"] = True
    response = client.get("/home")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-feature-job-posts="true"' in html
    assert 'Browse Jobs' in html

    app.config["FEATURE_JOB_POSTS"] = False
    response = client.get("/home")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-feature-job-posts="false"' in html
