from flask import Blueprint, abort, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import db, JobPost, JobProposal, JobPostStatus, JobProposalStatus, User, RoleEnum, Booking, BookingStatus, PaymentStatus, MessageType
from app.config import Config
from datetime import datetime, timezone, timedelta
from decimal import Decimal

jobs_bp = Blueprint("jobs", __name__)


def _job_posts_enabled():
    return bool(current_app.config.get("FEATURE_JOB_POSTS", False))


def _feature_disabled_response():
    return jsonify({"error": "job posts feature is disabled"}), 404


def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _expire_stale_jobs():
    from app.services.notification_triggers import notify_job_post_expired

    now = _utcnow_naive()
    changed = False

    stale_open_cutoff = now - timedelta(
        hours=int(current_app.config.get("JOB_POST_OPEN_EXPIRY_HOURS", 72) or 72)
    )
    stale_open_jobs = (
        JobPost.query.filter(
            JobPost.status == JobPostStatus.OPEN,
            JobPost.created_at.isnot(None),
            JobPost.created_at < stale_open_cutoff,
        )
        .all()
    )
    for job in stale_open_jobs:
        job.status = JobPostStatus.EXPIRED
        job.closed_at = now
        try:
            notify_job_post_expired(job=job)
        except Exception as exc:
            current_app.logger.error(
                "jobs.expiry_notification_failed",
                extra={"job_id": job.id, "error": str(exc)},
            )
        changed = True

    stale_selected_jobs = (
        JobPost.query.filter(
            JobPost.status == JobPostStatus.PROVIDER_FOUND,
            JobPost.provider_found_visible_until.isnot(None),
            JobPost.provider_found_visible_until < now,
        )
        .all()
    )
    for job in stale_selected_jobs:
        job.status = JobPostStatus.BOOKED if job.selected_provider_id else JobPostStatus.EXPIRED
        if job.closed_at is None:
            job.closed_at = now
        changed = True

    if changed:
        db.session.commit()


def _public_job_query():
    now = _utcnow_naive()
    return JobPost.query.filter(
        (JobPost.status == JobPostStatus.OPEN)
        | (
            (JobPost.status == JobPostStatus.PROVIDER_FOUND)
            & (JobPost.provider_found_visible_until.isnot(None))
            & (JobPost.provider_found_visible_until > now)
        )
    )


def _serialize_job(job, *, include_owner=False):
    payload = {
        "id": job.id,
        "title": job.title,
        "description": job.description,
        "budget_min": str(job.budget_min) if job.budget_min else None,
        "budget_max": str(job.budget_max) if job.budget_max else None,
        "currency": job.currency,
        "location": job.location_text,
        "status": job.status.value,
        "selected_provider_id": job.selected_provider_id,
        "selected_at": job.selected_at.isoformat() if job.selected_at else None,
        "provider_found_visible_until": (
            job.provider_found_visible_until.isoformat()
            if job.provider_found_visible_until
            else None
        ),
        "cancel_allowed_until": (
            job.cancel_allowed_until.isoformat() if job.cancel_allowed_until else None
        ),
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }
    if include_owner:
        payload["seeker_id"] = job.seeker_id
    return payload

def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        # Standard format: 2024-04-25T14:30:00Z
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None

@jobs_bp.route("/api/jobs", methods=["POST"])
@jwt_required()
def create_job():
    if not _job_posts_enabled():
        return _feature_disabled_response()

    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user or user.role != RoleEnum.SEEKER:
        return jsonify({"error": "Only seekers can post jobs"}), 403

    data = request.get_json() or {}
    title = data.get("title")
    if not title:
        return jsonify({"error": "Job title is required"}), 400
    title = str(title).strip()
    if not title:
        return jsonify({"error": "Job title is required"}), 400
    if len(title) > 255:
        return jsonify({"error": "Job title is too long"}), 400

    budget_min = Decimal(str(data.get("budget_min", 0))) if data.get("budget_min") else None
    budget_max = Decimal(str(data.get("budget_max", 0))) if data.get("budget_max") else None
    if budget_min is not None and budget_min < 0:
        return jsonify({"error": "Budget cannot be negative"}), 400
    if budget_max is not None and budget_max < 0:
        return jsonify({"error": "Budget cannot be negative"}), 400
    if budget_min is not None and budget_max is not None and budget_min > budget_max:
        return jsonify({"error": "Minimum budget cannot exceed maximum budget"}), 400

    job = JobPost(
        seeker_id=user_id,
        title=title,
        description=data.get("description"),
        budget_min=budget_min,
        budget_max=budget_max,
        location_text=data.get("location_text"),
        scheduled_for=_parse_iso_datetime(data.get("scheduled_for"))
    )
    
    db.session.add(job)
    db.session.commit()
    
    return jsonify({"id": job.id, "status": job.status.value}), 201


