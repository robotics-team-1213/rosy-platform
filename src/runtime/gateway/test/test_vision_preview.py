"""Authenticated, bounded latest-frame camera preview contracts."""

from __future__ import annotations

import pytest

from core_features.vision import (
    VisionFrameAdvanced,
    VisionFrameStore,
    VisionPullRateLimited,
    parse_preview_format,
)


VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


def jpeg(payload: bytes = b"frame") -> bytes:
    return b"\xff\xd8" + payload + b"\xff\xd9"


def test_latest_frame_store_rejects_invalid_and_unbounded_payloads():
    with pytest.raises(ValueError, match="maximum"):
        VisionFrameStore(max_bytes=512_001, stale_after_s=1.0)
    with pytest.raises(ValueError, match="0.4"):
        VisionFrameStore(
            max_bytes=1024, stale_after_s=1.0,
            min_pull_interval_s=0.399,
        )
    store = VisionFrameStore(max_bytes=32, stale_after_s=1.0)

    with pytest.raises(ValueError, match="JPEG"):
        store.publish(
            b"not-an-image", captured_at=10.0, received_at=20.0,
            frame_id="front_camera_link", source="GAZEBO")
    with pytest.raises(ValueError, match="maximum"):
        store.publish(
            jpeg(b"x" * 40), captured_at=10.0, received_at=20.0,
            frame_id="front_camera_link", source="GAZEBO")


def test_latest_frame_store_is_monotonic_and_fail_closed_when_stale():
    store = VisionFrameStore(max_bytes=1024, stale_after_s=1.0)
    store.publish(
        jpeg(b"first"), captured_at=10.0, received_at=20.0,
        frame_id="front_camera_link", source="GAZEBO",
        width=640, height=360, overlay="semantic-road-v1")

    with pytest.raises(ValueError, match="older"):
        store.publish(
            jpeg(b"late-old"), captured_at=9.9, received_at=20.1,
            frame_id="front_camera_link", source="GAZEBO")

    fresh = store.status(now=20.5)
    assert fresh == {
        "available": True,
        "stale": False,
        "source": "GAZEBO",
        "frame_id": "front_camera_link",
        "captured_at": 10.0,
        "age_ms": 500,
        "width": 640,
        "height": 360,
        "overlay": "semantic-road-v1",
        "sequence": 1,
        "quality": None,
        "quality_age_ms": None,
        "raw_available": False,
        "raw_sequence": None,
    }
    assert store.frame(now=20.5).data == jpeg(b"first")

    stale = store.status(now=21.1)
    assert stale["available"] is False
    assert stale["stale"] is True
    assert store.frame(now=21.1) is None


def test_stale_lease_allows_a_new_capture_clock_epoch():
    store = VisionFrameStore(max_bytes=1024, stale_after_s=1.0)
    store.publish(
        jpeg(b"before-reset"), captured_at=100.0, received_at=20.0,
        frame_id="front_camera_link", source="GAZEBO")

    frame = store.publish(
        jpeg(b"after-reset"), captured_at=0.1, received_at=21.1,
        frame_id="front_camera_link", source="GAZEBO")

    assert frame.captured_at == 0.1
    assert frame.sequence == 2


def test_frame_pull_is_sequence_bound_and_rate_limited_per_viewer():
    store = VisionFrameStore(
        max_bytes=1024, stale_after_s=1.0, min_pull_interval_s=0.4)
    stored = store.publish(
        jpeg(b"current"), captured_at=10.0, received_at=20.0,
        frame_id="front_camera_link", source="GAZEBO")

    with pytest.raises(VisionFrameAdvanced):
        store.frame_for_viewer(
            "viewer-a", expected_sequence=stored.sequence - 1, now=20.0)
    assert store.frame_for_viewer(
        "viewer-a", expected_sequence=stored.sequence, now=20.0) == stored
    with pytest.raises(VisionPullRateLimited):
        store.frame_for_viewer(
            "viewer-a", expected_sequence=stored.sequence, now=20.1)
    # A stalled camera must not let a repeated variant spend a second admission.
    with pytest.raises(VisionPullRateLimited):
        store.frame_for_viewer("viewer-a", expected_sequence=stored.sequence, now=20.4)
    # Limits are isolated by authenticated token id.
    assert store.frame_for_viewer(
        "viewer-b", expected_sequence=stored.sequence, now=20.1) == stored


@pytest.mark.parametrize('quality_reason', ['low_light', 'overexposed'])
def test_camera_preview_api_requires_auth_and_returns_jpeg(
        core_client, monkeypatch, quality_reason):
    client, services = core_client()

    assert client.get("/api/v1/vision/front/status").status_code == 401
    unbound = client.get("/api/v1/vision/front/frame", headers=VIEWER)
    assert unbound.status_code == 400

    missing = client.get(
        "/api/v1/vision/front/frame?sequence=1", headers=VIEWER)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CAMERA_FRAME_UNAVAILABLE"

    services.vision.publish(
        jpeg(b"dashboard"), captured_at=42.25,
        frame_id="front_camera_link", source="GAZEBO",
        width=640, height=360, overlay="semantic-road-v1", quality=dict(valid=False, reason=quality_reason))

    status = client.get("/api/v1/vision/front/status", headers=VIEWER)
    frame = client.get(
        f"/api/v1/vision/front/frame?sequence={status.json()['sequence']}",
        headers=VIEWER,
    )

    assert status.status_code == 200
    assert status.json()["available"] is True
    assert status.json()["source"] == "GAZEBO"
    assert status.json()["width"] == 640
    assert status.json()['quality'] == dict(valid=False, reason=quality_reason)
    assert status.headers["cache-control"] == "no-store"
    assert frame.status_code == 200
    assert frame.headers["content-type"] == "image/jpeg"
    assert frame.headers["content-encoding"] == "identity"
    assert frame.headers["cache-control"] == "no-store"
    assert frame.headers["x-rosy-camera-source"] == "GAZEBO"
    assert frame.content == jpeg(b"dashboard")


