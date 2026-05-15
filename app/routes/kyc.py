from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from ..extensions import db
from ..models import AuditLog, KycDocument, KycStatus, RoleEnum, User
from ..services.storage_service import store_upload


kyc_bp = Blueprint("kyc", __name__, url_prefix="/api/kyc")
admin_bp = Blueprint("admin_kyc", __name__, url_prefix="/api/admin/kyc")

ALLOWED_DOC_TYPES = {
    "id_front",
    "id_back",
    "selfie",
    "bank_proof",
    "skill_certificate",
}
REQUIRED_DOC_TYPES = {"id_front", "id_back", "selfie", "bank_proof"}
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}
DOC_LABELS = {
    "id_front": "Government ID front",
    "id_back": "Government ID back",
    "selfie": "Selfie",
    "bank_proof": "Bank proof",
    "skill_certificate": "Skill certificate",
}
DEFAULT_REVIEW_SLA = "24-48 hours after all required documents are submitted"


def _current_user():
    return db.session.get(User, int(get_jwt_identity()))


def _provider_required():
    user = _current_user()
    if not user:
        return None, (jsonify({"error": "unauthenticated"}), 401)
    if user.role != RoleEnum.PROVIDER:
        return None, (jsonify({"error": "only providers allowed"}), 403)
    return user, None


def _admin_required():
    user = _current_user()
    admin_email = (current_app.config.get("ADMIN_EMAIL") or "").strip().lower()
    if not user:
        return None, (jsonify({"error": "unauthenticated"}), 401)
    if not admin_email or user.email.lower() != admin_email:
        return None, (jsonify({"error": "admin access required"}), 403)
    return user, None


def _sync_kyc_state(provider):
    submitted_types = {doc.doc_type for doc in provider.kyc_documents}
    if REQUIRED_DOC_TYPES.issubset(submitted_types):
        if provider.kyc_status in {KycStatus.pending, KycStatus.rejected}:
            provider.kyc_status = KycStatus.documents_submitted
        if provider.kyc_submitted_at is None:
            provider.kyc_submitted_at = datetime.now(timezone.utc)
        provider.kyc_rejection_reason = None
        provider.kyc_rejected_at = None


def _serialize_document(document):
    return {
        "doc_type": document.doc_type,
        "label": DOC_LABELS.get(document.doc_type, document.doc_type.replace("_", " ").title()),
        "file_url": document.file_url,
        "created_at": document.created_at.isoformat() if document.created_at else None,
    }


def _status_copy(provider):
    status = provider.kyc_status
    if status == KycStatus.approved:
        return {
            "title": "KYC approved",
            "description": "Your provider profile is bookable in search and ready for live jobs.",
        }
    if status == KycStatus.rejected:
        return {
            "title": "KYC needs attention",
            "description": provider.kyc_rejection_reason or "One or more documents need to be updated before your profile can go live again.",
        }
    if status == KycStatus.documents_submitted:
        return {
            "title": "Documents received",
            "description": "Your required documents are submitted. Review usually completes within 24 to 48 hours.",
        }
    if status == KycStatus.under_review:
        return {
            "title": "KYC under review",
            "description": "A reviewer is checking your documents. You can still manage existing jobs while review is in progress.",
        }
    if status == KycStatus.suspended:
        return {
            "title": "Account suspended",
            "description": provider.kyc_rejection_reason or "Your provider profile is temporarily suspended from new jobs. Please contact support.",
        }
    return {
        "title": "KYC not started",
        "description": "Upload the required documents to become bookable in search and unlock live marketplace traffic.",
    }


def _kyc_status_payload(provider):
    submitted_docs = {doc.doc_type for doc in provider.kyc_documents}
    required_remaining = sorted(REQUIRED_DOC_TYPES - submitted_docs)
    status_copy = _status_copy(provider)
    reupload_types = (
        sorted(REQUIRED_DOC_TYPES)
        if provider.kyc_status == KycStatus.rejected
        else required_remaining
    )
    return {
        "provider_id": provider.id,
        "kyc_status": provider.kyc_status.value,
        "status_title": status_copy["title"],
        "status_description": status_copy["description"],
        "discoverability_blocked": provider.kyc_status != KycStatus.approved,
        "job_acceptance_blocked": provider.kyc_status == KycStatus.suspended,
        "required_documents": [
            {"doc_type": doc_type, "label": DOC_LABELS.get(doc_type, doc_type.replace("_", " ").title())}
            for doc_type in sorted(REQUIRED_DOC_TYPES)
        ],
        "required_documents_remaining": required_remaining,
        "reupload_document_types": reupload_types,
        "documents": [_serialize_document(document) for document in provider.kyc_documents],
        "submitted_at": provider.kyc_submitted_at.isoformat() if provider.kyc_submitted_at else None,
        "approved_at": provider.kyc_approved_at.isoformat() if provider.kyc_approved_at else None,
        "rejected_at": provider.kyc_rejected_at.isoformat() if provider.kyc_rejected_at else None,
        "rejection_reason": provider.kyc_rejection_reason,
        "review_sla": DEFAULT_REVIEW_SLA,
    }


