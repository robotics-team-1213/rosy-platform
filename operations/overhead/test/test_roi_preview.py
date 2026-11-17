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