def test_raw_and_annotated_api_are_same_capture_and_admitted_once_each(core_client, monkeypatch):
    client, services = core_client()
    from core.bridge.observation import camera_preview
    from types import SimpleNamespace
    stamp = SimpleNamespace(sec=42, nanosec=250000000)
    header = SimpleNamespace(stamp=stamp, frame_id='front_camera_link')
    warnings = []
    camera_preview(services, SimpleNamespace(header=header, data=jpeg(b'raw'),
        format='jpeg;source=front;width=320;height=240;overlay=none'), warn=warnings.append, raw=True, source_now=42.25)
    camera_preview(services, SimpleNamespace(header=header, data=jpeg(b'annotated'),
        format='jpeg;source=front;width=320;height=240;overlay=follow-road-v2'), warn=warnings.append, source_now=42.25)
    assert not warnings
    status = client.get('/api/v1/vision/front/status', headers=VIEWER).json()
    assert status['raw_available'] and status['raw_sequence'] == status['sequence']
    sequence = status['sequence']
    original = client.get(f'/api/v1/vision/front/frame?sequence={sequence}&overlay=false', headers=VIEWER)
    annotated = client.get(f'/api/v1/vision/front/frame?sequence={sequence}', headers=VIEWER)
    assert original.content == jpeg(b'raw') and annotated.content == jpeg(b'annotated')
    assert original.headers['x-rosy-camera-variant'] == 'raw'
    assert annotated.headers['x-rosy-camera-variant'] == 'annotated'
    for key in ('x-rosy-camera-captured-at', 'x-rosy-camera-frame-id', 'x-rosy-camera-sequence'):
        assert original.headers[key] == annotated.headers[key]
    assert client.get(f'/api/v1/vision/front/frame?sequence={sequence}&overlay=false',
                      headers=VIEWER).status_code == 429

    advanced = client.get(
        "/api/v1/vision/front/frame?sequence=999", headers=VIEWER)
    assert advanced.status_code == 409
    assert advanced.json()["error"]["code"] == "CAMERA_FRAME_ADVANCED"

    # The store's rate-window behavior is covered above with an explicit
    # clock.  Keep this API-boundary assertion independent of host load: a
    # full suite can legitimately spend more than 400 ms between requests.
    def rate_limited(*_args, **_kwargs):
        raise VisionPullRateLimited(0.4)

    monkeypatch.setattr(services.vision, "frame_for_viewer", rate_limited)
    limited = client.get(
        f"/api/v1/vision/front/frame?sequence={sequence}",
        headers=VIEWER,
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "CAMERA_RATE_LIMITED"


def test_preview_format_parser_is_bounded_and_defaults_unknown_metadata():
    parsed = parse_preview_format(
        "jpeg; source=GAZEBO; width=640; height=360; "
        "overlay=semantic-road-v1")

    assert parsed == {
        "source": "GAZEBO",
        "width": 640,
        "height": 360,
        "overlay": "semantic-road-v1",
    }
    assert parse_preview_format("jpeg") == {
        "source": "UNKNOWN",
        "width": 0,
        "height": 0,
        "overlay": "none",
    }
    assert parse_preview_format(
        "png; source=PINKY; width=640; height=360") is None


def test_preview_format_parser_sanitizes_source_for_response_headers():
    parsed = parse_preview_format(
        "jpeg; source=gazebo\r\nx-injected: yes; width=640; height=360")

    assert parsed["source"] == "GAZEBO_X-INJECTED_YES"


def test_model_status_api_is_read_only_viewer_data(core_client):
    """D-423 §3.6: GET only; promote/rollback stay on the operator CLI (rosy_ml)."""
    import json
    import time
    client, services = core_client()
    assert client.get("/api/v1/vision/models").status_code == 401
    empty = client.get("/api/v1/vision/models", headers=VIEWER)
    assert empty.status_code == 200 and empty.json() == {"tasks": []}
    assert empty.headers["cache-control"] == "no-store"
    services.vision.models.accept("perception/learned/object_det/status", json.dumps({
        "schema": "rosy.perception.learned_status/1", "model_revision": "object-det-r1",
        "last_error": None, "frames_inferred": 3, "latency_ms_p50": 200.0}), now=time.monotonic())
    tasks = client.get("/api/v1/vision/models", headers=VIEWER).json()["tasks"]
    assert [(t["task"], t["slot"], t["model_revision"], t["stale"]) for t in tasks] == [
        ("object_det", "active", "object-det-r1", False)]
    for method in ("post", "put", "delete"):
        assert getattr(client, method)("/api/v1/vision/models", headers=VIEWER).status_code == 405


def test_bridge_feeds_both_model_status_topics_latched():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "core" / "bridge" / "ros_bridge.py").read_text(
        encoding="utf-8")
    assert "MODEL_STATUS_TOPICS" in source and source.count("self._svc.vision.models.accept(") == 2
