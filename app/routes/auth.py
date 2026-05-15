# app/routes/auth.py

from flask import Blueprint, jsonify, request, current_app
import hashlib
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from ..extensions import db, bcrypt, limiter
from ..models import AuditLog, User, RoleEnum, VerificationStatus
from ..config import Config
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt,
    jwt_required,
    get_jwt_identity,
)
# 🔥 OCR + FAKE CHECKS — guarded import so server starts without ML libraries
try:
    from app.verify.document_verify import (
        extract_text,
        is_blurry,
        is_screenshot,
        validate_document,
    )
    from app.verify.face_verify import (
        extract_and_save_document_face,
        load_document_face,
        extract_video_faces,
        faces_match,
        extract_face_from_image,
    )
    FACE_VERIFY_AVAILABLE = True
except ImportError:  # numpy / cv2 / deepface not installed (Windows local env)
    FACE_VERIFY_AVAILABLE = False
    # Stubs so route code can reference names without crashing
    def extract_text(p): return ""
    def is_blurry(p): return False
    def is_screenshot(p): return False
    def validate_document(t, d): return True
    def extract_and_save_document_face(src, dst): return False
    def load_document_face(p): return None
    def extract_video_faces(p): return []
    def faces_match(ref, faces): return False
    def extract_face_from_image(p): return None

from app.utils import compute_badges

from ..services.storage_service import store_upload, resolve_reference_path
import os
import random
import string
import re

# ==========================
# Blueprint
# ==========================
auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# ==========================
# Helpers
# ==========================
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _password_reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


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


def _email_hash(email):
    return hashlib.sha256((email or "").encode("utf-8")).hexdigest()


def _infer_video_extension(content_type):
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    return {
        "video/webm": "webm",
        "video/mp4": "mp4",
        "video/quicktime": "mov",
        "video/x-msvideo": "avi",
        "application/octet-stream": "webm",
    }.get(normalized)


def _provider_route_contract(user):
    if not user or user.role != RoleEnum.PROVIDER:
        return {
            "provider_access_state": None,
            "provider_next_route": None,
            "provider_allowed_paths": [],
        }

    if not user.is_provider_profile_complete:
        return {
            "provider_access_state": "profile_incomplete",
            "provider_next_route": "/provider/profile",
            "provider_allowed_paths": ["/provider/profile"],
        }

    verification_status = user.verification_status.value
    kyc_status = user.kyc_status.value

    if verification_status == VerificationStatus.document_verified.value and user.requires_selfie:
        return {
            "provider_access_state": "requires_selfie",
            "provider_next_route": "/provider_verification_selfie",
            "provider_allowed_paths": ["/provider_verification_selfie"],
        }

    if verification_status == VerificationStatus.document_verified.value:
        return {
            "provider_access_state": "requires_video",
            "provider_next_route": "/provider_verification_video",
            "provider_allowed_paths": ["/provider_verification_video"],
        }

    if verification_status == VerificationStatus.face_verified.value:
        return {
            "provider_access_state": "requires_location",
            "provider_next_route": "/confirm_location",
            "provider_allowed_paths": ["/confirm_location"],
        }

    if verification_status == VerificationStatus.completed.value and kyc_status == "approved":
        return {
            "provider_access_state": "ready",
            "provider_next_route": "/provider/dashboard",
            "provider_allowed_paths": [],
        }

    if kyc_status in {"pending", "documents_submitted", "under_review", "rejected"}:
        return {
            "provider_access_state": f"kyc_{kyc_status}",
            "provider_next_route": "/provider/dashboard",
            "provider_allowed_paths": [
                "/provider/dashboard",
                "/provider/kyc-status",
                "/provider_verification",
            ],
        }

    if kyc_status == "suspended":
        return {
            "provider_access_state": "kyc_suspended",
            "provider_next_route": "/provider/kyc-status",
            "provider_allowed_paths": ["/provider/kyc-status", "/provider_verification"],
        }

    return {
        "provider_access_state": "verification_required",
        "provider_next_route": "/provider_verification",
        "provider_allowed_paths": ["/provider_verification"],
    }