@jobs_bp.route("/api/jobs", methods=["GET"])
def list_public_jobs():
    """Public board: list all OPEN jobs."""
    if not _job_posts_enabled():
        return _feature_disabled_response()

    _expire_stale_jobs()
    jobs = _public_job_query().order_by(JobPost.created_at.desc()).all()
    return jsonify([_serialize_job(job) for job in jobs])


@jobs_bp.route("/api/jobs/mine", methods=["GET"])
@jwt_required()
def list_my_jobs():
    if not _job_posts_enabled():
        return _feature_disabled_response()

    user_id = int(get_jwt_identity())
    _expire_stale_jobs()
    jobs = JobPost.query.filter_by(seeker_id=user_id).order_by(JobPost.created_at.desc()).all()
    return jsonify([
        {
            "id": j.id,
            "title": j.title,
            "status": j.status.value,
            "proposal_count": JobProposal.query.filter_by(job_post_id=j.id, status=JobProposalStatus.ACTIVE).count(),
            "created_at": j.created_at.isoformat()
        } for j in jobs
    ])


@jobs_bp.route("/api/jobs/<int:job_id>", methods=["GET"])
@jwt_required()
def get_job(job_id):
    if not _job_posts_enabled():
        return _feature_disabled_response()

    _expire_stale_jobs()
    job = db.session.get(JobPost, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    return jsonify(_serialize_job(job, include_owner=True))


@jobs_bp.route("/api/jobs/<int:job_id>/proposals", methods=["POST"])
@jwt_required()
def create_proposal(job_id):
    if not _job_posts_enabled():
        return _feature_disabled_response()

    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user or user.role != RoleEnum.PROVIDER:
        return jsonify({"error": "Only providers can submit proposals"}), 403

    job = db.session.get(JobPost, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    _expire_stale_jobs()
    db.session.refresh(job)
    if job.seeker_id == user_id:
        return jsonify({"error": "You cannot propose to your own job"}), 400

    if job.status != JobPostStatus.OPEN:
        return jsonify({"error": "Job is no longer open for proposals"}), 400

    # Check for existing proposal
    existing = JobProposal.query.filter_by(job_post_id=job_id, provider_id=user_id, status=JobProposalStatus.ACTIVE).first()
    if existing:
        return jsonify({"error": "You have already submitted an active proposal for this job"}), 400

    data = request.get_json() or {}
    quoted_amount = data.get("quoted_amount")
    if quoted_amount is None:
        return jsonify({"error": "Quoted amount is required"}), 400

    proposal = JobProposal(
        job_post_id=job_id,
        provider_id=user_id,
        cover_message=data.get("cover_message"),
        quoted_amount=Decimal(str(quoted_amount)),
        estimated_duration_minutes=data.get("estimated_duration_minutes", 60),
        available_from=_parse_iso_datetime(data.get("available_from"))
    )
    
    db.session.add(proposal)
    db.session.flush()

    # Notify seeker
    from app.services.notification_triggers import notify_new_proposal
    try:
        notify_new_proposal(job=job, proposal=proposal)
    except Exception as exc:
        current_app.logger.error(
            "jobs.proposal_notification_failed",
            extra={"job_id": job.id, "proposal_id": proposal.id, "error": str(exc)},
        )

    db.session.commit()
    
    return jsonify({"id": proposal.id, "status": proposal.status.value}), 201


@jobs_bp.route("/api/jobs/<int:job_id>/proposals", methods=["GET"])
@jwt_required()
def list_proposals(job_id):
    if not _job_posts_enabled():
        return _feature_disabled_response()

    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "unauthenticated"}), 401

    _expire_stale_jobs()
    job = db.session.get(JobPost, job_id)
    
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Seekers see all proposals for their job
    if job.seeker_id == user_id:
        proposals = JobProposal.query.filter_by(job_post_id=job_id).order_by(JobProposal.created_at.desc()).all()
    elif user.role == RoleEnum.PROVIDER:
        # Providers see only their own
        proposals = JobProposal.query.filter_by(job_post_id=job_id, provider_id=user_id).all()
    else:
        return jsonify({"error": "forbidden"}), 403

    return jsonify([
        {
            "id": p.id,
            "provider_id": p.provider_id,
            "provider_name": p.provider.name,
            "quoted_amount": str(p.quoted_amount),
            "cover_message": p.cover_message,
            "status": p.status.value,
            "created_at": p.created_at.isoformat()
        } for p in proposals
    ])


