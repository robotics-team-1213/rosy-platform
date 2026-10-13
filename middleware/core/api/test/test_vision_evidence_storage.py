"""Bounded, atomic storage for operator camera evidence on the robot SD."""

import asyncio
import json

import pytest

from core_api_web.api.v1.vision_evidence import EvidenceError, list_evidence, save_evidence


def packet(metadata, payload):
    header = json.dumps(metadata, separators=(",", ":")).encode()
    return len(header).to_bytes(4, "little") + header + payload


def video_metadata():
    return {"schema_version": 1, "kind": "video", "mime_type": "video/webm",
            "started_at": "2026-09-26T00:00:00Z", "stopped_at": "2026-09-26T00:00:02Z",
            "frame_count": 2, "operations": [{"action": "수동 운전", "result": "accepted",
                                               "elapsed_ms": 500}]}


async def chunks(data, size=3):
    for start in range(0, len(data), size):
        yield data[start:start + size]


def test_video_and_manifest_are_saved_atomically_from_fragmented_stream(tmp_path):
    body = packet(video_metadata(), b"\x1aE\xdf\xa3video")
    result = asyncio.run(save_evidence(chunks(body), tmp_path))
    assert result["kind"] == "video"
    assert result["bytes"] == 9
    video = tmp_path / result["file_name"]
    assert video.read_bytes() == b"\x1aE\xdf\xa3video"
    saved = json.loads((tmp_path / f"{result['id']}.json").read_text(encoding="utf-8"))
    assert saved["operations"] == video_metadata()["operations"]
    assert not list(tmp_path.glob("*.part"))


def test_oversize_or_unrecognized_media_never_leaves_partial_files(tmp_path):
    metadata = video_metadata()
    with pytest.raises(EvidenceError):
        asyncio.run(save_evidence(chunks(packet(metadata, b"not-webm")), tmp_path))
    assert not list(tmp_path.iterdir())
    with pytest.raises(EvidenceError):
        asyncio.run(save_evidence(chunks(packet(metadata, b"\x1aE\xdf\xa3" + b"x" * 20)),
                                  tmp_path, max_video_bytes=10))
    assert not list(tmp_path.iterdir())


def test_metadata_cannot_embed_credentials_or_arbitrary_operation_fields(tmp_path):
    metadata = video_metadata()
    metadata["token"] = "must-never-save"
    with pytest.raises(EvidenceError):
        asyncio.run(save_evidence(chunks(packet(metadata, b"\x1aE\xdf\xa3x")), tmp_path))
    assert not list(tmp_path.iterdir())
    metadata = video_metadata()
    metadata["operations"][0]["action"] = ["not a string"]
    with pytest.raises(EvidenceError):
        asyncio.run(save_evidence(chunks(packet(metadata, b"\x1aE\xdf\xa3x")), tmp_path))
    assert not list(tmp_path.iterdir())


def test_saved_files_are_listed_by_creation_time_not_random_identifier(tmp_path):
    for identifier, created_at in [("a" * 24, "2026-09-26T00:00:01+00:00"),
                                   ("f" * 24, "2026-09-26T00:00:00+00:00")]:
        name = f"{identifier}.jpg"
        (tmp_path / name).write_bytes(b"\xff\xd8x\xff\xd9")
        (tmp_path / f"{identifier}.json").write_text(json.dumps({
            "id": identifier, "kind": "screenshot", "file_name": name,
            "mime_type": "image/jpeg", "bytes": 5, "sha256": "x" * 64,
            "created_at": created_at,
        }), encoding="utf-8")
    assert [item["id"] for item in list_evidence(tmp_path)] == ["a" * 24, "f" * 24]