def _serialize_user(user):
    payload = {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role.value,
        "is_admin": user.is_admin,
        "is_verified": user.is_verified,
        "is_email_verified": user.is_email_verified,
        "verification_status": user.verification_status.value,
        "kyc_status": user.kyc_status.value,
        "kyc_rejection_reason": user.kyc_rejection_reason,
        "requires_selfie": user.requires_selfie,
        "is_provider_profile_complete": user.is_provider_profile_complete,
        "location": user.location,
        "latitude": user.latitude,
        "longitude": user.longitude,
        "referral_code": user.referral_code,
        "wallet_balance": str(user.wallet_balance or 0),
    }
    payload.update(_provider_route_contract(user))
    return payload


# ==========================
# REGISTER
# ==========================
@auth_bp.route("/register", methods=["POST"])
@limiter.limit(lambda: current_app.config.get("AUTH_RATE_LIMIT", "5 per minute"))
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

    if len(password) < 8:
        return {"error": "password must be at least 8 characters"}, 400

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
    db.session.refresh(user)

    access = create_access_token(identity=str(user.id))
    refresh = create_refresh_token(identity=str(user.id))

    # Send verification email
    try:
        from itsdangerous import URLSafeTimedSerializer
        s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="email-verify")
        token = s.dumps(user.email)
        verify_link = f"{request.host_url}verify-email?token={token}"
        from ..services.notification_delivery import send_email
        send_email(
            recipient=user,
            title="Verify your Sklio Email",
            body=f"Welcome to Sklio! Click the link to verify your email address: {verify_link}"
        )
    except Exception as e:
        current_app.logger.error(f"Failed to send verification email on registration: {e}")

    return {
        "access_token": access,
        "refresh_token": refresh,
        "user": _serialize_user(user),
    }, 201


# ==========================
# LOGIN
# ==========================
@auth_bp.route("/login", methods=["POST"])
@limiter.limit(lambda: current_app.config.get("AUTH_RATE_LIMIT", "5 per minute"))
def login():
    data = request.get_json() or {}

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return {"error": "email and password required"}, 400

    user = User.query.filter_by(email=email).first()

    if not user or not user.check_password(password, bcrypt):
        AuditLog.record(
            "user.login_failed",
            actor_role="anonymous",
            target_type="user",
            metadata={
                "email_hash": _email_hash(email),
                "reason": "bad_password",
            },
            request=request,
        )
        db.session.commit()
        current_app.logger.warning(
            "user.login.failed",
            extra={
                "email_hash": _email_hash(email),
                "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
                "reason": "bad_password",
            },
        )
        return {"error": "invalid email or password"}, 401

    access = create_access_token(identity=str(user.id))
    refresh = create_refresh_token(identity=str(user.id))
    current_app.logger.info(
        "user.login.success",
        extra={
            "user_id": user.id,
            "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
            "user_type": user.role.value,
        },
    )

    return {
        "access_token": access,
        "refresh_token": refresh,
        "user": _serialize_user(user),
    }, 200


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
@limiter.limit(lambda: current_app.config.get("AUTH_RATE_LIMIT", "5 per minute"))
def refresh():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return {"error": "user not found"}, 404

    access = create_access_token(identity=str(user.id))
    return {
        "access_token": access,
        "token_type": "Bearer",
        "user_id": user.id,
        "refresh_jti": get_jwt().get("jti"),
    }, 200


