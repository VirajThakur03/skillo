# app/routes/skills.py
from flask import Blueprint, request, jsonify
from ..extensions import db
from ..models import Skill, User, KycStatus, RoleEnum, FavoriteProvider
from ..services.provider_metrics import (
    batch_provider_acceptance_counts,
    metrics_for_kyc_approved_provider,
)
from ..utils import haversine
from decimal import Decimal
from math import radians, sin, cos, sqrt, atan2
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request

skills_bp = Blueprint("skills", __name__)

@skills_bp.route("", methods=["GET"])
def list_skills():
    verify_jwt_in_request(optional=True)
    viewer_uid = get_jwt_identity()
    viewer = db.session.get(User, int(viewer_uid)) if viewer_uid is not None else None

    # simple search: q (title), location, price_min, price_max
    q = request.args.get("q", "")
    location = request.args.get("location")
    price_min = request.args.get("price_min", type=float)
    price_max = request.args.get("price_max", type=float)

    query = (
        Skill.query
        .join(User, Skill.provider_id == User.id)
        .filter(
            Skill.is_active == True,
            User.kyc_status == KycStatus.approved,
            User.is_accepting_bookings == True
        )
    )

    if q:
        query = query.filter(Skill.title.ilike(f"%{q}%") | Skill.description.ilike(f"%{q}%"))
    if location:
        query = query.filter(Skill.location.ilike(f"%{location}%"))
    if price_min is not None:
        query = query.filter(Skill.price >= Decimal(price_min))
    if price_max is not None:
        query = query.filter(Skill.price <= Decimal(price_max))

    skills = query.limit(100).all()
    stats = batch_provider_acceptance_counts(
        list({s.provider.id for s in skills if s.provider})
    )
    saved_ids = set()
    if viewer and viewer.role == RoleEnum.SEEKER:
        pids = list({s.provider.id for s in skills if s.provider})
        if pids:
            saved_ids = {
                r.provider_id
                for r in FavoriteProvider.query.filter(
                    FavoriteProvider.seeker_id == viewer.id,
                    FavoriteProvider.provider_id.in_(pids),
                ).all()
            }

    result = []
    for s in skills:
        p = s.provider
        rl, ar = metrics_for_kyc_approved_provider(p, stats)
        is_saved = None
        if viewer and viewer.role == RoleEnum.SEEKER:
            is_saved = p.id in saved_ids
        result.append({
            "id": s.id,
            "title": s.title,
            "description": s.description,
            "price": float(s.price),
            "currency": s.currency,
            "provider": {
                "id": p.id,
                "name": p.name,
                "rating": p.rating,
                "response_label": rl,
                "acceptance_rate": ar,
                "is_saved": is_saved,
            },
            "location": s.location
        })
    return jsonify(result)

@skills_bp.route("", methods=["POST"])
@jwt_required()
def create_skill():
    user_id = get_jwt_identity()
    user = db.session.get(User, user_id)

    if not user:
        return {"error": "unauthenticated"}, 401

    # FIXED provider check (use OR)
    if (user.role.name.lower() != "provider") and (user.role.value.lower() != "provider"):
        return {"error": "only providers can create skills"}, 403

    # NEW: require verification
    if not user.is_verified:
        return {"error": "provider not verified. Upload ID and wait for verification."}, 403
    if user.kyc_status != KycStatus.approved:
        return {"error": "provider kyc not approved. Complete review before publishing skills."}, 403

    data = request.get_json() or {}
    title = data.get("title")
    description = data.get("description", "")
    price = data.get("price", 0.0)
    location = data.get("location", user.location)
    latitude = data.get("latitude")
    longitude = data.get("longitude")

    if not title:
        return {"error": "title required"}, 400

    skill = Skill(
        provider_id=user.id,
        title=title,
        description=description,
        price=price,
        location=location
    )

    # optional latitude/longitude
    if latitude:
        try:
            skill.latitude = float(latitude)
            skill.longitude = float(longitude) if longitude else None
        except:
            pass

    db.session.add(skill)
    db.session.commit()
    return {"id": skill.id, "title": skill.title}, 201

@skills_bp.route("/providers")
@jwt_required(optional=True)
def skill_providers():
    skill_id = request.args.get("skill_id", type=int)
    sort = request.args.get("sort", "distance")

    if not skill_id:
        return {"error": "skill_id required"}, 400

    skill = Skill.query.get_or_404(skill_id)

    seeker = None
    uid = get_jwt_identity()
    if uid is not None:
        seeker = db.session.get(User, int(uid))

    providers = Skill.query.join(User, Skill.provider_id == User.id).filter(
        Skill.title == skill.title,
        Skill.is_active == True,
        User.is_accepting_bookings == True
    ).all()

    approved_provider_ids = [
        s.provider.id
        for s in providers
        if s.provider and s.provider.kyc_status == KycStatus.approved
    ]
    stats = batch_provider_acceptance_counts(list(set(approved_provider_ids)))

    saved_ids = set()
    if seeker and seeker.role == RoleEnum.SEEKER and approved_provider_ids:
        saved_ids = {
            r.provider_id
            for r in FavoriteProvider.query.filter(
                FavoriteProvider.seeker_id == seeker.id,
                FavoriteProvider.provider_id.in_(list(set(approved_provider_ids))),
            ).all()
        }

    results = []

    for s in providers:
        provider = s.provider
        if provider.kyc_status != KycStatus.approved:
            continue

        distance = 999
        if seeker and seeker.latitude and provider.latitude:
            distance = haversine(
                seeker.latitude,
                seeker.longitude,
                provider.latitude,
                provider.longitude,
            )

        rl, ar = metrics_for_kyc_approved_provider(provider, stats)

        is_saved = None
        if seeker and seeker.role == RoleEnum.SEEKER:
            is_saved = provider.id in saved_ids

        results.append({
            "id": provider.id,
            "name": provider.name,
            "rating": provider.rating or 0,
            "price": float(s.price),
            "distance_km": distance,
            "skill_id": s.id,
            "response_label": rl,
            "acceptance_rate": ar,
            "is_saved": is_saved,
        })

    if sort == "price":
        results.sort(key=lambda x: x["price"])
    elif sort == "rating":
        results.sort(key=lambda x: -x["rating"])
    else:
        results.sort(key=lambda x: x["distance_km"])

    return results
