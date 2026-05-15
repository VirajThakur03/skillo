import os
import tempfile
import urllib.request
import uuid

from flask import current_app
from werkzeug.utils import secure_filename


def _get_backend():
    return (current_app.config.get("STORAGE_BACKEND") or "local").lower()


def _get_upload_root():
    return current_app.config.get("UPLOAD_FOLDER", "/app/uploads/documents")


def _ensure_folder(path):
    os.makedirs(path, exist_ok=True)


def _extension_from_content_type(content_type):
    """Map known upload content types to file extensions."""
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    return {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "application/pdf": "pdf",
        "video/mp4": "mp4",
        "video/quicktime": "mov",
        "video/webm": "webm",
    }.get(normalized, "")


def _stream_size_bytes(file_obj):
    stream = getattr(file_obj, "stream", None)
    if stream is None:
        return getattr(file_obj, "content_length", None)

    try:
        current_pos = stream.tell()
        stream.seek(0, os.SEEK_END)
        size_bytes = stream.tell()
        stream.seek(current_pos)
        return size_bytes
    except Exception:
        return getattr(file_obj, "content_length", None)


def store_upload(file_obj, *, folder, allowed_extensions=None, user_id=None, max_size_mb=None):
    filename = secure_filename(file_obj.filename or "upload")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not ext:
        ext = _extension_from_content_type(getattr(file_obj, "content_type", None))
        if ext:
            filename = f"upload.{ext}"
    if allowed_extensions and ext not in allowed_extensions:
        raise ValueError(f"File type .{ext} not allowed")

    size_bytes = _stream_size_bytes(file_obj)
    if max_size_mb:
        max_size_bytes = int(max_size_mb * 1024 * 1024)
        if size_bytes is not None and size_bytes > max_size_bytes:
            raise ValueError(f"File too large. Maximum size is {max_size_mb} MB")

    current_app.logger.info(
        "upload.started",
        extra={
            "user_id": user_id,
            "file_type": ext,
            "folder": folder,
            "file_name": filename,
            "size_bytes": size_bytes,
        },
    )

    upload_root = _get_upload_root()
    local_dir = os.path.join(upload_root, folder)
    _ensure_folder(local_dir)

    local_name = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    local_path = os.path.join(local_dir, local_name)
    file_obj.save(local_path)

    backend = _get_backend()
    if backend == "s3":
        import boto3
        bucket = current_app.config.get("S3_BUCKET_NAME") or os.getenv("S3_BUCKET_NAME")
        access_key = current_app.config.get("AWS_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = current_app.config.get("AWS_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
        env = (os.getenv("FLASK_ENV") or current_app.config.get("FLASK_ENV") or "production").lower()

        if not bucket or not access_key or not secret_key:
            if env != "production":
                current_app.logger.warning(
                    "storage.s3.not_configured",
                    extra={"bucket": bool(bucket), "access_key": bool(access_key), "secret_key": bool(secret_key)},
                )
            else:
                raise RuntimeError("S3 storage is not configured")
        else:
            s3 = boto3.client(
                "s3",
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=current_app.config.get("AWS_REGION") or os.getenv("AWS_REGION", "ap-south-1"),
            )
            key = f"{folder}/{local_name}"
            with open(local_path, "rb") as handle:
                s3.upload_fileobj(
                    handle,
                    bucket,
                    key,
                    ExtraArgs={"ContentType": file_obj.content_type or "application/octet-stream"},
                )
            url = f"https://{bucket}.s3.amazonaws.com/{key}"
            current_app.logger.info(
                "upload.completed",
                extra={"user_id": user_id, "s3_key": key},
            )
            return {"local_path": local_path, "storage_ref": url}

    relative_ref = os.path.relpath(local_path, upload_root)
    current_app.logger.info(
        "upload.completed",
        extra={"user_id": user_id, "s3_key": relative_ref},
    )
    return {"local_path": local_path, "storage_ref": relative_ref}


def resolve_reference_path(reference):
    if not reference:
        return None

    upload_root = _get_upload_root()
    if reference.startswith("http://") or reference.startswith("https://"):
        suffix = os.path.basename(reference.split("?")[0])
        fd, temp_path = tempfile.mkstemp(prefix="download_", suffix=f"_{suffix}")
        os.close(fd)
        urllib.request.urlretrieve(reference, temp_path)
        return temp_path

    if os.path.isabs(reference):
        return reference
    return os.path.join(upload_root, reference)


def delete_reference(reference):
    if not reference:
        return

    backend = _get_backend()
    if backend == "s3" and (reference.startswith("http://") or reference.startswith("https://")):
        import boto3
        bucket = current_app.config.get("S3_BUCKET_NAME") or os.getenv("S3_BUCKET_NAME")
        if not bucket:
            return
        key = reference.split(f"{bucket}.s3.amazonaws.com/")[-1]
        s3 = boto3.client(
            "s3",
            aws_access_key_id=current_app.config.get("AWS_ACCESS_KEY_ID")
            or os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=current_app.config.get("AWS_SECRET_ACCESS_KEY")
            or os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=current_app.config.get("AWS_REGION") or os.getenv("AWS_REGION", "ap-south-1"),
        )
        s3.delete_object(Bucket=bucket, Key=key)
        return

    local_path = resolve_reference_path(reference)
    if local_path and os.path.exists(local_path):
        os.remove(local_path)
