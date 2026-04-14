import io
import uuid
from datetime import timedelta

from minio import Minio

from core.config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
    logger,
)

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".md",
    ".markdown",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}

MAX_FILE_SIZE = 20 * 1024 * 1024


def get_minio_client() -> Minio:
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )


def _ensure_bucket(client: Minio) -> None:
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)


def is_allowed_file(filename: str) -> bool:
    if not filename:
        return False
    name = filename.lower()
    return any(name.endswith(ext) for ext in ALLOWED_EXTENSIONS)


def is_image_file(filename: str) -> bool:
    if not filename:
        return False
    name = filename.lower()
    return any(name.endswith(ext) for ext in IMAGE_EXTENSIONS)


def get_extension(filename: str) -> str:
    name = (filename or "").lower()
    for ext in sorted(ALLOWED_EXTENSIONS, key=len, reverse=True):
        if name.endswith(ext):
            return ext
    return ""


def upload_file(file_bytes: bytes, filename: str, folder: str = "documents") -> str:
    client = get_minio_client()
    _ensure_bucket(client)
    ext = get_extension(filename)
    object_name = f"{folder}/{uuid.uuid4().hex}{ext}"
    client.put_object(
        MINIO_BUCKET,
        object_name,
        io.BytesIO(file_bytes),
        length=len(file_bytes),
        content_type=_guess_content_type(ext),
    )
    logger.info("[STORAGE] Uploaded %s (%d bytes)", object_name, len(file_bytes))
    return object_name


def delete_file(object_name: str) -> None:
    if not object_name:
        return
    try:
        client = get_minio_client()
        client.remove_object(MINIO_BUCKET, object_name)
        logger.info("[STORAGE] Deleted %s", object_name)
    except Exception as exc:
        logger.warning("[STORAGE] Failed to delete %s: %s", object_name, exc)


def get_presigned_url(object_name: str, expires_hours: int = 1) -> str:
    if not object_name:
        return ""
    client = get_minio_client()
    return client.presigned_get_object(
        MINIO_BUCKET,
        object_name,
        expires=timedelta(hours=expires_hours),
    )


def _guess_content_type(ext: str) -> str:
    types = {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".bmp": "image/bmp",
    }
    return types.get(ext, "application/octet-stream")


def classify_file_type(filename: str) -> str:
    if not filename:
        return "unknown"
    name = filename.lower()
    if any(name.endswith(e) for e in IMAGE_EXTENSIONS):
        return "image"
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith((".doc", ".docx")):
        return "word"
    if name.endswith((".md", ".markdown")):
        return "markdown"
    return "unknown"
