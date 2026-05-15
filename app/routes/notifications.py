from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from ..extensions import db
from ..models import (
    Notification,
    NotificationCategory,
    NotificationDelivery,
    NotificationPreference,
    User,
)
from ..services.marketplace import (
    create_notification,
    get_or_create_notification_preference,
    is_admin_user,
)

notifications_bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")


NOTIFICATION_TEMPLATES = {
    "booking.accepted": {
        "title": "Booking confirmed",
        "body": "Your provider has confirmed the booking.",
    },
    "booking.cancelled": {
        "title": "Booking cancelled",
        "body": "Your booking has been cancelled.",
    },
    "quote.received": {
        "title": "New quote received",
        "body": "A provider sent you a quote.",
    },
}


def _current_user():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return None, ({"error": "unauthenticated"}, 401)
    return user, None


def _serialize_notification(item):
    return {
        "id": item.id,
        "category": item.category.value,
        "priority": item.priority.value,
        "title": item.title,
        "body": item.body,
        "deep_link": item.deep_link,
        "entity_type": item.entity_type,
        "entity_id": item.entity_id,
        "read": item.read_at is not None,
        "created_at": item.created_at.isoformat(),
    }


@notifications_bp.route("", methods=["GET"])
@jwt_required()
def list_notifications():
    user, error = _current_user()
    if error:
        return error

    unread_only = request.args.get("unread") == "true"
    query = Notification.query.filter_by(recipient_user_id=user.id, deleted_at=None)
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))

    items = query.order_by(Notification.created_at.desc()).limit(100).all()
    return {"items": [_serialize_notification(item) for item in items]}, 200


@notifications_bp.route("/<int:notification_id>/read", methods=["POST"])
@jwt_required()
def mark_notification_read(notification_id):
    user, error = _current_user()
    if error:
        return error

    notification = Notification.query.filter_by(
        id=notification_id,
        recipient_user_id=user.id,
        deleted_at=None,
    ).first()
    if not notification:
        return {"error": "notification not found"}, 404

    if notification.read_at is None:
        notification.read_at = db.func.now()
        db.session.commit()
    return {"success": True}, 200


@notifications_bp.route("/read-all", methods=["POST"])
@jwt_required()
def mark_all_read():
    user, error = _current_user()
    if error:
        return error

    Notification.query.filter_by(
        recipient_user_id=user.id,
        deleted_at=None,
    ).filter(Notification.read_at.is_(None)).update({"read_at": db.func.now()})
    db.session.commit()
    return {"success": True}, 200


@notifications_bp.route("/unread-count", methods=["GET"])
@jwt_required()
def unread_count():
    user, error = _current_user()
    if error:
        return error
    count = Notification.query.filter_by(
        recipient_user_id=user.id, 
        read_at=None
    ).count()
    return {"count": count}, 200


@notifications_bp.route("/preferences", methods=["GET"])
@jwt_required()
def get_preferences():
    user, error = _current_user()
    if error:
        return error

    preference = get_or_create_notification_preference(user.id)
    db.session.commit()
    return {
        "push_enabled": preference.push_enabled,
        "email_enabled": preference.email_enabled,
        "whatsapp_enabled": preference.whatsapp_enabled,
        "category_channels": preference.category_channels,
        "quiet_hours_enabled": preference.quiet_hours_enabled,
        "quiet_start_local": preference.quiet_start_local,
        "quiet_end_local": preference.quiet_end_local,
    }, 200


@notifications_bp.route("/preferences", methods=["PUT"])
@jwt_required()
def save_preferences():
    user, error = _current_user()
    if error:
        return error

    preference = get_or_create_notification_preference(user.id)
    data = request.get_json() or {}
    preference.push_enabled = bool(data.get("push_enabled", preference.push_enabled))
    preference.email_enabled = bool(data.get("email_enabled", preference.email_enabled))
    preference.whatsapp_enabled = bool(data.get("whatsapp_enabled", preference.whatsapp_enabled))
    preference.category_channels = data.get("category_channels") or preference.category_channels or {}
    preference.quiet_hours_enabled = bool(data.get("quiet_hours_enabled", preference.quiet_hours_enabled))
    preference.quiet_start_local = data.get("quiet_start_local")
    preference.quiet_end_local = data.get("quiet_end_local")
    db.session.commit()
    return {"success": True}, 200


@notifications_bp.route("/admin/templates", methods=["GET"])
@jwt_required()
def admin_templates():
    user, error = _current_user()
    if error:
        return error
    if not is_admin_user(user):
        return {"error": "admin only"}, 403

    return {"items": NOTIFICATION_TEMPLATES}, 200


@notifications_bp.route("/admin/templates/<template_key>/test-send", methods=["POST"])
@jwt_required()
def admin_test_send(template_key):
    user, error = _current_user()
    if error:
        return error
    if not is_admin_user(user):
        return {"error": "admin only"}, 403
    if template_key not in NOTIFICATION_TEMPLATES:
        return {"error": "template not found"}, 404

    data = request.get_json() or {}
    recipient_id = int(data.get("recipient_user_id") or user.id)
    template = NOTIFICATION_TEMPLATES[template_key]
    create_notification(
        recipient_id=recipient_id,
        category=NotificationCategory.BOOKING_UPDATE,
        title=template["title"],
        body=template["body"],
        template_key=template_key,
    )
    db.session.commit()
    return {"success": True}, 202


@notifications_bp.route("/admin/deliveries", methods=["GET"])
@jwt_required()
def admin_delivery_log():
    user, error = _current_user()
    if error:
        return error
    if not is_admin_user(user):
        return {"error": "admin only"}, 403

    deliveries = NotificationDelivery.query.order_by(NotificationDelivery.id.desc()).limit(100).all()
    return {
        "items": [
            {
                "id": delivery.id,
                "notification_id": delivery.notification_id,
                "channel": delivery.channel.value,
                "status": delivery.status.value,
                "template_key": delivery.template_key,
                "error_code": delivery.error_code,
                "error_message": delivery.error_message,
            }
            for delivery in deliveries
        ]
    }, 200
