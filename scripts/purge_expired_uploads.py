from pathlib import Path
from time import time
import argparse
import os

from app import create_app


def purge_expired_uploads():
    app = create_app()
    upload_dir = Path(app.config["UPLOAD_FOLDER"])
    retention_days = int(app.config.get("DOCUMENT_RETENTION_DAYS", 30))
    cutoff = time() - (retention_days * 24 * 60 * 60)
    quarantine_retention_days = int(
        app.config.get("CHAT_ATTACHMENT_QUARANTINE_RETENTION_DAYS", 14)
    )
    quarantine_cutoff = time() - (quarantine_retention_days * 24 * 60 * 60)

    if not upload_dir.exists():
        print(f"Upload directory does not exist: {upload_dir}")
        return 0

    deleted = 0
    for path in upload_dir.rglob("*"):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        path_cutoff = quarantine_cutoff if "quarantine" in path.parts else cutoff
        if path.stat().st_mtime < path_cutoff:
            path.unlink()
            deleted += 1

    for directory in sorted(
        [path for path in upload_dir.rglob("*") if path.is_dir()],
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        if any(directory.iterdir()):
            continue
        directory.rmdir()

    print(
        f"Deleted {deleted} expired upload(s) from {upload_dir} "
        f"using a {retention_days}-day standard retention window and "
        f"{quarantine_retention_days}-day quarantine retention window."
    )
    return deleted


def migrate_uploads_to_s3():
    bucket = os.getenv("S3_BUCKET_NAME")
    if not bucket:
        raise SystemExit("S3_BUCKET_NAME is required")

    import boto3

    app = create_app()
    upload_dir = Path(app.config["UPLOAD_FOLDER"])
    if not upload_dir.exists():
        print(f"Upload directory does not exist: {upload_dir}")
        return 0

    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION", "ap-south-1"),
    )

    migrated = 0
    for file_path in upload_dir.rglob("*"):
        if not file_path.is_file() or file_path.name == ".gitkeep":
            continue
        key = str(file_path).replace("\\", "/")
        s3.upload_file(str(file_path), bucket, key)
        migrated += 1
        print(f"Uploaded {file_path} -> s3://{bucket}/{key}")

    print("Migration complete. Update DB references if needed.")
    return migrated


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--migrate-to-s3", action="store_true")
    args = parser.parse_args()

    if args.migrate_to_s3:
        migrate_uploads_to_s3()
    else:
        purge_expired_uploads()
