# app/routes/front.py
import os
from flask import Blueprint, abort, current_app, redirect, render_template, request, send_from_directory
from ..models import Skill, User, Booking, Review, KycStatus
from ..extensions import db
from ..services.provider_metrics import (
    batch_provider_acceptance_counts,
    metrics_for_kyc_approved_provider,
)
from flask_jwt_extended import jwt_required, get_jwt_identity

front_bp = Blueprint("front", __name__)


@front_bp.route("/favicon.ico")
def favicon():
    static_dir = os.path.join(current_app.root_path, "static", "images")
    return send_from_directory(static_dir, "logo.png", mimetype="image/png")


@front_bp.route("/sw.js")
def service_worker():
    static_dir = os.path.join(current_app.root_path, "static")
    return send_from_directory(static_dir, "sw.js", mimetype="application/javascript")


def _job_posts_enabled():
    return bool(current_app.config.get("FEATURE_JOB_POSTS", False))


def _provider_cancellation_policy(provider):
    cutoff_hours = int(getattr(provider, "cancellation_cutoff_hours", 2) or 2)
    fee_percent = int(getattr(provider, "cancellation_fee_pct", 20) or 20)
    return {
        "cutoff_hours": cutoff_hours,
        "fee_percent": fee_percent,
        "free_before": f"{cutoff_hours} hours before start",
        "fee_after": f"{fee_percent}% of booking amount",
        "custom_text": getattr(provider, "cancellation_policy_text", None),
    }


@front_bp.route("/")
def index():
    return render_template("index.html")


@front_bp.route("/logout")
def logout_page():
    return redirect("/demo_login")


@front_bp.route("/home")
def home():
    """
    Landing skills list page with simple server-side search.
    Filters:
      - q: matches title or description (ILIKE)
      - location: matches skill.location (ILIKE)
    """
    q = request.args.get("q", "")
    location = request.args.get("location", "")

    query = Skill.query.join(User, Skill.provider_id == User.id).filter(
        Skill.is_active == True,
    )

    if hasattr(User, "is_accepting_bookings"):
        # The model has the attribute, but the DB column might not exist yet if migration hasn't run.
        # We will apply the filter, and if it fails at execution time, we fallback.
        query_with_booking = query.filter(User.is_accepting_bookings == True)
    else:
        query_with_booking = query

    if q:
        query_with_booking = query_with_booking.filter(
            (Skill.title.ilike(f"%{q}%")) |
            (Skill.description.ilike(f"%{q}%"))
        )
        query = query.filter(
            (Skill.title.ilike(f"%{q}%")) |
            (Skill.description.ilike(f"%{q}%"))
        )

    if location:
        query_with_booking = query_with_booking.filter(Skill.location.ilike(f"%{location}%"))
        query = query.filter(Skill.location.ilike(f"%{location}%"))

    page = request.args.get("page", 1, type=int)
    
    import sqlalchemy.exc
    try:
        paginated = query_with_booking.paginate(page=page, per_page=12, error_out=False)
    except sqlalchemy.exc.OperationalError:
        # Fallback if the is_accepting_bookings column does not exist in the database yet
        db.session.rollback()
        paginated = query.paginate(page=page, per_page=12, error_out=False)

    skills = paginated.items
    has_next = paginated.has_next
    next_page = paginated.next_num
    unique_providers = list({s.provider for s in skills if s.provider})
    approved_ids = [
        p.id for p in unique_providers if p.kyc_status == KycStatus.approved
    ]
    acc_stats = batch_provider_acceptance_counts(approved_ids)
    provider_seeker_metrics = {}
    for p in unique_providers:
        response_label, acceptance_rate = metrics_for_kyc_approved_provider(
            p, acc_stats
        )
        provider_seeker_metrics[p.id] = {
            "response_label": response_label,
            "acceptance_rate": acceptance_rate,
        }
    return render_template(
        "home.html",
        skills=skills,
        q=q,
        location=location,
        provider_seeker_metrics=provider_seeker_metrics,
        has_next=has_next,
        next_page=next_page,
    )