@auth_bp.route("/password-reset/request", methods=["POST"])
@limiter.limit(lambda: current_app.config.get("PASSWORD_RESET_RATE_LIMIT", "5 per hour"))
def request_password_reset():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return {"error": "email is required"}, 400

    user = User.query.filter_by(email=email).first()
    response = {"message": "If that account exists, a password reset link has been issued."}
    if not user:
        return response, 202

    token = _password_reset_serializer().dumps({"user_id": user.id, "email": user.email})
    AuditLog.record(
        "user.password_reset_requested",
        actor_id=user.id,
        actor_role=user.role.value,
        target_type="user",
        target_id=user.id,
        metadata={"email_hash": _email_hash(user.email)},
        request=request,
    )
    db.session.commit()

    current_app.logger.info(
        "user.password_reset.requested",
        extra={"user_id": user.id, "email_hash": _email_hash(user.email)},
    )
    if (current_app.config.get("ENV") or "development") != "production":
        response["reset_token"] = token
    return response, 202


@auth_bp.route("/password-reset/confirm", methods=["POST"])
@limiter.limit(lambda: current_app.config.get("PASSWORD_RESET_RATE_LIMIT", "5 per hour"))
def confirm_password_reset():
    data = request.get_json() or {}
    token = (data.get("token") or "").strip()
    new_password = data.get("password") or ""
    if not token or not new_password:
        return {"error": "token and password are required"}, 400
    if len(new_password) < 8:
        return {"error": "password must be at least 8 characters"}, 400

    try:
        payload = _password_reset_serializer().loads(
            token,
            max_age=current_app.config.get("PASSWORD_RESET_TOKEN_TTL_SECONDS", 1800),
        )
    except SignatureExpired:
        return {"error": "reset token expired"}, 400
    except BadSignature:
        return {"error": "invalid reset token"}, 400

    user = db.session.get(User, int(payload["user_id"]))
    if not user or user.email != payload.get("email"):
        return {"error": "user not found"}, 404

    user.set_password(new_password, bcrypt)
    AuditLog.record(
        "user.password_reset_completed",
        actor_id=user.id,
        actor_role=user.role.value,
        target_type="user",
        target_id=user.id,
        metadata={"email_hash": _email_hash(user.email)},
        request=request,
    )
    db.session.commit()
    return {"message": "password updated"}, 200



# ==========================
# CURRENT USER
# ==========================
@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    user = db.session.get(User, int(get_jwt_identity()))

    if not user:
        return {"error": "not found"}, 404

   

    return _serialize_user(user), 200



# ==========================
# UPLOAD DOCUMENT (PROVIDER)
# ==========================
@auth_bp.route("/upload_document", methods=["POST"])
@jwt_required()
def upload_document():
    user = db.session.get(User, int(get_jwt_identity()))

    # ------------------ BASIC CHECKS ------------------
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

    # ------------------ SAVE FILE ------------------
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)

    try:
        stored = store_upload(
            file,
            folder="kyc",
            allowed_extensions=current_app.config.get("ALLOWED_DOCUMENT_EXTENSIONS"),
            user_id=user.id,
        )
    except Exception as exc:
        current_app.logger.error(
            "upload.failed",
            extra={"user_id": user.id, "error": str(exc)},
        )
        return {"error": "upload failed"}, 500
    file_path = stored["local_path"]

    # ------------------ FILE TYPE ------------------
    is_pdf = file.filename.lower().endswith(".pdf")

    # ------------------ ML-BYPASS: skip verification if libs not installed ------------------
    if not FACE_VERIFY_AVAILABLE:
        user.document_filename = stored["storage_ref"]
        user.document_type = doc_type or "other"
        user.verification_status = VerificationStatus.document_verified
        user.verification_notes = "ML verification skipped (unavailable in environment)"
        user.is_verified = False
        user.requires_selfie = False
        db.session.commit()
        return {
            "message": "Document accepted (verification skipped — ML unavailable)",
            "next": "/provider_verification_video",
            "requires_selfie": False,
            "verification_status": user.verification_status.value,
        }, 201

    # ------------------ IMAGE QUALITY CHECKS ------------------
    if not is_pdf:
        if is_blurry(file_path):
            return {"error": "Document image too blurry"}, 400

        if is_screenshot(file_path):
            return {"error": "Screenshots are not allowed"}, 400

    # ------------------ OCR ------------------
    text = extract_text(file_path)

    if not text or not text.strip():
        return {
            "error": "No readable text found. Upload a clear original document."
        }, 400

    text = text.lower()
    normalized_doc_type = doc_type
    if doc_type in ["driving license", "driving licence"]:
        normalized_doc_type = "driving"
    if doc_type not in {"aadhaar", "passport", "driving", "driving license", "driving licence", "other"}:
        return {"error": "unsupported document type"}, 400
    is_valid = validate_document(text, normalized_doc_type)

    if not is_valid:
        return {
            "error": "Invalid document image. Upload a clear original document."
        }, 400

    # ------------------ FACE EXTRACTION (OPTIONAL) ------------------
    doc_face_saved = False

    if not is_pdf:
        doc_face_path = os.path.join(
            upload_folder,
            f"user_{user.id}_doc_face.jpg"
        )
        doc_face_saved = extract_and_save_document_face(file_path, doc_face_path)

    # ⚠️ IMPORTANT: NEVER FAIL DOCUMENT STAGE DUE TO FACE
    if doc_face_saved:
        user.requires_selfie = False
        verification_notes = "Document verified, face extracted"
    else:
        user.requires_selfie = True
        verification_notes = "Document verified (no face found, selfie required)"

    # ------------------ UPDATE USER ------------------
    user.document_filename = stored["storage_ref"]
    user.document_type = normalized_doc_type
    user.verification_status = VerificationStatus.document_verified
    user.verification_notes = verification_notes
    user.is_verified = False

    db.session.commit()

    # ------------------ RESPONSE ------------------
    return {
        "message": "Document verified successfully",
        "next": "/provider_verification_selfie" if user.requires_selfie else "/provider_verification_video",
        "requires_selfie": user.requires_selfie,
        "verification_status": user.verification_status.value,
    }, 201

