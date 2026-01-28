# app/routes/skills.py
from flask import Blueprint, request, jsonify
from ..extensions import db
from ..models import Skill, User
from decimal import Decimal
from math import radians, sin, cos, sqrt, atan2
from flask_jwt_extended import jwt_required, get_jwt_identity

skills_bp = Blueprint("skills", __name__)

@skills_bp.route("", methods=["GET"])
def list_skills():
    # simple search: q (title), location, price_min, price_max
    q = request.args.get("q", "")
    location = request.args.get("location")
    price_min = request.args.get("price_min", type=float)
    price_max = request.args.get("price_max", type=float)

    query = Skill.query.filter(Skill.is_active == True)

    if q:
        query = query.filter(Skill.title.ilike(f"%{q}%") | Skill.description.ilike(f"%{q}%"))
    if location:
        query = query.filter(Skill.location.ilike(f"%{location}%"))
    if price_min is not None:
        query = query.filter(Skill.price >= Decimal(price_min))
    if price_max is not None:
        query = query.filter(Skill.price <= Decimal(price_max))

    skills = query.limit(100).all()
    result = []
    for s in skills:
        result.append({
            "id": s.id,
            "title": s.title,
            "description": s.description,
            "price": float(s.price),
            "currency": s.currency,
            "provider": {
                "id": s.provider.id,
                "name": s.provider.name,
                "rating": s.provider.rating,
            },
            "location": s.location
        })
    return jsonify(result)

@skills_bp.route("", methods=["POST"])
@jwt_required()
def create_skill():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if not user:
        return {"error": "unauthenticated"}, 401

    # FIXED provider check (use OR)
    if (user.role.name.lower() != "provider") and (user.role.value.lower() != "provider"):
        return {"error": "only providers can create skills"}, 403

    # NEW: require verification
    if not user.is_verified:
        return {"error": "provider not verified. Upload ID and wait for verification."}, 403

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
    if get_jwt_identity():
        seeker = User.query.get(get_jwt_identity())

    providers = Skill.query.filter_by(
        title=skill.title,
        is_active=True
    ).all()

    results = []

    for s in providers:
        provider = s.provider

        distance = 999
        if seeker and seeker.latitude and provider.latitude:
            distance = haversine(
                seeker.latitude,
                seeker.longitude,
                provider.latitude,
                provider.longitude,
            )

        results.append({
            "id": provider.id,
            "name": provider.name,
            "rating": provider.rating or 0,
            "price": float(s.price),
            "distance_km": distance,
            "skill_id": s.id
        })

    if sort == "price":
        results.sort(key=lambda x: x["price"])
    elif sort == "rating":
        results.sort(key=lambda x: -x["rating"])
    else:
        results.sort(key=lambda x: x["distance_km"])

    return results
