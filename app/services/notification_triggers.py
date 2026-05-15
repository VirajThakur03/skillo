from ..models import NotificationCategory, NotificationPriority
from .marketplace import create_notification


def notify_new_chat_message(*, recipient_id, sender_name, content, conversation_id, booking_id=None):
    preview = content.strip()
    if len(preview) > 60:
        preview = f"{preview[:57]}..."
    return create_notification(
        recipient_id=recipient_id,
        category=NotificationCategory.CHAT_MENTION,
        priority=NotificationPriority.NORMAL,
        title=f"New message from {sender_name}",
        body=preview or "Open chat to view the message.",
        entity_type="booking" if booking_id else "chat",
        entity_id=booking_id or conversation_id,
        deep_link=f"/chat/{conversation_id}",
        template_key="chat.new_message",
    )


def notify_booking_status_change(*, booking, new_status, changed_by_role=None, refund_amount=None):
    provider_name = getattr(booking.provider, "name", "Your provider")
    when = booking.scheduled_at.strftime("%d %b, %I:%M %p") if booking.scheduled_at else "soon"

    if new_status == "confirmed":
        return create_notification(
            recipient_id=booking.seeker_id,
            category=NotificationCategory.BOOKING_UPDATE,
            title="Your booking is confirmed!",
            body=f"{provider_name} will arrive {when}.",
            entity_type="booking",
            entity_id=booking.id,
            deep_link=f"/track/{booking.id}",
            template_key="booking.confirmed",
        )

    if new_status == "declined":
        return create_notification(
            recipient_id=booking.seeker_id,
            category=NotificationCategory.BOOKING_UPDATE,
            title="Provider couldn't accept",
            body="We're finding alternatives for your booking.",
            entity_type="booking",
            entity_id=booking.id,
            deep_link=f"/track/{booking.id}",
            template_key="booking.declined",
        )

    if new_status == "completed":
        return create_notification(
            recipient_id=booking.seeker_id,
            category=NotificationCategory.BOOKING_UPDATE,
            title="Booking complete",
            body="How was your experience? Leave a review from the booking page.",
            entity_type="booking",
            entity_id=booking.id,
            deep_link=f"/track/{booking.id}",
            template_key="booking.completed",
        )

    if new_status == "cancelled":
        refund_line = f" Refund: INR {float(refund_amount or 0):.0f}." if refund_amount is not None else ""
        for recipient_id in {booking.seeker_id, booking.provider_id}:
            create_notification(
                recipient_id=recipient_id,
                category=NotificationCategory.BOOKING_UPDATE,
                title="Booking cancelled",
                body=f"Booking #{booking.id} was cancelled.{refund_line}",
                entity_type="booking",
                entity_id=booking.id,
                deep_link=f"/track/{booking.id}",
                template_key="booking.cancelled",
            )
        return None

    return None

def notify_new_proposal(*, job, proposal):
    return create_notification(
        recipient_id=job.seeker_id,
        category=NotificationCategory.QUOTE_UPDATE,
        priority=NotificationPriority.NORMAL,
        title="New Proposal Received",
        body=f"You have a new proposal of INR {proposal.quoted_amount} for your job: {job.title}",
        entity_type="job_post",
        entity_id=job.id,
        deep_link=f"/jobs/{job.id}",
        template_key="job.new_proposal",
    )

def notify_proposal_selected(*, job, proposal, booking_id):
    return create_notification(
        recipient_id=proposal.provider_id,
        category=NotificationCategory.BOOKING_UPDATE,
        priority=NotificationPriority.HIGH,
        title="You've been selected!",
        body=f"You were selected for the job: {job.title}. A new booking has been created.",
        entity_type="booking",
        entity_id=booking_id,
        deep_link=f"/track/{booking_id}",
        template_key="job.proposal_selected",
    )


def notify_job_post_expired(*, job):
    return create_notification(
        recipient_id=job.seeker_id,
        category=NotificationCategory.QUOTE_UPDATE,
        priority=NotificationPriority.NORMAL,
        title="Your job post expired",
        body=f"Your job post '{job.title}' expired before a provider was selected.",
        entity_type="job_post",
        entity_id=job.id,
        deep_link="/my-jobs",
        template_key="job.expired",
    )
