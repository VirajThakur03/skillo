# app/routes/favorites.py
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

from ..extensions import db
from ..models import User, Skill, RoleEnum, FavoriteProvider
from ..services.provider_metrics import (
    batch_provider_acceptance_counts,
    metrics_for_kyc_approved_provider,
)

favorites_bp = Blueprint("favorites", __name__, url_prefix="/api/favorites")


def _seeker_user():
    uid = get_jwt_identity()
    if uid is None:
        return None, ({"error": "unauthenticated"}, 401)
    user = db.session.get(User, int(uid))
    if not user or user.role != RoleEnum.SEEKER:
        return None, ({"error": "only seekers may manage saved providers"}, 403)
    return user, None


@favorites_bp.route("/check", methods=["GET"])
@jwt_required()
def check_saved():
    user, err = _seeker_user()
    if err:
        return err
    raw = request.args.get("provider_ids") or ""
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    ids = list(dict.fromkeys(ids))[:100]
    if not ids:
        return {"saved_provider_ids": []}, 200
    try:
        rows = FavoriteProvider.query.filter(
            FavoriteProvider.seeker_id == user.id,
            FavoriteProvider.provider_id.in_(ids),
        ).all()
        return {"saved_provider_ids": [r.provider_id for r in rows]}, 200
    except (OperationalError, ProgrammingError):
        return {"saved_provider_ids": []}, 200


@favorites_bp.route("", methods=["GET"])
@jwt_required()
def list_favorites():
    user, err = _seeker_user()
    if err:
        return err
    offset = max(0, request.args.get("offset", type=int) or 0)
    limit = min(max(request.args.get("limit", type=int) or 20, 1), 50)
    try:
        q = (
            FavoriteProvider.query.filter_by(seeker_id=user.id)
            .order_by(FavoriteProvider.created_at.desc())
        )
        total = q.count()
        rows = q.offset(offset).limit(limit).all()
    except (OperationalError, ProgrammingError):
        return {"error": "saved providers unavailable"}, 503

    provider_ids = [row.provider_id for row in rows]
    acceptance_stats = batch_provider_acceptance_counts(provider_ids)

    items = []
    for row in rows:
        prov = db.session.get(User, row.provider_id)
        if not prov or prov.role != RoleEnum.PROVIDER:
            continue
        response_label, acceptance_rate = metrics_for_kyc_approved_provider(
            prov, acceptance_stats
        )
        sk = (
            Skill.query.filter_by(provider_id=prov.id, is_active=True)
            .order_by(Skill.id.asc())
            .first()
        )
        saved_at = row.created_at.isoformat() if row.created_at else None
        items.append(
            {
                "provider": {
                    "id": prov.id,
                    "name": prov.name,
                    "rating": float(prov.rating or 0),
                    "location": prov.location,
                    "response_label": response_label,
                    "acceptance_rate": acceptance_rate,
                    "is_saved": True,
                },
                "skill_id": sk.id if sk else None,
                "skill_title": sk.title if sk else None,
                "starting_price": float(sk.price or 0) if sk else None,
                "saved_at": saved_at,
                "notes": row.notes,
            }
        )

    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
    }, 200


@favorites_bp.route("", methods=["POST"])
@jwt_required()
def add_favorite():
    user, err = _seeker_user()
    if err:
        return err
    data = request.get_json() or {}
    try:
        pid = int(data.get("provider_id"))
    except (TypeError, ValueError):
        return {"error": "provider_id required"}, 400

    prov = db.session.get(User, pid)
    if not prov or prov.role != RoleEnum.PROVIDER:
        return {"error": "invalid provider"}, 404
    if pid == user.id:
        return {"error": "invalid provider"}, 400

    if FavoriteProvider.query.filter_by(
        seeker_id=user.id, provider_id=pid
    ).first():
        return {"saved": True}, 200

    row = FavoriteProvider(seeker_id=user.id, provider_id=pid)
    db.session.add(row)
    try:
        db.session.commit()
        return {"saved": True}, 201
    except IntegrityError:
        db.session.rollback()
        return {"saved": True}, 200
    except (OperationalError, ProgrammingError):
        db.session.rollback()
        return {"error": "saved providers unavailable"}, 503


@favorites_bp.route("/<int:provider_id>", methods=["DELETE"])
@jwt_required()
def remove_favorite(provider_id):
    user, err = _seeker_user()
    if err:
        return err
    try:
        FavoriteProvider.query.filter_by(
            seeker_id=user.id, provider_id=provider_id
        ).delete(synchronize_session=False)
        db.session.commit()
    except (OperationalError, ProgrammingError):
        db.session.rollback()
        return {"error": "saved providers unavailable"}, 503
    return "", 204


@favorites_bp.route("/<int:provider_id>/notes", methods=["PATCH"])
@jwt_required()
def update_favorite_notes(provider_id):
    user, err = _seeker_user()
    if err:
        return err
        
    data = request.get_json() or {}
    notes = data.get("notes", "")

    try:
        fav = FavoriteProvider.query.filter_by(
            seeker_id=user.id, provider_id=provider_id
        ).first()
        if not fav:
            return {"error": "not found in favorites"}, 404
            
        fav.notes = notes
        db.session.commit()
    except (OperationalError, ProgrammingError):
        db.session.rollback()
        return {"error": "database unavailable"}, 503
        
    return {"success": True, "notes": fav.notes}, 200