@front_bp.route("/skill/<int:skill_id>")
def skill_profile(skill_id):
    skill = Skill.query.get_or_404(skill_id)
    provider = skill.provider
    try:
        reviews = (
            Review.query
            .filter_by(provider_id=provider.id)
            .order_by(Review.created_at.desc())
            .limit(10)
            .all()
        )
    except Exception:
        reviews = []
    acc_stats = batch_provider_acceptance_counts([provider.id])
    response_label, acceptance_rate = metrics_for_kyc_approved_provider(
        provider, acc_stats
    )
    provider_metrics = {
        "response_label": response_label,
        "acceptance_rate": acceptance_rate,
    }
    return render_template(
        "skill_profile.html",
        skill=skill,
        provider=provider,
        reviews=reviews,
        provider_metrics=provider_metrics,
        is_accepting_bookings=getattr(provider, "is_accepting_bookings", True),
    )


@front_bp.route("/booking/<int:skill_id>", methods=["GET"])
def booking_page(skill_id):
    """
    Booking page for a skill.
    Note: backend cannot read JWT from localStorage, so strict role enforcement
    for seekers happens in the API (/api/bookings). Frontend hides CTAs when
    the user role is not seeker.
    """
    skill = Skill.query.get_or_404(skill_id)
    return render_template(
        "booking.html",
        skill=skill,
        cancellation_policy=_provider_cancellation_policy(skill.provider),
    )


@front_bp.route("/track/<int:booking_id>")
def track_booking(booking_id):
    """
    Seeker-side tracking page (view worker live location).
    Real role check is done at API/socket level; this is a thin UI.
    """
    return render_template("track_booking.html", booking_id=booking_id)


@front_bp.route("/worker_track/<int:booking_id>")
def worker_location_sender(booking_id):
    """
    Simple mobile-friendly page for providers to share live location
    for a specific booking. Uses Socket.IO to push location updates.
    Should only be used by the provider assigned to this booking; that
    check is enforced on the API/socket side.
    """
    booking = Booking.query.get_or_404(booking_id)
    return render_template(
        "worker_location_sender.html",
        booking_id=booking.id,
        booking=booking,
    )


@front_bp.route("/wallet")
def wallet_page():
    # Modernized Wallet Dashboard
    return render_template("wallet_v2.html")


@front_bp.route("/payment-history")
def payment_history_page():
    # Unified payment/invoice history
    return render_template("payment_history.html")


@front_bp.route("/provider_verification")
def provider_verification():
    return render_template("provider_verification.html")


@front_bp.route("/provider_verification_video")
def provider_verification_video():
    return render_template("provider_verification_video.html")


# ✅ Auth entrypoints all share the same role-aware template
@front_bp.route("/login")
@front_bp.route("/register")
@front_bp.route("/demo-login")
@front_bp.route("/demo_login")
def demo_login():
    return render_template("demo_login.html")

@front_bp.route("/chat/<room>")
def chat_page(room):
    return render_template("chat.html", room=room)


@front_bp.route("/messages")
def messages_page():
    return render_template("messages.html")

@front_bp.route("/provider/dashboard")
def provider_dashboard_page():
    return render_template("provider_dashboard.html")

@front_bp.route("/provider/kyc-status")
def provider_kyc_status_page():
    return render_template("provider_kyc_status.html")

@front_bp.route("/provider_verification_selfie")
def provider_verification_selfie():
    return render_template("provider_verification_selfie.html")

@front_bp.route("/confirm_location")
def confirm_location_page():
    return render_template("confirm_location.html")

@front_bp.route("/providers")
def providers_list():
    skill_id = request.args.get("skill_id", type=int)
    return render_template("provider_list.html", skill_id=skill_id)

@front_bp.route("/provider/profile")
def provider_profile_page():
    return render_template("provider_profile.html")

@front_bp.route("/my-bookings")
def seeker_dashboard():
    return render_template("seeker_dashboard.html")


@front_bp.route("/saved-providers")
def saved_providers_page():
    return render_template("saved_providers.html")


@front_bp.route("/account")
@front_bp.route("/settings")
def account_settings_page():
    return render_template("account.html")


def _legal_context():
    return {
        "legal_last_updated": current_app.config.get("LEGAL_LAST_UPDATED", "April 9, 2026"),
        "grievance_officer_name": current_app.config.get("GRIEVANCE_OFFICER_NAME", "Sklio Grievance Officer"),
        "grievance_email": current_app.config.get("GRIEVANCE_EMAIL", "grievance@sklio.in"),
        "grievance_phone": current_app.config.get("GRIEVANCE_PHONE", "+91 98765 43210"),
    }


@front_bp.route("/trust-center")
def trust_center_page():
    return render_template("trust_center.html", **_legal_context())


