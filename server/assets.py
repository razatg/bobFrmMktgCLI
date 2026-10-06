"""Validated, client-scoped source asset storage for hosted conversations."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path


MAX_UPLOAD_BYTES = 100 * 1024 * 1024
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


class AssetValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class StoredUpload:
    original_name: str
    media_type: str
    size_bytes: int
    sha256: str
    storage_relpath: str


def safe_original_name(value: str) -> str:
    name = Path(str(value or "upload")).name
    name = re.sub(r"[\x00-\x1f\x7f]+", "", name).strip()
    return (name or "upload")[:180]


def detect_media(header: bytes) -> tuple[str, str] | None:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "video/mp4", ".mp4"
    return None


def asset_storage_root(state_root: Path) -> Path:
    return (state_root / "client-assets").resolve()


def resolve_asset_path(state_root: Path, storage_relpath: str) -> Path | None:
    root = asset_storage_root(state_root)
    candidate = state_root.resolve() / storage_relpath
    target = candidate.resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target if target.is_file() and not candidate.is_symlink() else None


async def store_upload(
    chunks: AsyncIterable[bytes],
    state_root: Path,
    client_id: str,
    asset_id: str,
    original_name: str,
    content_length: int | None = None,
) -> StoredUpload:
    if not _SAFE_ID.fullmatch(client_id) or not _SAFE_ID.fullmatch(asset_id):
        raise AssetValidationError("invalid asset scope")
    if content_length is not None and content_length > MAX_UPLOAD_BYTES:
        raise AssetValidationError("file is larger than the 100 MB upload limit", 413)

    state_root = state_root.resolve()
    directory = asset_storage_root(state_root) / client_id / asset_id
    directory.mkdir(parents=True, exist_ok=False)
    temporary = directory / ".upload"
    digest = hashlib.sha256()
    header = bytearray()
    size = 0
    try:
        with temporary.open("wb") as output:
            async for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise AssetValidationError("file is larger than the 100 MB upload limit", 413)
                if len(header) < 32:
                    header.extend(chunk[: 32 - len(header)])
                digest.update(chunk)
                output.write(chunk)
        media = detect_media(bytes(header))
        if not size:
            raise AssetValidationError("uploaded file is empty")
        if not media:
            raise AssetValidationError("only PNG, JPEG, WebP, and MP4 files are supported")
        media_type, extension = media
        final_path = directory / f"original{extension}"
        os.replace(temporary, final_path)
        relative = str(final_path.relative_to(state_root))
        return StoredUpload(
            original_name=safe_original_name(original_name),
            media_type=media_type,
            size_bytes=size,
            sha256=digest.hexdigest(),
            storage_relpath=relative,
        )
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