@kyc_bp.route("/upload", methods=["POST"])
@jwt_required()
def upload_kyc_document():
    provider, error = _provider_required()
    if error:
        return error

    doc_type = (request.form.get("doc_type") or "").strip().lower()
    if doc_type not in ALLOWED_DOC_TYPES:
        return jsonify({"error": "invalid doc_type"}), 400

    file = request.files.get("file")
    if not file:
        return jsonify({"error": "file is required"}), 400
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        return jsonify({"error": "Only JPG, PNG, and PDF files are allowed"}), 400

    extension = file.filename.rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if extension not in {"jpg", "jpeg", "png", "pdf"}:
        return jsonify({"error": "invalid file extension"}), 400

    try:
        stored = store_upload(
            file,
            folder="kyc/private",
            allowed_extensions={"jpg", "jpeg", "png", "pdf"},
            user_id=provider.id,
        )
    except Exception as exc:
        current_app.logger.error(
            "upload.failed",
            extra={"user_id": provider.id, "error": str(exc)},
        )
        return jsonify({"error": "Upload failed. Please try again."}), 500

    existing = KycDocument.query.filter_by(provider_id=provider.id, doc_type=doc_type).first()
    if existing:
        existing.file_url = stored["storage_ref"]
        existing.created_at = datetime.now(timezone.utc)
    else:
        db.session.add(
            KycDocument(
                provider_id=provider.id,
                doc_type=doc_type,
                file_url=stored["storage_ref"],
            )
        )

    _sync_kyc_state(provider)
    AuditLog.record(
        "kyc.document_uploaded",
        actor_id=provider.id,
        actor_role=provider.role.value,
        target_type="provider",
        target_id=provider.id,
        metadata={
            "provider_id": provider.id,
            "doc_type": doc_type,
        },
        request=request,
    )
    db.session.commit()

    return jsonify(
        {
            "status": "uploaded",
            "kyc_status": provider.kyc_status.value,
            "required_documents_remaining": sorted(
                REQUIRED_DOC_TYPES - {doc.doc_type for doc in provider.kyc_documents}
            ),
        }
    )


@kyc_bp.route("/status", methods=["GET"])
@jwt_required()
def get_kyc_status():
    provider, error = _provider_required()
    if error:
        return error

    return jsonify(_kyc_status_payload(provider)), 200


@admin_bp.route("/pending", methods=["GET"])
@jwt_required()
def list_pending_kyc():
    admin, error = _admin_required()
    if error:
        return error
    _ = admin

    providers = (
        User.query.filter(User.kyc_status.in_([KycStatus.documents_submitted, KycStatus.under_review]))
        .order_by(User.kyc_submitted_at.asc().nullslast(), User.id.asc())
        .all()
    )
    return jsonify(
        {
            "providers": [
                {
                    "id": provider.id,
                    "name": provider.name,
                    "email": provider.email,
                    "kyc_status": provider.kyc_status.value,
                    "submitted_at": provider.kyc_submitted_at.isoformat() if provider.kyc_submitted_at else None,
                    "documents": [
                        {
                            "doc_type": doc.doc_type,
                            "file_url": doc.file_url,
                            "created_at": doc.created_at.isoformat(),
                        }
                        for doc in provider.kyc_documents
                    ],
                }
                for provider in providers
            ]
        }
    )


@admin_bp.route("/<int:provider_id>/approve", methods=["POST"])
@jwt_required()
def approve_kyc(provider_id):
    admin, error = _admin_required()
    if error:
        return error

    provider = User.query.get_or_404(provider_id)
    if provider.role != RoleEnum.PROVIDER:
        return jsonify({"error": "provider not found"}), 404

    provider.kyc_status = KycStatus.approved
    provider.kyc_approved_at = datetime.now(timezone.utc)
    provider.kyc_approved_by = admin.id
    provider.kyc_rejected_at = None
    provider.kyc_rejection_reason = None
    AuditLog.record(
        "kyc.approved",
        actor_id=admin.id,
        actor_role="admin",
        target_type="provider",
        target_id=provider.id,
        metadata={
            "provider_id": provider.id,
            "approved_by_admin_id": admin.id,
        },
        request=request,
    )
    db.session.commit()

    current_app.logger.info(
        "kyc.approved",
        extra={"provider_id": provider.id, "admin_id": admin.id},
    )
    return jsonify({"status": "approved", "provider_id": provider.id})


@admin_bp.route("/<int:provider_id>/reject", methods=["POST"])
@jwt_required()
def reject_kyc(provider_id):
    admin, error = _admin_required()
    if error:
        return error

    provider = User.query.get_or_404(provider_id)
    if provider.role != RoleEnum.PROVIDER:
        return jsonify({"error": "provider not found"}), 404

    reason = (request.get_json(silent=True) or {}).get("reason", "").strip()
    if not reason:
        return jsonify({"error": "rejection reason is required"}), 400

    provider.kyc_status = KycStatus.rejected
    provider.kyc_rejected_at = datetime.now(timezone.utc)
    provider.kyc_rejection_reason = reason
    provider.kyc_approved_at = None
    provider.kyc_approved_by = None
    AuditLog.record(
        "kyc.rejected",
        actor_id=admin.id,
        actor_role="admin",
        target_type="provider",
        target_id=provider.id,
        metadata={
            "provider_id": provider.id,
            "rejected_by": admin.id,
            "reason": reason,
        },
        request=request,
    )
    db.session.commit()

    current_app.logger.warning(
        "kyc.rejected",
        extra={"provider_id": provider.id, "admin_id": admin.id, "reason": reason},
    )
    return jsonify({"status": "rejected", "provider_id": provider.id, "reason": reason})
