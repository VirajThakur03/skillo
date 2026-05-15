import secrets
from decimal import Decimal
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import get_jwt_identity, jwt_required

from ..extensions import bcrypt, db
from ..models import Booking, ConsentRecord, Message, Skill, User, generate_deleted_email
from ..services.storage_service import delete_reference, store_upload


account_bp = Blueprint("account", __name__, url_prefix="/api/account")


def _current_user():
    return db.session.get(User, int(get_jwt_identity()))


@account_bp.route("/export", methods=["GET"])
@jwt_required()
def export_account():
    user = _current_user()
    if not user:
        return jsonify({"error": "user not found"}), 404

    return jsonify(
        {
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "phone": user.phone,
                "role": user.role.value,
                "location": user.location,
                "latitude": user.latitude,
                "longitude": user.longitude,
                "verification_status": user.verification_status.value,
                "kyc_status": user.kyc_status.value,
                "wallet_balance": str(user.wallet_balance or Decimal("0.00")),
                "created_at": user.created_at.isoformat() if user.created_at else None,
            },
            "skills": [
                {
                    "id": skill.id,
                    "title": skill.title,
                    "description": skill.description,
                    "price": float(skill.price or 0),
                    "currency": skill.currency,
                    "location": skill.location,
                    "is_active": skill.is_active,
                    "created_at": skill.created_at.isoformat() if skill.created_at else None,
                }
                for skill in Skill.query.filter_by(provider_id=user.id).order_by(Skill.created_at.desc()).all()
            ],
            "bookings": {
                "as_seeker": [
                    {
                        "id": booking.id,
                        "provider_id": booking.provider_id,
                        "skill_id": booking.skill_id,
                        "scheduled_at": booking.scheduled_at.isoformat() if booking.scheduled_at else None,
                        "status": booking.status.value,
                        "payment_status": booking.payment_status.value,
                        "price": float(booking.price or 0),
                    }
                    for booking in Booking.query.filter_by(seeker_id=user.id).order_by(Booking.created_at.desc()).all()
                ],
                "as_provider": [
                    {
                        "id": booking.id,
                        "seeker_id": booking.seeker_id,
                        "skill_id": booking.skill_id,
                        "scheduled_at": booking.scheduled_at.isoformat() if booking.scheduled_at else None,
                        "status": booking.status.value,
                        "payment_status": booking.payment_status.value,
                        "price": float(booking.price or 0),
                    }
                    for booking in Booking.query.filter_by(provider_id=user.id).order_by(Booking.created_at.desc()).all()
                ],
            },
            "messages": [
                {
                    "id": message.id,
                    "room": message.room,
                    "content": message.content,
                    "created_at": message.created_at.isoformat() if message.created_at else None,
                }
                for message in Message.query.filter_by(sender_id=user.id).order_by(Message.created_at.desc()).all()
            ],
            "consents": [
                {
                    "consent_type": consent.consent_type,
                    "version": consent.version,
                    "accepted_at": consent.accepted_at.isoformat(),
                    "ip_address": consent.ip_address,
                    "user_agent": consent.user_agent,
                }
                for consent in sorted(user.consent_records, key=lambda item: item.accepted_at, reverse=True)
            ],
            "kyc_documents": [
                {
                    "doc_type": document.doc_type,
                    "file_url": document.file_url,
                    "created_at": document.created_at.isoformat() if document.created_at else None,
                }
                for document in user.kyc_documents
            ],
        }
    )

@account_bp.route("/profile", methods=["PATCH"])
@jwt_required()
def update_profile():
    user = _current_user()
    if not user:
        return jsonify({"error": "user not found"}), 404

    data = request.get_json() or {}
    
    name = (data.get("name") or "").strip()
    if name:
        user.name = name
        
    phone = (data.get("phone") or "").strip()
    if phone:
        # Check if phone is already in use by someone else
        existing = User.query.filter(User.phone == phone, User.id != user.id).first()
        if existing:
            return jsonify({"error": "phone already in use"}), 409
        user.phone = phone
        
    db.session.commit()
    return jsonify({"name": user.name, "phone": user.phone}), 200

