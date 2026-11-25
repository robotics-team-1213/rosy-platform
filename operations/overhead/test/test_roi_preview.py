import asyncio
from types import SimpleNamespace

from core_common.protocol.vision_preview import VisionLeaseSigner
from rosy_vision import ingest_preview
from rosy_vision.ingest import IngestServer

ROI_PATH = "/api/vision/sources/ceiling-north/roi/rosy_46"


def _server():
    server = IngestServer({"ceiling-north": "phone-token"},
                          preview_signer=VisionLeaseSigner("p" * 32))
    server.anchor_tracker = SimpleNamespace(roi_jpeg=lambda target_id: (b"roi-jpeg", 12.5))
    return server


def _get(server, path, authorization):
    # The ROI route lives in ingest_preview; drive it with a real IngestServer as self.
    return asyncio.run(ingest_preview._preview_response(server, path, authorization))


def test_roi_requires_a_lease():
    server = _server()
    assert _get(server, ROI_PATH, None).status_code == 401
    assert _get(server, ROI_PATH, "Bearer not-a-lease").status_code == 401


def test_roi_rejects_a_lease_for_another_source():
    server = _server()
    token = server.preview_signer.issue(principal_id="viewer", source_id="other")
    assert _get(server, ROI_PATH, f"Bearer {token}").status_code == 401


def test_roi_serves_the_crop_once_per_frame_interval():
    server = _server()
    token = server.preview_signer.issue(principal_id="viewer", source_id="ceiling-north")

    allowed = _get(server, ROI_PATH, f"Bearer {token}")
    limited = _get(server, ROI_PATH, f"Bearer {token}")

    assert allowed.status_code == 200
    assert allowed.body == b"roi-jpeg"
    assert allowed.headers["Content-Type"] == "image/jpeg"
    assert allowed.headers["X-Target-Id"] == "rosy_46"
    assert limited.status_code == 429
    # The ROI budget is its own key: the raw frame budget of the same viewer is untouched.
    assert ("viewer", "ceiling-north", "roi") in server._preview_last_sent


def test_roi_without_a_preview_signer_is_not_found():
    server = _server()
    server.preview_signer = None
    assert _get(server, ROI_PATH, "Bearer anything").status_code == 404


def test_anchor_head_tracker_encodes_roi_jpeg_on_demand_and_caches(monkeypatch):
    import cv2
    import numpy as np
    from rosy_vision.track.anchor_head_tracker import AnchorHeadTracker
    from rosy_vision.track.model import Calibration, DetectorResult

    encode_calls = []
    orig_imencode = cv2.imencode

    def spy_imencode(*args, **kwargs):
        encode_calls.append(args[0])
        return orig_imencode(*args, **kwargs)

    monkeypatch.setattr(cv2, "imencode", spy_imencode)
    tracker = AnchorHeadTracker()
    tracker.update_from_config({"anchors": [
        {"target_id": "rosy_46", "kind": "pinky", "label": "rosy_46", "base_x": 0.4, "base_y": 0.35, "base_yaw": -1.5708, "updated_at": 1e12},
    ]})
    calib = Calibration("ceiling_north", "map_v2_fleet", "cal-v3", tuple(np.diag([0.0025, 0.0025, 1.0]).ravel()),
                        (640, 360), (-1.0, -1.0, 2.0, 2.0), 60.0)
    image = np.full((360, 640, 3), 120, np.uint8)
    tracker.step(image, 100.0, calib, DetectorResult((), "OK"),
                 source_id="ceiling_north", map_id="map_v2_fleet", processor_revision="p", seq=1)
    assert encode_calls == []

    arm_bytes, arm_at = tracker.roi_jpeg("arm_a")
    assert arm_bytes is not None and arm_bytes.startswith(b"\xff\xd8") and arm_at == 100.0
    assert len(encode_calls) == 1
    assert tracker.roi_jpeg("arm_a") == (arm_bytes, 100.0)
    assert len(encode_calls) == 1

    pinky_bytes, pinky_at = tracker.roi_jpeg("rosy_46")
    assert pinky_bytes is not None and pinky_bytes.startswith(b"\xff\xd8") and pinky_at == 100.0
    assert len(encode_calls) == 2
