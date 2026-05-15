from pathlib import Path

from flask import Blueprint, abort, current_app, make_response, redirect, request, send_file
from werkzeug.utils import secure_filename

from ..health import service_health
from ..services.feature_flags import frontend_feature_payload
from ..services.storage_service import resolve_reference_path


system_bp = Blueprint("system", __name__, url_prefix="/api/system")


@system_bp.route("/features", methods=["GET"])
def list_features():
    response = make_response(frontend_feature_payload(), 200)
    response.headers["Cache-Control"] = "public, max-age=60"
    return response


@system_bp.route("/health", methods=["GET"])
def health_check():
    checks = service_health(current_app)
    status_code = 200 if checks["status"] == "ok" else 503
    return {
        "status": checks["status"],
        "service": "sklio-backend",
        "environment": current_app.config.get("ENV", "development"),
        "checks": checks,
    }, status_code


@system_bp.route("/upload", methods=["GET"])
def serve_upload():
    reference = (request.args.get("ref") or "").strip()
    if not reference:
        abort(404)

    if reference.startswith("http://") or reference.startswith("https://"):
        return redirect(reference, code=302)

    resolved_path = resolve_reference_path(reference)
    if not resolved_path:
        abort(404)

    upload_root = Path(current_app.config.get("UPLOAD_FOLDER", "")).resolve()
    target = Path(resolved_path).resolve()
    try:
        target.relative_to(upload_root)
    except ValueError:
        abort(404)

    if not target.exists() or not target.is_file():
        abort(404)

    as_attachment = request.args.get("download") == "1"
    download_name = request.args.get("name")
    if download_name:
        download_name = secure_filename(download_name)

    return send_file(
        target,
        as_attachment=as_attachment,
        download_name=download_name or target.name,
        conditional=True,
        max_age=3600,
    )
