from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from ..extensions import db
from ..models import (
    SearchQueryLog,
    Skill,
    User,
    VerificationStatus,
    KycStatus,
    RoleEnum,
    FavoriteProvider,
)
from sqlalchemy.exc import ProgrammingError
from ..services.provider_metrics import (
    batch_provider_acceptance_counts,
    metrics_for_kyc_approved_provider,
)
from ..services.marketplace import (
    compute_provider_badges,
    get_or_create_instant_book_setting,
    list_provider_slots,
    provider_is_available,
)
from ..utils import haversine

search_bp = Blueprint("search", __name__, url_prefix="/api/search")


def _viewer():
    verify_jwt_in_request(optional=True)
    identity = get_jwt_identity()
    if identity is None:
        return None
    return db.session.get(User, int(identity))


def _provider_verified(provider):
    return bool(
        provider
        and (
            provider.is_verified
            or provider.verification_status
            in {VerificationStatus.face_verified, VerificationStatus.completed}
        )
    )


def _distance_from_viewer(viewer, provider, lat, lon):
    if lat is not None and lon is not None and provider.latitude is not None and provider.longitude is not None:
        return haversine(lat, lon, provider.latitude, provider.longitude)
    if (
        viewer
        and viewer.latitude is not None
        and viewer.longitude is not None
        and provider.latitude is not None
        and provider.longitude is not None
    ):
        return haversine(
            viewer.latitude,
            viewer.longitude,
            provider.latitude,
            provider.longitude,
        )
    return None


@search_bp.route("/providers", methods=["GET"])
def search_providers():
    viewer = _viewer()
    q = (request.args.get("q") or "").strip()
    location = (request.args.get("location") or "").strip()
    sort = (request.args.get("sort") or "relevance").strip().lower()
    price_min = request.args.get("price_min", type=float)
    price_max = request.args.get("price_max", type=float)
    rating_min = request.args.get("rating_min", type=float)
    distance_limit = request.args.get("distance_km", type=float)
    verified_only = request.args.get("verified_only") == "true"
    open_now = request.args.get("open_now") == "true"
    instant_book = request.args.get("instant_book") == "true"
    latitude = request.args.get("latitude", type=float)
    longitude = request.args.get("longitude", type=float)
    limit = min(max(request.args.get("limit", type=int) or 20, 1), 50)

    query = Skill.query.join(User, Skill.provider_id == User.id).filter(
        Skill.is_active.is_(True),
    )
    
    if hasattr(User, "is_accepting_bookings"):
        query_with_booking = query.filter(User.is_accepting_bookings.is_(True))
    else:
        query_with_booking = query

    if q:
        query_with_booking = query_with_booking.filter(
            Skill.title.ilike(f"%{q}%")
            | Skill.description.ilike(f"%{q}%")
            | Skill.tags.ilike(f"%{q}%")
        )
        query = query.filter(
            Skill.title.ilike(f"%{q}%")
            | Skill.description.ilike(f"%{q}%")
            | Skill.tags.ilike(f"%{q}%")
        )
    if location:
        query_with_booking = query_with_booking.filter(Skill.location.ilike(f"%{location}%"))
        query = query.filter(Skill.location.ilike(f"%{location}%"))
    if price_min is not None:
        query_with_booking = query_with_booking.filter(Skill.price >= Decimal(str(price_min)))
        query = query.filter(Skill.price >= Decimal(str(price_min)))
    if price_max is not None:
        query_with_booking = query_with_booking.filter(Skill.price <= Decimal(str(price_max)))
        query = query.filter(Skill.price <= Decimal(str(price_max)))

    import sqlalchemy.exc
    try:
        skills = query_with_booking.limit(200).all()
    except sqlalchemy.exc.OperationalError:
        db.session.rollback()
        skills = query.limit(200).all()
    provider_ids_for_stats = list(
        {
            skill.provider_id
            for skill in skills
            if skill.provider_id
            and skill.provider
            and skill.provider.role == RoleEnum.PROVIDER
            and skill.provider.kyc_status == KycStatus.approved
        }
    )
    acceptance_stats = batch_provider_acceptance_counts(provider_ids_for_stats)

    saved_provider_ids = set()
    if viewer and viewer.role == RoleEnum.SEEKER:
        cand_ids = list(
            {
                skill.provider_id
                for skill in skills
                if skill.provider and skill.provider.role == RoleEnum.PROVIDER
            }
        )
        if cand_ids:
            try:
                saved_provider_ids = {
                    row.provider_id
                    for row in FavoriteProvider.query.filter(
                        FavoriteProvider.seeker_id == viewer.id,
                        FavoriteProvider.provider_id.in_(cand_ids),
                    ).all()
                }
            except (Exception, ProgrammingError):
                saved_provider_ids = set()

    results = []
    for skill in skills:
        provider = skill.provider
        if not provider or provider.role != RoleEnum.PROVIDER:
            continue
        if verified_only and not _provider_verified(provider):
            continue
        if rating_min is not None and (provider.rating or 0) < rating_min:
            continue

        distance_km = _distance_from_viewer(viewer, provider, latitude, longitude)
        if distance_limit is not None and distance_km is not None and distance_km > distance_limit:
            continue

        instant_book_setting = get_or_create_instant_book_setting(provider.id)
        instant_book_available = bool(
            instant_book_setting.instant_book_enabled
            and (
                not instant_book_setting.enabled_skill_ids
                or skill.id in (instant_book_setting.enabled_skill_ids or [])
            )
        )
        if instant_book and not instant_book_available:
            continue

        slot_snapshot = list_provider_slots(provider.id, days=7, skill_id=skill.id)
        open_now_available, _ = provider_is_available(
            provider.id,
            datetime.now(timezone.utc),
            max(30, instant_book_setting.slot_duration_minutes or 60),
            skill_id=skill.id,
        )
        if open_now and not open_now_available:
            continue

        response_label, acceptance_rate = metrics_for_kyc_approved_provider(
            provider, acceptance_stats
        )

        is_saved = None
        if viewer and viewer.role == RoleEnum.SEEKER:
            is_saved = provider.id in saved_provider_ids

        results.append(
            {
                "provider_id": provider.id,
                "skill_id": skill.id,
                "provider_name": provider.name,
                "service_title": skill.title,
                "description": skill.description,
                "starting_price": float(skill.price or 0),
                "currency": skill.currency,
                "rating": provider.rating or 0,
                "review_count": len(getattr(provider, "reviews_received", None) or []),
                "distance_km": round(distance_km, 2) if distance_km is not None else None,
                "verified_badges": compute_provider_badges(provider),
                "open_now": open_now_available,
                "instant_book": instant_book_available,
                "next_available_at": slot_snapshot.get("next_available_at"),
                "location": skill.location or provider.location,
                "response_label": response_label,
                "acceptance_rate": acceptance_rate,
                "is_saved": is_saved,
            }
        )

    if sort == "distance":
        results.sort(key=lambda item: (item["distance_km"] is None, item["distance_km"] or 999999))
    elif sort == "price":
        results.sort(key=lambda item: item["starting_price"])
    elif sort == "rating":
        results.sort(key=lambda item: -item["rating"])
    else:
        results.sort(
            key=lambda item: (
                0 if q and q.lower() in (item["service_title"] or "").lower() else 1,
                -(item["rating"] or 0),
                item["distance_km"] if item["distance_km"] is not None else 999999,
            )
        )

    session_id = (
        request.headers.get("X-Session-Id")
        or request.args.get("session_id")
        or request.remote_addr
        or "anonymous"
    )
    db.session.add(
        SearchQueryLog(
            user_id=viewer.id if viewer else None,
            session_id=session_id,
            query_text=q or None,
            filters={
                "location": location or None,
                "price_min": price_min,
                "price_max": price_max,
                "rating_min": rating_min,
                "distance_km": distance_limit,
                "verified_only": verified_only,
                "open_now": open_now,
                "instant_book": instant_book,
                "sort": sort,
            },
            result_count=len(results),
        )
    )
    db.session.commit()

    return {
        "items": results[:limit],
        "total": len(results),
        "facets": {
            "available_sorts": ["relevance", "distance", "price", "rating"],
            "verified_only": verified_only,
            "open_now": open_now,
            "instant_book": instant_book,
        },
    }, 200


