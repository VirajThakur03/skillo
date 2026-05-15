from datetime import datetime, timezone

from flask import current_app

from .feature_flags import feature_enabled


def send_push(recipient, title, body, data=None):
    if not feature_enabled("push_notifications"):
        return {"status": "skipped", "error_code": "feature_disabled", "error_message": "Push notifications are disabled."}

    token = getattr(recipient, "fcm_token", None) or getattr(recipient, "push_token", None)
    backend = (current_app.config.get("PUSH_DELIVERY_BACKEND") or "log").lower()
    if backend == "log":
        current_app.logger.info(
            "push.notification.sent",
            extra={
                "recipient_user_id": recipient.id,
                "title": title,
                "body": body,
                "data": data or {},
            },
        )
        return {"status": "delivered", "payload": {"title": title, "body": body, "data": data or {}}}
    if not token:
        return {"status": "skipped", "error_code": "missing_push_token", "error_message": "Recipient has no push token."}
    return {"status": "skipped", "error_code": "unsupported_backend", "error_message": f"Push backend '{backend}' is not configured."}


def send_email(recipient, title, body):
    if not feature_enabled("email_notifications"):
        return {"status": "skipped", "error_code": "feature_disabled", "error_message": "Email notifications are disabled."}

    if not recipient.email:
        return {"status": "skipped", "error_code": "missing_email", "error_message": "Recipient has no email address."}

    backend = (current_app.config.get("EMAIL_DELIVERY_BACKEND") or "log").lower()
    if backend == "log":
        current_app.logger.info(
            "email.notification.sent",
            extra={
                "recipient_user_id": recipient.id,
                "email": recipient.email,
                "subject": title,
                "body": body,
                "sent_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return {"status": "delivered", "payload": {"subject": title, "body": body}}
    return {"status": "skipped", "error_code": "unsupported_backend", "error_message": f"Email backend '{backend}' is not configured."}