@front_bp.route("/help")
def help_center_page():
    return render_template("help_center.html", **_legal_context())


@front_bp.route("/legal/terms")
def terms_page():
    return render_template("terms.html", **_legal_context())


@front_bp.route("/legal/privacy")
def privacy_page():
    return render_template("privacy.html", **_legal_context())


@front_bp.route("/legal/refund")
def refund_policy_page():
    return render_template("refund_policy.html", **_legal_context())


@front_bp.route("/legal/provider-terms")
def provider_agreement_page():
    return render_template("provider_agreement.html", **_legal_context())


@front_bp.route("/legal/grievance")
def grievance_page():
    return render_template("grievance.html", **_legal_context())


@front_bp.route("/seeker-onboarding")
def seeker_onboarding_page():
    return render_template("seeker_onboarding.html")


@front_bp.route("/provider-onboarding")
def provider_onboarding_page():
    return render_template("provider_onboarding.html")


@front_bp.route("/quote-requests")
def quote_requests_page():
    return render_template("quote_requests.html")


@front_bp.route("/notifications")
def notifications_page():
    return render_template("notifications.html")


@front_bp.route("/provider-availability")
def provider_availability_page():
    return render_template("provider_availability.html")


@front_bp.route("/ops-dashboard")
def ops_dashboard_page():
    return render_template("ops_dashboard.html")


@front_bp.route("/admin")
def admin_search_page():
    return render_template("admin_search.html")


@front_bp.route("/ai-assist")
def ai_assist_page():
    return render_template("ai_assist.html")


@front_bp.route("/disputes")
def disputes_page():
    return render_template("disputes.html")


@front_bp.route("/cookie-policy")
def cookie_policy_page():
    return render_template("cookie_policy.html")


@front_bp.route("/memberships")
def memberships_page():
    return render_template("memberships.html")


@front_bp.route("/referrals")
@front_bp.route("/account/referrals")
def referrals_page():
    return render_template("referrals.html")

@front_bp.route("/jobs")
def jobs_board():
    """Public job board for everyone to browse."""
    if not _job_posts_enabled():
        abort(404)
    return render_template("job_posts.html")


@front_bp.route("/my-jobs")
def my_jobs():
    """Seeker's private job management dashboard."""
    if not _job_posts_enabled():
        abort(404)
    return render_template("my_job_posts.html")


@front_bp.route("/provider/job-board")
def provider_job_board():
    """Provider's dashboard to see available jobs and submit proposals."""
    if not _job_posts_enabled():
        abort(404)
    return render_template("provider_job_board.html")


@front_bp.route("/jobs/<int:job_id>")
def job_details(job_id):
    """Detailed view for a specific job post."""
    if not _job_posts_enabled():
        abort(404)
    return render_template("job_details.html", job_id=job_id)

@front_bp.route("/robots.txt")
def robots_txt():
    from flask import Response
    content = f"User-agent: *\nAllow: /\nSitemap: {request.host_url}sitemap.xml\n"
    return Response(content, mimetype="text/plain")

@front_bp.route("/sitemap.xml")
def sitemap_xml():
    from flask import Response
    pages = [
        "/", "/home", "/jobs", "/trust-center", 
        "/privacy", "/terms", "/refund-policy", "/contact"
    ]
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for page in pages:
        xml.append(f"  <url>\n    <loc>{request.host_url.rstrip('/')}{page}</loc>\n  </url>")
    xml.append('</urlset>')
    return Response("\n".join(xml), mimetype="application/xml")

@front_bp.route("/contact", methods=["GET", "POST"])
def contact_page():
    if request.method == "POST":
        from flask import request as req, jsonify
        from ..services.notification_delivery import send_email
        data = req.get_json() or {}
        name = data.get("name")
        email = data.get("email")
        message = data.get("message")
        if not name or not email or not message:
            return jsonify({"error": "All fields are required"}), 400
        
        # Send to admin using a dummy recipient structure
        class AdminRecipient:
            def __init__(self, admin_email):
                self.email = admin_email
                self.id = 0
                
        admin = AdminRecipient(current_app.config.get("ADMIN_EMAIL", "admin@sklio.com"))
        send_email(
            recipient=admin,
            title=f"New Contact Form Submission from {name}",
            body=f"Sender: {name} ({email})\n\nMessage:\n{message}"
        )
        return jsonify({"message": "Your message has been sent successfully!"}), 200
        
    return render_template("contact.html")
