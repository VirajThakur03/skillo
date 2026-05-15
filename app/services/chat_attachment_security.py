import json
import os
import socket
import struct
import uuid
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename

from .storage_service import store_upload


def _scan_mode():
    return (current_app.config.get("CHAT_ATTACHMENT_SCAN_MODE") or "basic").strip().lower()


def _require_scan():
    return bool(current_app.config.get("CHAT_ATTACHMENT_REQUIRE_SCAN", True))


def _upload_root():
    return Path(current_app.config.get("UPLOAD_FOLDER", ".")).resolve()


def _extension_from_name(filename):
    safe = secure_filename(filename or "")
    return safe.rsplit(".", 1)[-1].lower() if "." in safe else ""


def _read_upload_bytes(file_obj):
    stream = getattr(file_obj, "stream", None) or file_obj
    current_pos = None
    try:
        current_pos = stream.tell()
    except Exception:
        current_pos = None

    try:
        if hasattr(stream, "seek"):
            stream.seek(0)
        data = stream.read()
        return data or b""
    finally:
        if current_pos is not None and hasattr(stream, "seek"):
            stream.seek(current_pos)


def _write_quarantine_record(*, room, original_name, extension, content_bytes, reason, user_id):
    quarantine_root = _upload_root() / "quarantine" / "chat" / room
    quarantine_root.mkdir(parents=True, exist_ok=True)

    safe_name = secure_filename(original_name or f"upload.{extension or 'bin'}")
    stem = uuid.uuid4().hex
    file_path = quarantine_root / f"{stem}_{safe_name}"
    metadata_path = quarantine_root / f"{stem}_{safe_name}.json"

    file_path.write_bytes(content_bytes)
    metadata_path.write_text(
        json.dumps(
            {
                "room": room,
                "user_id": user_id,
                "original_name": original_name,
                "extension": extension,
                "reason": reason,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    current_app.logger.warning(
        "chat.attachment_quarantined",
        extra={
            "user_id": user_id,
            "room": room,
            "file_name": safe_name,
            "reason": reason,
            "quarantine_path": str(file_path),
        },
    )

    return str(file_path)


def _is_probably_clean_basic(content_bytes, extension):
    if not content_bytes:
        return False, "empty upload"

    suspicious_markers = (
        b"<script",
        b"<?php",
        b"javascript:",
        b"powershell",
        b"cmd.exe",
    )
    lowered = content_bytes[:4096].lower()
    if any(marker in lowered for marker in suspicious_markers):
        return False, "suspicious embedded content"

    signatures = {
        "pdf": lambda data: data.startswith(b"%PDF-"),
        "jpg": lambda data: data.startswith(b"\xff\xd8\xff"),
        "jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
        "png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
        "gif": lambda data: data.startswith((b"GIF87a", b"GIF89a")),
        "webp": lambda data: data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    }

    validator = signatures.get(extension)
    if validator and not validator(content_bytes):
        return False, f"invalid {extension} signature"

    return True, "basic validation passed"


def _clamav_scan_bytes(content_bytes):
    host = (current_app.config.get("CLAMAV_HOST") or "").strip()
    port = int(current_app.config.get("CLAMAV_PORT") or 3310)
    timeout = int(current_app.config.get("CLAMAV_TIMEOUT_SECONDS") or 5)

    if not host:
        raise RuntimeError("CLAMAV_HOST is not configured")

    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(b"zINSTREAM\0")
        chunk_size = 65536
        view = memoryview(content_bytes)
        for idx in range(0, len(content_bytes), chunk_size):
            chunk = view[idx: idx + chunk_size]
            sock.sendall(struct.pack(">I", len(chunk)))
            sock.sendall(chunk)
        sock.sendall(struct.pack(">I", 0))
        response = sock.recv(4096).decode("utf-8", errors="replace").strip()

    if "FOUND" in response:
        return False, response
    if "OK" in response:
        return True, response
    raise RuntimeError(response or "unknown scanner response")


def secure_store_chat_attachment(
    file_obj,
    *,
    room,
    user_id,
    allowed_extensions,
    max_size_mb,
):
    original_name = file_obj.filename or "upload"
    extension = _extension_from_name(original_name)
    content_bytes = _read_upload_bytes(file_obj)

    basic_clean, basic_reason = _is_probably_clean_basic(content_bytes, extension)
    if not basic_clean:
        _write_quarantine_record(
            room=room,
            original_name=original_name,
            extension=extension,
            content_bytes=content_bytes,
            reason=basic_reason,
            user_id=user_id,
        )
        raise ValueError("Attachment rejected by security checks")

    mode = _scan_mode()
    if mode == "clamav":
        try:
            clam_clean, clam_reason = _clamav_scan_bytes(content_bytes)
        except Exception as exc:
            if _require_scan():
                _write_quarantine_record(
                    room=room,
                    original_name=original_name,
                    extension=extension,
                    content_bytes=content_bytes,
                    reason=f"clamav unavailable: {exc}",
                    user_id=user_id,
                )
                raise ValueError("Attachment is pending security review")
            current_app.logger.warning(
                "chat.attachment_scan_degraded",
                extra={"user_id": user_id, "room": room, "reason": str(exc)},
            )
        else:
            if not clam_clean:
                _write_quarantine_record(
                    room=room,
                    original_name=original_name,
                    extension=extension,
                    content_bytes=content_bytes,
                    reason=clam_reason,
                    user_id=user_id,
                )
                raise ValueError("Attachment rejected by malware scanner")
            current_app.logger.info(
                "chat.attachment_scan_passed",
                extra={"user_id": user_id, "room": room, "scan_mode": "clamav", "detail": clam_reason},
            )
    elif mode == "none" and _require_scan():
        _write_quarantine_record(
            room=room,
            original_name=original_name,
            extension=extension,
            content_bytes=content_bytes,
            reason="scan mode disabled while scan required",
            user_id=user_id,
        )
        raise ValueError("Attachment scanning is required before upload")
    else:
        current_app.logger.info(
            "chat.attachment_scan_passed",
            extra={"user_id": user_id, "room": room, "scan_mode": "basic", "detail": basic_reason},
        )

    if hasattr(file_obj, "stream") and hasattr(file_obj.stream, "seek"):
        file_obj.stream.seek(0)

    stored = store_upload(
        file_obj,
        folder=f"chat/{room}",
        allowed_extensions=allowed_extensions,
        max_size_mb=max_size_mb,
        user_id=user_id,
    )
    stored["original_name"] = secure_filename(original_name or "attachment")
    return stored
