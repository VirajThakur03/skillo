from flask import current_app


def feature_enabled(name):
    mapping = {
        "availability_calendar": "FEATURE_AVAILABILITY_CALENDAR",
        "push_notifications": "FEATURE_PUSH_NOTIFICATIONS",
        "email_notifications": "FEATURE_EMAIL_NOTIFICATIONS",
        "promo_codes": "FEATURE_PROMO_CODES",
        "referral_rewards": "FEATURE_REFERRAL_REWARDS",
        "wallet": "FEATURE_WALLET",
        "weekly_availability": "FEATURE_WEEKLY_AVAILABILITY",
        "chat_read_receipts": "FEATURE_CHAT_READ_RECEIPTS",
        "provider_reply_review": "FEATURE_PROVIDER_REPLY_REVIEW",
        "job_posts": "FEATURE_JOB_POSTS",
    }
    config_key = mapping.get(name)
    if not config_key:
        return False
    return bool(current_app.config.get(config_key, False))


def frontend_feature_payload():
    return {
        "availability_calendar": feature_enabled("availability_calendar"),
        "push_notifications": feature_enabled("push_notifications"),
        "email_notifications": feature_enabled("email_notifications"),
        "promo_codes": feature_enabled("promo_codes"),
        "referral_rewards": feature_enabled("referral_rewards"),
        "wallet": feature_enabled("wallet"),
        "weekly_availability": feature_enabled("weekly_availability"),
        "chat_read_receipts": feature_enabled("chat_read_receipts"),
        "provider_reply_review": feature_enabled("provider_reply_review"),
        "job_posts": feature_enabled("job_posts"),
    }
