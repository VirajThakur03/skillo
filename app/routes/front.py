# app/routes/front.py
from flask import Blueprint, render_template, request
from ..models import Skill, User, Booking
from ..extensions import db
from flask_jwt_extended import jwt_required, get_jwt_identity

front_bp = Blueprint("front", __name__)


@front_bp.route("/")
def index():
    return render_template("index.html")


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

    query = Skill.query.filter(Skill.is_active == True)

    if q:
        query = query.filter(
            (Skill.title.ilike(f"%{q}%")) |
            (Skill.description.ilike(f"%{q}%"))
        )

    if location:
        query = query.filter(Skill.location.ilike(f"%{location}%"))

    skills = query.limit(50).all()
    return render_template("home.html", skills=skills, q=q, location=location)


@front_bp.route("/skill/<int:skill_id>")
def skill_profile(skill_id):
    skill = Skill.query.get_or_404(skill_id)
    provider = skill.provider
    return render_template("skill_profile.html", skill=skill, provider=provider)


@front_bp.route("/booking/<int:skill_id>", methods=["GET"])
def booking_page(skill_id):
    """
    Booking page for a skill.
    Note: backend cannot read JWT from localStorage, so strict role enforcement
    for seekers happens in the API (/api/bookings). Frontend hides CTAs when
    the user role is not seeker.
    """
    skill = Skill.query.get_or_404(skill_id)
    return render_template("booking.html", skill=skill)


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
    # Wallet demo page; reads real data via API on the frontend.
    return render_template("wallet.html")


@front_bp.route("/provider_verification")
def provider_verification():
    return render_template("provider_verification.html")


@front_bp.route("/provider_verification_video")
def provider_verification_video():
    return render_template("provider_verification_video.html")


# ✅ BOTH URLs point to the same view that renders the demo login template
@front_bp.route("/demo-login")
@front_bp.route("/demo_login")
def demo_login():
    return render_template("demo_login.html")

@front_bp.route("/chat/<room>")
def chat_page(room):
    return render_template("chat.html", room=room)

@front_bp.route("/provider/dashboard")
def provider_dashboard_page():
    return render_template("provider_dashboard.html")

@front_bp.route("/provider_verification_selfie")
def provider_verification_selfie():
    return render_template("provider_verification_selfie.html")

@front_bp.route("/confirm_location")
def confirm_location_page():
    return render_template("confirm_location.html")

@front_bp.route("/providers")
def providers_list():
    skill_id = request.args.get("skill_id", type=int)
    return render_template("providers_list.html", skill_id=skill_id)

@front_bp.route("/provider/profile")
def provider_profile_page():
    return render_template("provider_profile.html")

@front_bp.route("/my-bookings")
def seeker_dashboard():
    return render_template("seeker_dashboard.html")
