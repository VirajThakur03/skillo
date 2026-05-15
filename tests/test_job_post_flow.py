from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.extensions import db
from app.models import (
    Booking,
    BookingStatus,
    JobPost,
    JobPostStatus,
    JobProposal,
    JobProposalStatus,
    Message,
    Notification,
    RoleEnum,
    User,
    VerificationStatus,
)


def _register_provider(register_user, suffix):
    return register_user(
        "provider",
        name=f"Provider {suffix}",
        email=f"provider-{suffix}@example.com",
    )


def test_job_post_feature_flag_blocks_routes(app, client):
    app.config["FEATURE_JOB_POSTS"] = False

    response = client.get("/api/jobs")
    assert response.status_code == 404
    assert response.get_json()["error"] == "job posts feature is disabled"


def test_job_post_flow_create_propose_select_and_cancel(
    app,
    client,
    register_user,
    auth_headers,
):
    app.config["FEATURE_JOB_POSTS"] = True

    seeker, seeker_token = register_user(
        "seeker",
        name="Job Seeker",
        email="job-seeker@example.com",
    )
    provider_a, provider_a_token = _register_provider(register_user, "a")
    provider_b, provider_b_token = _register_provider(register_user, "b")

    with app.app_context():
        for provider_id in (provider_a["id"], provider_b["id"]):
            provider = db.session.get(User, provider_id)
            provider.is_verified = True
            provider.verification_status = VerificationStatus.completed
        db.session.commit()

    create_response = client.post(
        "/api/jobs",
        headers=auth_headers(seeker_token),
        json={
            "title": "Need an electrician",
            "description": "Install two ceiling fans",
            "budget_min": 500,
            "budget_max": 1500,
            "location_text": "Indiranagar",
        },
    )
    assert create_response.status_code == 201, create_response.get_json()
    job_id = create_response.get_json()["id"]

    proposal_a = client.post(
        f"/api/jobs/{job_id}/proposals",
        headers=auth_headers(provider_a_token),
        json={"quoted_amount": 1200, "cover_message": "Can do it tomorrow"},
    )
    proposal_b = client.post(
        f"/api/jobs/{job_id}/proposals",
        headers=auth_headers(provider_b_token),
        json={"quoted_amount": 1000, "cover_message": "Available today"},
    )
    assert proposal_a.status_code == 201, proposal_a.get_json()
    assert proposal_b.status_code == 201, proposal_b.get_json()
    proposal_a_id = proposal_a.get_json()["id"]

    select_response = client.post(
        f"/api/jobs/{job_id}/select-provider",
        headers=auth_headers(seeker_token),
        json={"proposal_id": proposal_a_id},
    )
    assert select_response.status_code == 200, select_response.get_json()
    select_payload = select_response.get_json()
    assert select_payload["job_status"] == "PROVIDER_FOUND"
    assert select_payload["booking_id"]
    assert select_payload["provider_found_visible_until"]
    assert select_payload["cancel_allowed_until"]

    with app.app_context():
        job = db.session.get(JobPost, job_id)
        assert job.status == JobPostStatus.PROVIDER_FOUND
        assert job.selected_provider_id == provider_a["id"]
        assert job.provider_found_visible_until is not None
        assert job.cancel_allowed_until is not None

        proposals = (
            JobProposal.query.filter_by(job_post_id=job_id)
            .order_by(JobProposal.provider_id.asc())
            .all()
        )
        assert [proposal.status for proposal in proposals] == [
            JobProposalStatus.SELECTED,
            JobProposalStatus.REJECTED,
        ]

        booking = Booking.query.filter_by(job_post_id=job_id).first()
        assert booking is not None
        assert booking.status == BookingStatus.PENDING
        assert booking.provider_id == provider_a["id"]

        room = f"booking_{booking.id}"
        welcome = Message.query.filter_by(room=room, sender_id=None).first()
        assert welcome is not None
        assert "Provider selected for job" in welcome.content

    cancel_response = client.post(
        f"/api/jobs/{job_id}/cancel-selected-provider",
        headers=auth_headers(seeker_token),
    )
    assert cancel_response.status_code == 200, cancel_response.get_json()

    with app.app_context():
        job = db.session.get(JobPost, job_id)
        assert job.status == JobPostStatus.OPEN
        assert job.selected_provider_id is None
        assert job.cancel_allowed_until is None

        selected_proposal = JobProposal.query.filter_by(
            job_post_id=job_id,
            provider_id=provider_a["id"],
        ).first()
        assert selected_proposal.status == JobProposalStatus.ACTIVE

        booking = Booking.query.filter_by(job_post_id=job_id).first()
        assert booking.status == BookingStatus.CANCELLED
        assert booking.cancellation_reason == "job_selection_cancelled_by_seeker"


def test_job_selection_cannot_be_cancelled_after_window(
    app,
    client,
    register_user,
    auth_headers,
):
    app.config["FEATURE_JOB_POSTS"] = True

    seeker, seeker_token = register_user(
        "seeker",
        name="Late Cancel Seeker",
        email="late-cancel-seeker@example.com",
    )
    provider, provider_token = _register_provider(register_user, "late")

    with app.app_context():
        provider_record = db.session.get(User, provider["id"])
        provider_record.is_verified = True
        provider_record.verification_status = VerificationStatus.completed
        db.session.commit()

    job_response = client.post(
        "/api/jobs",
        headers=auth_headers(seeker_token),
        json={"title": "Painter needed", "description": "One room repaint"},
    )
    job_id = job_response.get_json()["id"]

    proposal_response = client.post(
        f"/api/jobs/{job_id}/proposals",
        headers=auth_headers(provider_token),
        json={"quoted_amount": 1800},
    )
    proposal_id = proposal_response.get_json()["id"]

    select_response = client.post(
        f"/api/jobs/{job_id}/select-provider",
        headers=auth_headers(seeker_token),
        json={"proposal_id": proposal_id},
    )
    assert select_response.status_code == 200

    with app.app_context():
        job = db.session.get(JobPost, job_id)
        job.cancel_allowed_until = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        )
        db.session.commit()

    cancel_response = client.post(
        f"/api/jobs/{job_id}/cancel-selected-provider",
        headers=auth_headers(seeker_token),
    )
    assert cancel_response.status_code == 400
    assert "expired" in cancel_response.get_json()["error"].lower()


def test_stale_open_job_expiry_creates_notification(
    app,
    client,
    register_user,
    auth_headers,
):
    app.config["FEATURE_JOB_POSTS"] = True
    app.config["JOB_POST_OPEN_EXPIRY_HOURS"] = 1

    seeker, seeker_token = register_user(
        "seeker",
        name="Expiry Seeker",
        email="expiry-seeker@example.com",
    )

    create_response = client.post(
        "/api/jobs",
        headers=auth_headers(seeker_token),
        json={"title": "Expired job", "description": "Old listing"},
    )
    assert create_response.status_code == 201
    job_id = create_response.get_json()["id"]

    with app.app_context():
        job = db.session.get(JobPost, job_id)
        job.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
        db.session.commit()

    board = client.get("/api/jobs")
    assert board.status_code == 200

    with app.app_context():
        job = db.session.get(JobPost, job_id)
        assert job.status == JobPostStatus.EXPIRED
        notification = Notification.query.filter_by(recipient_user_id=seeker["id"]).order_by(Notification.id.desc()).first()
        assert notification is not None
        assert "expired" in notification.title.lower()
