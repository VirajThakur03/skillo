from app.extensions import db
from app.models import Notification, NotificationCategory, NotificationDelivery
from app.services.marketplace import create_notification


def test_persisted_notification_survives_live_emit_failure(
    app,
    client,
    register_user,
    auth_headers,
    monkeypatch,
):
    seeker, token = register_user(
        "seeker",
        name="Notify Seeker",
        email="notify-seeker@example.com",
    )

    def _raise_emit(*args, **kwargs):
        raise RuntimeError("socket offline during test")

    monkeypatch.setattr("app.services.marketplace.socketio.emit", _raise_emit)

    with app.app_context():
        notification = create_notification(
            recipient_id=seeker["id"],
            category=NotificationCategory.BOOKING_UPDATE,
            title="Booking updated",
            body="Your booking is confirmed.",
            entity_type="booking",
            entity_id=123,
            template_key="booking.confirmed",
        )
        db.session.commit()
        assert notification.id is not None

        persisted = Notification.query.filter_by(recipient_user_id=seeker["id"]).one()
        assert persisted.title == "Booking updated"
        deliveries = NotificationDelivery.query.filter_by(notification_id=persisted.id).all()
        assert deliveries

    unread = client.get("/api/notifications/unread-count", headers=auth_headers(token))
    assert unread.status_code == 200
    assert unread.get_json()["count"] == 1

    listing = client.get("/api/notifications", headers=auth_headers(token))
    assert listing.status_code == 200
    items = listing.get_json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Booking updated"
