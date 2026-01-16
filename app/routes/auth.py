# app/routes/auth.py

from flask import Blueprint, request, current_app
from ..extensions import db, bcrypt
from ..models import User, RoleEnum, VerificationStatus
from ..config import Config
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
)
from app.verify.document_verify import extract_text, validate_document
from werkzeug.utils import secure_filename
import os
import random
import string
import time
import re

# ==========================
# Blueprint
# ==========================
auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# ==========================
# Helpers
# ==========================
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def allowed_file(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in current_app.config.get(
        "ALLOWED_DOCUMENT_EXTENSIONS",
        {"png", "jpg", "jpeg", "pdf"},
    )


def generate_referral_code():
    return "SKL" + "".join(
        random.choices(string.ascii_uppercase + string.digits, k=5)
    )


# ==========================
# REGISTER
# ==========================
@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}

    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    role_raw = data.get("role", "seeker").strip().lower()

    # ---- Validation ----
    if not name or not email or not password:
        return {"error": "name, email and password are required"}, 400

    if not EMAIL_REGEX.match(email):
        return {"error": "invalid email format"}, 400

    if len(password) < 6:
        return {"error": "password must be at least 6 characters"}, 400

    if User.query.filter_by(email=email).first():
        return {"error": "email already registered"}, 400

    # ---- Role mapping (MATCHES DB ENUM) ----
    if role_raw == "seeker":
        role_enum = RoleEnum.SEEKER
    elif role_raw == "provider":
        role_enum = RoleEnum.PROVIDER
    else:
        return {"error": "invalid role"}, 400

    # ---- Create user ----
    user = User(
        name=name,
        email=email,
        role=role_enum,
    )
    user.set_password(password, bcrypt)

    # ---- Generate unique referral code ----
    while True:
        code = generate_referral_code()
        if not User.query.filter_by(referral_code=code).first():
            user.referral_code = code
            break

    db.session.add(user)
    db.session.commit()

    access = create_access_token(identity=str(user.id))
    refresh = create_refresh_token(identity=str(user.id))

    return {
    "access_token": access,
    "refresh_token": refresh,
    "user": {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role.value,

        # 🔐 VERIFICATION FLAGS (CRITICAL)
        "is_verified": user.is_verified,
        "verification_status": user.verification_status.value,
        "verification_video_status": user.verification_video_status.value,

        # optional info
        "location": user.location,
        "latitude": user.latitude,
        "longitude": user.longitude,
        "referral_code": user.referral_code,
        "wallet_balance": str(user.wallet_balance or 0),
    },
}, 201


# ==========================
# LOGIN
# ==========================
@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return {"error": "email and password required"}, 400

    user = User.query.filter_by(email=email).first()

    if not user or not user.check_password(password, bcrypt):
        return {"error": "invalid email or password"}, 401

    access = create_access_token(identity=str(user.id))
    refresh = create_refresh_token(identity=str(user.id))

    return {
    "access_token": access,
    "refresh_token": refresh,
    "user": {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role.value,

        # 🔐 VERIFICATION FLAGS (CRITICAL)
        "is_verified": user.is_verified,
        "verification_status": user.verification_status.value,
        "verification_video_status": user.verification_video_status.value,

        # optional info
        "location": user.location,
        "latitude": user.latitude,
        "longitude": user.longitude,
        "referral_code": user.referral_code,
        "wallet_balance": str(user.wallet_balance or 0),
    },
}


# ==========================
# CURRENT USER
# ==========================
@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)

    if not user:
        return {"error": "not found"}, 404

    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role.value,
        "location": user.location,
        "latitude": user.latitude,
        "longitude": user.longitude,
        "is_verified": user.is_verified,
        "verification_status": user.verification_status.value,
        "verification_video_status": user.verification_video_status.value,
        "referral_code": user.referral_code,
        "wallet_balance": str(user.wallet_balance or 0),
    }


# ==========================
# UPLOAD DOCUMENT (PROVIDER)
# ==========================
@auth_bp.route("/upload_document", methods=["POST"])
@jwt_required()
def upload_document():
    user = User.query.get(int(get_jwt_identity()))

    if not user:
        return {"error": "unauthenticated"}, 401

    if user.role != RoleEnum.PROVIDER:
        return {"error": "only providers allowed"}, 403

    if "file" not in request.files:
        return {"error": "file required"}, 400

    file = request.files["file"]
    doc_type = request.form.get("document_type", "").strip().lower()

    if not file.filename:
        return {"error": "no selected file"}, 400

    if not allowed_file(file.filename):
        return {"error": "unsupported file type"}, 400

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)

    filename = secure_filename(file.filename)
    save_name = f"user_{user.id}_{int(time.time())}_{filename}"
    file_path = os.path.join(upload_folder, save_name)
    file.save(file_path)

    # ---------- OCR ----------
    text = extract_text(file_path)

    if not text.strip():
        return {"error": "No readable text found"}, 400

    import re

    is_valid = False

    if doc_type == "aadhaar":
        is_valid = bool(re.search(r"\b\d{4}\s?\d{4}\s?\d{4}\b", text))

    elif doc_type == "passport":
        is_valid = bool(re.search(r"\b[A-Z][0-9]{7}\b", text))

    elif doc_type in ["driving license", "driving licence"]:
        is_valid = bool(re.search(r"\b[A-Z]{2}\d{2}\s?\d{11}\b", text))

    elif doc_type == "other":
        is_valid = True

    if not is_valid:
        return {"error": "Invalid document image"}, 400

    # ---------- SAVE ----------
    user.document_filename = save_name
    user.document_type = doc_type
    user.verification_status = VerificationStatus.document_verified
    user.verification_video_status = VerificationStatus.pending
    user.is_verified = False

    db.session.commit()

    return {
        "message": "Document verified",
        "next": "face_verification"
    }, 201




# ==========================
# UPLOAD VERIFICATION VIDEO
# ==========================
@auth_bp.route("/upload_verification_video", methods=["POST"])
@jwt_required()
def upload_verification_video():
    user = User.query.get(int(get_jwt_identity()))

    if user.verification_status != VerificationStatus.document_verified:
        return {"error": "document verification required"}, 400

    file = request.files.get("file")
    if not file:
        return {"error": "video required"}, 400

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)

    filename = secure_filename(file.filename)
    save_name = f"user_{user.id}_face_{int(time.time())}_{filename}"
    file.save(os.path.join(upload_folder, save_name))

    user.verification_video_filename = save_name
    user.verification_status = VerificationStatus.face_verified

    db.session.commit()

    return {
        "message": "Face verification uploaded",
        "next": "location"
    }, 201

# ==========================
# UPLOAD LOCATION CONFIRMATION
# ==========================
@auth_bp.route("/confirm_location", methods=["POST"])
@jwt_required()
def confirm_location():
    user = User.query.get(int(get_jwt_identity()))

    if user.verification_status != VerificationStatus.face_verified:
        return {"error": "face verification required"}, 400

    data = request.get_json() or {}
    user.latitude = data.get("latitude")
    user.longitude = data.get("longitude")

    user.verification_status = VerificationStatus.completed
    user.is_verified = True

    db.session.commit()

    return {"message": "Verification completed"}, 200