# ==========================
# UPLOAD SELFIE
# ==========================
@auth_bp.route("/upload_selfie", methods=["POST"])
@jwt_required()
def upload_selfie():
    user = db.session.get(User, int(get_jwt_identity()))

    if not user:
        return {"error": "unauthenticated"}, 401

    if user.verification_status != VerificationStatus.document_verified:
        return {"error": "document verification required"}, 400

    file = request.files.get("file")
    if not file:
        return {"error": "selfie image required"}, 400

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)

    try:
        stored = store_upload(
            file,
            folder="kyc",
            allowed_extensions={"jpg", "jpeg", "png"},
            user_id=user.id,
        )
    except Exception as exc:
        current_app.logger.error(
            "upload.failed",
            extra={"user_id": user.id, "error": str(exc)},
        )
        return {"error": "upload failed"}, 500
    selfie_path = stored["local_path"]

    if FACE_VERIFY_AVAILABLE:
        face = extract_face_from_image(selfie_path)
        if face is None:
            return {"error": "No clear face detected in selfie"}, 400

    # ✅ SAVE SELFIE REFERENCE
    user.selfie_filename = stored["storage_ref"]
    user.requires_selfie = False
    user.verification_notes = "Selfie captured successfully"

    db.session.commit()

    return {
        "message": "Selfie uploaded successfully",
        "next": "/provider_verification_video"
    }, 201