@jobs_bp.route("/api/jobs/<int:job_id>/select-provider", methods=["POST"])
@jwt_required()
def select_provider(job_id):
    if not _job_posts_enabled():
        return _feature_disabled_response()

    user_id = int(get_jwt_identity())
    _expire_stale_jobs()
    job = db.session.get(JobPost, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    
    if job.seeker_id != user_id:
        return jsonify({"error": "Only the job owner can select a provider"}), 403
    
    if job.status != JobPostStatus.OPEN:
        return jsonify({"error": f"Job is currently {job.status.value}"}), 400

    data = request.get_json() or {}
    proposal_id = data.get("proposal_id")
    if not proposal_id:
        return jsonify({"error": "proposal_id is required"}), 400
    
    proposal = db.session.get(JobProposal, proposal_id)
    if not proposal or proposal.job_post_id != job_id:
        return jsonify({"error": "Invalid proposal"}), 400
    
    if proposal.status != JobProposalStatus.ACTIVE:
        return jsonify({"error": "Proposal is no longer active"}), 400

    now = _utcnow_naive()

    try:
        # Update Job Post
        job.status = JobPostStatus.PROVIDER_FOUND
        job.selected_provider_id = proposal.provider_id
        job.selected_at = now
        job.provider_found_visible_until = now + timedelta(hours=3)
        job.cancel_allowed_until = now + timedelta(hours=2)

        # Update Proposals
        proposal.status = JobProposalStatus.SELECTED
        JobProposal.query.filter(
            JobProposal.job_post_id == job_id,
            JobProposal.id != proposal_id,
        ).update({JobProposal.status: JobProposalStatus.REJECTED}, synchronize_session=False)

        from app.services.booking_service import create_booking_from_job
        booking = create_booking_from_job(job, proposal)

        from app.services.notification_triggers import notify_proposal_selected
        notify_proposal_selected(job=job, proposal=proposal, booking_id=booking.id)

        room = f"booking_{booking.id}"
        from app.routes.chat import _persist_message

        _persist_message(
            room,
            sender_id=None,
            content=f"Provider selected for job: {job.title}. Use this chat for further coordination.",
            message_type=MessageType.TEXT,
            commit=False,
        )

        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "jobs.select_provider_failed",
            extra={"job_id": job_id, "proposal_id": proposal_id, "error": str(exc)},
        )
        return jsonify({"error": "Unable to complete provider selection right now"}), 500

    return jsonify(
        {
            "message": "Provider selected and booking created",
            "booking_id": booking.id,
            "job_status": job.status.value,
            "provider_found_visible_until": job.provider_found_visible_until.isoformat(),
            "cancel_allowed_until": job.cancel_allowed_until.isoformat(),
        }
    )


@jobs_bp.route("/api/jobs/<int:job_id>/cancel-selected-provider", methods=["POST"])
@jwt_required()
def cancel_selected_provider(job_id):
    if not _job_posts_enabled():
        return _feature_disabled_response()

    user_id = int(get_jwt_identity())
    _expire_stale_jobs()
    job = db.session.get(JobPost, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    
    if job.seeker_id != user_id:
        return jsonify({"error": "Only the job owner can cancel the selection"}), 403
    
    if job.status != JobPostStatus.PROVIDER_FOUND:
        return jsonify({"error": "No provider is currently selected for this job"}), 400

    now = _utcnow_naive()
    if now > job.cancel_allowed_until:
        return jsonify({"error": "Cancellation window (2 hours) has expired"}), 400

    # Reset job
    job.status = JobPostStatus.OPEN
    job.selected_provider_id = None
    job.selected_at = None
    job.provider_found_visible_until = None
    job.cancel_allowed_until = None
    
    # Update proposals - reset the selected one back to active
    JobProposal.query.filter_by(job_post_id=job_id, status=JobProposalStatus.SELECTED).update(
        {JobProposal.status: JobProposalStatus.ACTIVE}
    )
    
    # Cancel the booking
    booking = Booking.query.filter_by(job_post_id=job_id, status=BookingStatus.PENDING).first()
    if booking:
        booking.status = BookingStatus.CANCELLED
        booking.cancellation_reason = "job_selection_cancelled_by_seeker"

    db.session.commit()
    
    return jsonify({"message": "Selection cancelled. Job is now open again."})