@account_bp.route("/photo", methods=["POST"])
@jwt_required()
def upload_profile_photo():
    user = _current_user()
    if not user:
        return jsonify({"error": "user not found"}), 404

    if "photo" not in request.files:
        return jsonify({"error": "no photo uploaded"}), 400

    file = request.files["photo"]
    if file.filename == "":
        return jsonify({"error": "empty file"}), 400

    try:
        result = store_upload(
            file, 
            folder="photos", 
            allowed_extensions={"jpg", "jpeg", "png", "webp"}, 
            user_id=user.id
        )
        
        old_photo = user.profile_photo_url
        user.profile_photo_url = result["storage_ref"]
        db.session.commit()
        
        if old_photo:
            try:
                delete_reference(old_photo)
            except Exception:
                pass
                
        return jsonify({"url": "/api/system/upload?ref=" + user.profile_photo_url}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Photo upload failed: {str(e)}")
        return jsonify({"error": "Upload failed"}), 500

@account_bp.route("/portfolio", methods=["POST"])
@jwt_required()
def add_portfolio_image():
    user = _current_user()
    if not user:
        return jsonify({"error": "user not found"}), 404

    if "image" not in request.files:
        return jsonify({"error": "no image uploaded"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "empty file"}), 400

    portfolio = list(user.portfolio_images or [])
    if len(portfolio) >= 6:
        return jsonify({"error": "Maximum of 6 portfolio images allowed"}), 400

    try:
        result = store_upload(
            file, 
            folder=f"portfolio/{user.id}", 
            allowed_extensions={"jpg", "jpeg", "png", "webp"}, 
            user_id=user.id
        )
        
        portfolio.append(result["storage_ref"])
        user.portfolio_images = portfolio
        db.session.commit()
        
        return jsonify({"url": "/api/system/upload?ref=" + result["storage_ref"], "index": len(portfolio) - 1}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Portfolio upload failed: {str(e)}")
        return jsonify({"error": "Upload failed"}), 500


@account_bp.route("/location", methods=["DELETE"])
@jwt_required()
def delete_location():
    user = _current_user()
    if not user:
        return jsonify({"error": "user not found"}), 404
    
    user.location = None
    user.latitude = None
    user.longitude = None
    db.session.commit()
    return jsonify({"message": "Location data deleted"}), 200


@account_bp.route("/profile", methods=["DELETE"])
@jwt_required()
def delete_profile_data():
    user = _current_user()
    if not user:
        return jsonify({"error": "user not found"}), 404
    
    user.bio = None
    db.session.commit()
    return jsonify({"message": "Profile bio deleted"}), 200


@account_bp.route("/portfolio", methods=["DELETE"])
@jwt_required()
def clear_portfolio():
    user = _current_user()
    if not user:
        return jsonify({"error": "user not found"}), 404
    
    portfolio = list(user.portfolio_images or [])
    for ref in portfolio:
        try:
            delete_reference(ref)
        except Exception:
            pass
    
    user.portfolio_images = []
    db.session.commit()
    return jsonify({"message": "Portfolio cleared"}), 200


@account_bp.route("/portfolio/<int:index>", methods=["DELETE"])
@jwt_required()
def delete_portfolio_image(index):
    user = _current_user()
    if not user:
        return jsonify({"error": "user not found"}), 404

    portfolio = list(user.portfolio_images or [])
    if index < 0 or index >= len(portfolio):
        return jsonify({"error": "Invalid portfolio index"}), 404

    ref_to_delete = portfolio.pop(index)
    user.portfolio_images = portfolio
    db.session.commit()

    try:
        delete_reference(ref_to_delete)
    except Exception:
        pass

    return "", 204


@account_bp.route("/consent", methods=["POST"])
@jwt_required()
def record_consent():
    user = _current_user()
    if not user:
        return jsonify({"error": "user not found"}), 404

    data = request.get_json() or {}
    consent_type = (data.get("consent_type") or "").strip()
    version = (data.get("version") or "").strip()
    if not consent_type or not version:
        return jsonify({"error": "consent_type and version are required"}), 400

    consent = ConsentRecord(
        user_id=user.id,
        consent_type=consent_type,
        version=version,
        ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
        user_agent=(request.headers.get("User-Agent") or "")[:255],
    )
    db.session.add(consent)
    db.session.commit()

    return jsonify(
        {
            "status": "recorded",
            "consent": {
                "consent_type": consent.consent_type,
                "version": consent.version,
                "accepted_at": consent.accepted_at.isoformat(),
            },
        }
    ), 201


@account_bp.route("", methods=["DELETE"])
@jwt_required()
def delete_account():
    user = _current_user()
    if not user:
        return "", 204

    for reference in [user.document_filename, user.selfie_filename, user.verification_video_filename]:
        try:
            delete_reference(reference)
        except Exception:
            pass

    for document in list(user.kyc_documents):
        try:
            delete_reference(document.file_url)
        except Exception:
            pass
        db.session.delete(document)

    for skill in Skill.query.filter_by(provider_id=user.id).all():
        skill.is_active = False
        skill.title = f"Unavailable skill #{skill.id}"
        skill.description = "Removed after account deletion request."

    for message in Message.query.filter_by(sender_id=user.id).all():
        message.content = "[deleted by user request]"
        message.sender_id = None
        message.is_deleted = True
        message.deleted_at = datetime.now(timezone.utc)

    # Also soft-delete bookings associated with this user
    for booking in Booking.query.filter((Booking.seeker_id == user.id) | (Booking.provider_id == user.id)).all():
        booking.is_deleted = True
        booking.deleted_at = datetime.now(timezone.utc)

    user.name = "Deleted User"
    user.email = generate_deleted_email()
    user.phone = None
    user.password_hash = bcrypt.generate_password_hash(secrets.token_urlsafe(32)).decode("utf-8")
    user.bio = None
    user.location = None
    user.latitude = None
    user.longitude = None
    user.document_filename = None
    user.document_type = None
    user.selfie_filename = None
    user.verification_video_filename = None
    user.verification_notes = "Account deleted by user request"
    user.wallet_balance = Decimal("0.00")
    user.badges = []
    user.referral_code = None

    db.session.commit()
    return ("", 204)