# ==========================
# UPLOAD VERIFICATION VIDEO
# ==========================
@auth_bp.route("/upload_verification_video", methods=["POST"])
@jwt_required()
def upload_verification_video():
    user = db.session.get(User, int(get_jwt_identity()))

    # --------------------
    # BASIC CHECKS
    # --------------------
    if not user:
        return {"error": "unauthenticated"}, 401

    # Allow retries after a previous face mismatch rejection without forcing
    # users to repeat document upload.
    if user.verification_status not in {
        VerificationStatus.document_verified,
        VerificationStatus.rejected,
    }:
        return {"error": "document verification required"}, 400
    if user.verification_status == VerificationStatus.rejected and not user.document_filename:
        return {"error": "document verification required"}, 400

    file = request.files.get("file")
    if not file:
        return {"error": "video required"}, 400
    raw_name = (file.filename or "").strip()
    incoming_ext = raw_name.rsplit(".", 1)[-1].lower() if "." in raw_name else ""
    allowed_video_exts = {"mp4", "mov", "webm"}
    if incoming_ext not in allowed_video_exts:
        inferred_ext = _infer_video_extension(getattr(file, "content_type", None)) or "webm"
        file.filename = f"verification.{inferred_ext}"

    # --------------------
    # SAVE VIDEO
    # --------------------
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)

    try:
        stored = store_upload(
            file,
            folder="kyc",
            allowed_extensions=allowed_video_exts,
            user_id=user.id,
        )
    except Exception as exc:
        current_app.logger.error(
            "upload.failed",
            extra={"user_id": user.id, "error": str(exc)},
        )
        details = None
        if (os.getenv("FLASK_ENV") or current_app.config.get("FLASK_ENV") or "production").lower() != "production":
            details = str(exc)
        response = {"error": "upload failed"}
        if details:
            response["details"] = details
        return response, 500
    video_path = stored["local_path"]

    # --------------------
    # ML BYPASS: skip face matching if libs not installed
    # --------------------
    if not FACE_VERIFY_AVAILABLE:
        user.verification_video_filename = stored["storage_ref"]
        user.verification_status = VerificationStatus.face_verified
        user.verification_notes = "Video accepted (ML verification skipped — unavailable in environment)"
        db.session.commit()
        return {"message": "Video accepted (verification skipped)", "next": "/confirm_location"}, 201

    # --------------------
    # LOAD REFERENCE FACE
    # Priority: Document → Selfie
    # --------------------
    reference_face = None
    reference_source = None

    # 1️⃣ Document face (if extracted earlier)
    doc_face_path = os.path.join(
        upload_folder,
        f"user_{user.id}_doc_face.jpg"
    )

    if os.path.exists(doc_face_path):
        reference_face = load_document_face(doc_face_path)
        reference_source = "document"

    # 2️⃣ Selfie fallback (REQUIRED for PDF docs)
    if reference_face is None and getattr(user, "selfie_filename", None):
        selfie_path = resolve_reference_path(user.selfie_filename)
        reference_face = extract_face_from_image(selfie_path)
        reference_source = "selfie"

    # ❌ No reference face → stop
    if reference_face is None:
        return {
            "error": "Selfie required for PDF or no-face documents"
        }, 400

    # --------------------
    # EXTRACT VIDEO FACES
    # --------------------
    video_faces = extract_video_faces(video_path)

    if video_faces is None:
        return {
            "error": "Video format not supported. Please retake or use a different browser."
        }, 400

    if not video_faces:
        return {"error": "No face detected in video"}, 400

    # --------------------
    # FACE MATCH (LBPH – beard safe)
    # --------------------
    if not faces_match(reference_face, video_faces):
        user.verification_status = VerificationStatus.rejected
        user.verification_notes = (
            f"Face mismatch ({reference_source} vs video); retry required"
        )
        db.session.commit()

        return {"error": "Face does not match reference"}, 400

    # --------------------
    # VERIFIED
    # --------------------
    user.verification_video_filename = stored["storage_ref"]
    user.verification_status = VerificationStatus.face_verified
    user.verification_notes = (
        f"Face verified successfully ({reference_source})"
    )

    db.session.commit()

    return {
        "message": "Face verified successfully",
        "next": "/confirm_location"
    }, 201




