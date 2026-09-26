"""Bounded operator camera evidence stored under CORE's own state directory."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
from typing import AsyncIterable


MAX_METADATA_BYTES = 32_768
MAX_VIDEO_BYTES = 64 * 1024 * 1024
MAX_JPEG_BYTES = 1 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MIN_FREE_BYTES = 512 * 1024 * 1024
OPERATIONS = frozenset({
    "운전 모드 변경", "수동 운전", "주행 목표 요청", "주행 취소",
    "도킹 요청", "언도크 요청", "도킹 취소", "차선 추종 변경",
    "비상 정지", "비상 정지 해제",
})
_WRITE_LOCK = asyncio.Lock()


class EvidenceError(ValueError):
    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def evidence_root() -> Path:
    return Path.home() / "captures"


def _invalid(message: str) -> EvidenceError:
    return EvidenceError("CAMERA_EVIDENCE_INVALID", 400, message)


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise _invalid("capture timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid("capture timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise _invalid("capture timestamp must include a timezone")
    return parsed


def _validate(metadata: object) -> tuple[str, int]:
    if not isinstance(metadata, dict) or type(metadata.get("schema_version")) is not int or metadata["schema_version"] != 1:
        raise _invalid("camera evidence schema is invalid")
    kind = metadata.get("kind")
    if kind == "video":
        required = {"schema_version", "kind", "mime_type", "started_at", "stopped_at",
                    "frame_count", "operations"}
        if set(metadata) != required or metadata["mime_type"] not in ("video/webm", "video/mp4"):
            raise _invalid("video metadata is invalid")
        started = _timestamp(metadata["started_at"])
        stopped = _timestamp(metadata["stopped_at"])
        if not 0 <= (stopped - started).total_seconds() <= 301:
            raise _invalid("video duration is invalid")
        if type(metadata["frame_count"]) is not int or not 1 <= metadata["frame_count"] <= 601:
            raise _invalid("video frame count is invalid")
        operations = metadata["operations"]
        if not isinstance(operations, list) or len(operations) > 200:
            raise _invalid("operation record is too long")
        for operation in operations:
            if (not isinstance(operation, dict)
                    or set(operation) != {"action", "result", "elapsed_ms"}
                    or not isinstance(operation["action"], str)
                    or operation["action"] not in OPERATIONS
                    or operation["result"] not in ("accepted", "failed")
                    or type(operation["elapsed_ms"]) is not int
                    or not 0 <= operation["elapsed_ms"] <= 300_000):
                raise _invalid("operation record is invalid")
        return ("webm" if metadata["mime_type"] == "video/webm" else "mp4", MAX_VIDEO_BYTES)
    if kind == "screenshot":
        required = {"schema_version", "kind", "mime_type", "saved_at", "sequence", "source"}
        if set(metadata) != required or metadata["mime_type"] != "image/jpeg":
            raise _invalid("screenshot metadata is invalid")
        _timestamp(metadata["saved_at"])
        if type(metadata["sequence"]) is not int or metadata["sequence"] < 1:
            raise _invalid("screenshot sequence is invalid")
        source = metadata["source"]
        if not isinstance(source, str) or not re.fullmatch(r"[A-Z0-9_-]{1,32}", source):
            raise _invalid("screenshot source is invalid")
        return "jpg", MAX_JPEG_BYTES
    raise _invalid("camera evidence kind is invalid")


async def _header(stream):
    buffer = bytearray()
    while len(buffer) < 4:
        try:
            buffer.extend(await anext(stream))
        except StopAsyncIteration as exc:
            raise _invalid("camera evidence header is missing") from exc
    length = int.from_bytes(buffer[:4], "little")
    if not 2 <= length <= MAX_METADATA_BYTES:
        raise _invalid("camera evidence metadata is too large")
    while len(buffer) < 4 + length:
        try:
            buffer.extend(await anext(stream))
        except StopAsyncIteration as exc:
            raise _invalid("camera evidence metadata is incomplete") from exc
        if len(buffer) > MAX_METADATA_BYTES + MAX_VIDEO_BYTES:
            raise _invalid("camera evidence body is too large")
    try:
        metadata = json.loads(buffer[4:4 + length])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _invalid("camera evidence metadata is not JSON") from exc
    return metadata, bytes(buffer[4 + length:])


def _media_valid(ext: str, first: bytes, last: bytes) -> bool:
    if ext == "jpg":
        return first.startswith(b"\xff\xd8") and last.endswith(b"\xff\xd9")
    if ext == "webm":
        return first.startswith(b"\x1a\x45\xdf\xa3")
    return len(first) >= 8 and first[4:8] == b"ftyp"


async def save_evidence(chunks: AsyncIterable[bytes], root: Path,
                        *, max_video_bytes: int = MAX_VIDEO_BYTES) -> dict:
    """Store one length-prefixed JSON manifest followed by media bytes."""
    stream = aiter(chunks)
    metadata, initial = await _header(stream)
    ext, limit = _validate(metadata)
    if ext in ("webm", "mp4"):
        limit = min(limit, max_video_bytes)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    identifier = secrets.token_hex(12)
    media_path = root / f"{identifier}.{ext}"
    media_part = root / f"{identifier}.{ext}.part"
    manifest_path = root / f"{identifier}.json"
    manifest_part = root / f"{identifier}.json.part"
    async with _WRITE_LOCK:
        used = sum(path.stat().st_size for path in root.iterdir()
                   if path.is_file() and path.suffix in (".jpg", ".webm", ".mp4"))
        if used >= MAX_TOTAL_BYTES or shutil.disk_usage(root).free < MIN_FREE_BYTES + limit:
            raise EvidenceError("CAMERA_STORAGE_FULL", 507, "camera evidence storage is full")
        size = 0
        digest = hashlib.sha256()
        first = bytearray()
        last = b""
        try:
            with media_part.open("xb") as output:
                for chunk in (initial,):
                    if chunk:
                        size += len(chunk)
                        if size > limit or used + size > MAX_TOTAL_BYTES:
                            raise EvidenceError("CAMERA_EVIDENCE_TOO_LARGE", 413, "camera evidence exceeds its limit")
                        output.write(chunk)
                        digest.update(chunk)
                        first.extend(chunk[:12])
                        last = (last + chunk)[-12:]
                async for chunk in stream:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > limit or used + size > MAX_TOTAL_BYTES:
                        raise EvidenceError("CAMERA_EVIDENCE_TOO_LARGE", 413, "camera evidence exceeds its limit")
                    output.write(chunk)
                    digest.update(chunk)
                    if len(first) < 12:
                        first.extend(chunk[:12 - len(first)])
                    last = (last + chunk)[-12:]
                output.flush()
                os.fsync(output.fileno())
            if not size or not _media_valid(ext, bytes(first), last):
                raise _invalid("camera media signature is invalid")
            created = datetime.now(timezone.utc).isoformat(timespec="seconds")
            result = {"id": identifier, "kind": metadata["kind"], "file_name": media_path.name,
                      "mime_type": metadata["mime_type"], "bytes": size,
                      "sha256": digest.hexdigest(), "created_at": created}
            with manifest_part.open("x", encoding="utf-8") as output:
                json.dump({**result, **metadata}, output, ensure_ascii=False, separators=(",", ":"))
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(media_part, media_path)
            os.replace(manifest_part, manifest_path)
            return result
        except BaseException:
            for path in (media_part, manifest_part, media_path, manifest_path):
                path.unlink(missing_ok=True)
            raise


def list_evidence(root: Path) -> list[dict]:
    if not root.is_dir():
        return []
    records = []
    for path in root.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if (path.stem == record.get("id") and (root / record["file_name"]).is_file()):
                records.append({key: record[key] for key in
                                ("id", "kind", "file_name", "mime_type", "bytes", "sha256", "created_at")})
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return sorted(records, key=lambda record: (record["created_at"], record["id"]),
                  reverse=True)[:50]