@search_bp.route("/providers/suggestions", methods=["GET"])
def provider_suggestions():
    q = (request.args.get("q") or "").strip()
    query = Skill.query.filter(Skill.is_active.is_(True))
    if q:
        query = query.filter(Skill.title.ilike(f"%{q}%"))
    titles = []
    for skill in query.order_by(Skill.created_at.desc()).limit(20).all():
        if skill.title and skill.title not in titles:
            titles.append(skill.title)
    return {"suggestions": titles[:10]}, 200


@search_bp.route("/filters/meta", methods=["GET"])
def filter_meta():
    skills = Skill.query.filter(Skill.is_active.is_(True)).all()
    prices = [float(skill.price or 0) for skill in skills]
    ratings = [float(skill.provider.rating or 0) for skill in skills if skill.provider]
    return {
        "price_bounds": {
            "min": min(prices) if prices else 0,
            "max": max(prices) if prices else 0,
        },
        "rating_bounds": {
            "min": min(ratings) if ratings else 0,
            "max": max(ratings) if ratings else 5,
        },
    }, 200


@search_bp.route("/query-events", methods=["POST"])
def query_events():
    data = request.get_json() or {}
    session_id = data.get("session_id") or request.remote_addr or "anonymous"
    viewer = _viewer()
    log = SearchQueryLog(
        user_id=viewer.id if viewer else None,
        session_id=session_id,
        query_text=data.get("query_text"),
        filters=data.get("filters") or {},
        result_count=int(data.get("result_count") or 0),
        clicked_provider_id=data.get("clicked_provider_id"),
        booked_provider_id=data.get("booked_provider_id"),
    )
    db.session.add(log)
    db.session.commit()
    return {"success": True}, 202