# ==========================
# UPLOAD LOCATION CONFIRMATION
# ==========================
@auth_bp.route("/confirm_location", methods=["POST"])
@jwt_required()
def confirm_location():
    user = db.session.get(User, int(get_jwt_identity()))

    if not user:
        return {"error": "unauthenticated"}, 401

    # 🔐 Must complete face verification first
    if user.verification_status != VerificationStatus.face_verified:
        return {"error": "face verification required"}, 400

    data = request.get_json() or {}

    lat = data.get("latitude")
    lon = data.get("longitude")

    if lat is None or lon is None:
        return {"error": "location required"}, 400

    # 📍 Save location
    user.latitude = lat
    user.longitude = lon

    # ✅ Final verification state
    user.verification_status = VerificationStatus.completed
    user.is_verified = True

    # ⭐ Trust score (increment only once)
    if not user.trust_score:
        user.trust_score = 0

    user.trust_score += 30

    # 🏅 Assign badges
    user.badges = compute_badges(user)

    db.session.commit()

    return {
        "message": "Verification completed",
        "trust_score": user.trust_score,
        "badges": user.badges
    }, 200


# ==========================
# LOGOUT
# ==========================
@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    from ..models import TokenBlocklist
    jti = get_jwt()["jti"]
    db.session.add(TokenBlocklist(jti=jti))
    db.session.commit()
    return jsonify({"message": "Successfully logged out"}), 200

# ==========================
# PASSWORD RESET & EMAIL VERIFICATION
# ==========================
from ..services.notification_delivery import send_email

def _password_reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")

@auth_bp.route("/forgot-password", methods=["POST"])
@limiter.limit(lambda: current_app.config.get("PASSWORD_RESET_RATE_LIMIT", "5 per hour"))
def forgot_password():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    
    if not email:
        return {"error": "email required"}, 400
        
    user = User.query.filter_by(email=email).first()
    if user:
        s = _password_reset_serializer()
        token = s.dumps(user.email)
        reset_link = f"{request.host_url}reset-password?token={token}"
        send_email(
            recipient=user, 
            title="Reset Your Sklio Password", 
            body=f"Click the link to reset your password: {reset_link}"
        )
        
    return {"message": "If an account exists, a password reset link has been sent."}, 200

@auth_bp.route("/reset-password", methods=["POST"])
@limiter.limit(lambda: current_app.config.get("PASSWORD_RESET_RATE_LIMIT", "5 per hour"))
def reset_password():
    data = request.get_json() or {}
    token = data.get("token")
    new_password = data.get("new_password")
    
    if not token or not new_password:
        return {"error": "token and new_password required"}, 400
        
    s = _password_reset_serializer()
    try:
        email = s.loads(token, max_age=3600) # 1 hour
    except SignatureExpired:
        return {"error": "token expired"}, 400
    except BadSignature:
        return {"error": "invalid token"}, 400
        
    user = User.query.filter_by(email=email).first()
    if not user:
        return {"error": "user not found"}, 404
        
    user.set_password(new_password, bcrypt)
    db.session.commit()
    
    return {"message": "Password updated successfully"}, 200

@auth_bp.route("/send-verification-email", methods=["POST"])
@jwt_required()
@limiter.limit(lambda: current_app.config.get("AUTH_RATE_LIMIT", "5 per minute"))
def send_verification_email():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return {"error": "unauthenticated"}, 401
        
    if user.is_email_verified:
        return {"message": "Email already verified"}, 200
        
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="email-verify")
    token = s.dumps(user.email)
    verify_link = f"{request.host_url}verify-email?token={token}"
    
    send_email(
        recipient=user,
        title="Verify your Sklio Email",
        body=f"Click the link to verify your email address: {verify_link}"
    )
    
    return {"message": "Verification email sent"}, 200

@auth_bp.route("/verify-email", methods=["POST"])
@limiter.limit(lambda: current_app.config.get("AUTH_RATE_LIMIT", "5 per minute"))
def verify_email():
    data = request.get_json() or {}
    token = data.get("token")
    
    if not token:
        return {"error": "token required"}, 400
        
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="email-verify")
    try:
        email = s.loads(token, max_age=86400) # 24 hours
    except SignatureExpired:
        return {"error": "token expired"}, 400
    except BadSignature:
        return {"error": "invalid token"}, 400
        
    user = User.query.filter_by(email=email).first()
    if not user:
        return {"error": "user not found"}, 404
        
    user.is_email_verified = True
    db.session.commit()
    
    return {"message": "Email verified successfully"}, 200
