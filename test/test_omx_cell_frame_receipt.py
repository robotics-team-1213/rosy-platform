"""A frame receipt must identify the exact fresh JPEG, not a cached camera picture."""
import hashlib
import importlib.util
from pathlib import Path
import sys
import urllib.error

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
spec = importlib.util.spec_from_file_location("cell_pipeline_io", OMX / "cell_pipeline_io.py")
io = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = io
spec.loader.exec_module(io)


class Reply:
    status = 200

    def __init__(self, raw, headers):
        self.raw, self.headers = raw, headers

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self):
        return self.raw


@pytest.fixture
def camera(monkeypatch, tmp_path):
    cell = io.FifoCell(tmp_path, {"top": "http://camera/frame/top.jpg"})
    monkeypatch.setattr(io.time, "time", lambda: 100.0)
    image = np.full((8, 8, 3), (10, 20, 30), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return cell, encoded.tobytes()


def test_fresh_receipt_hashes_actual_jpeg_and_decodes(camera, monkeypatch):
    cell, raw = camera
    monkeypatch.setattr(io.urllib.request, "urlopen", lambda request, timeout: Reply(
        raw, {"X-Frame-Seq": "42", "X-Source-Stamp": "99.75", "ETag": '"42"'}))
    receipt = cell.frame_receipt("top")
    assert receipt["jpeg_sha256"] == hashlib.sha256(raw).hexdigest()
    assert receipt["source_seq"] == 42
    assert receipt["source_stamp"] == 99.75
    assert receipt["camera"] == "top"
    assert receipt["captured_at"] == 100.0
    assert receipt["image"].shape == (8, 8, 3)


def test_not_modified_never_reuses_old_frame(camera, monkeypatch):
    cell, raw = camera
    previous = {"camera": "top", "source_seq": 42, "source_stamp": 99.7,
                "etag": '"42"'}

    def no_new_frame(request, timeout):
        assert request.get_header("If-none-match") == '"42"'
        raise urllib.error.HTTPError(request.full_url, 304, "Not Modified", {}, None)

    monkeypatch.setattr(io.urllib.request, "urlopen", no_new_frame)
    cell._frame_cache["top"] = ('"42"', np.zeros((8, 8, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="HTTP 304"):
        cell.frame_receipt("top", previous=previous)


@pytest.mark.parametrize("headers", [
    {"X-Source-Stamp": "99.7"},
    {"X-Frame-Seq": "42"},
    {"X-Frame-Seq": "42", "X-Source-Stamp": "97.0"},
])
def test_missing_or_old_source_metadata_is_rejected(camera, monkeypatch, headers):
    cell, raw = camera
    monkeypatch.setattr(io.urllib.request, "urlopen", lambda request, timeout: Reply(raw, headers))
    with pytest.raises(ValueError, match="source"):
        cell.frame_receipt("top")


def test_before_after_requires_both_sequence_and_stamp_to_advance(camera, monkeypatch):
    cell, raw = camera
    replies = iter([
        Reply(raw, {"X-Frame-Seq": "42", "X-Source-Stamp": "99.7", "ETag": '"42"'}),
        Reply(raw, {"X-Frame-Seq": "42", "X-Source-Stamp": "99.8", "ETag": '"42"'}),
        Reply(raw, {"X-Frame-Seq": "43", "X-Source-Stamp": "99.8", "ETag": '"43"'}),
    ])
    monkeypatch.setattr(io.urllib.request, "urlopen", lambda request, timeout: next(replies))
    before = cell.frame_receipt("top")
    with pytest.raises(ValueError, match="not advanced"):
        cell.frame_receipt("top", previous=before)
    after = cell.frame_receipt("top", previous=before)
    assert after["source_seq"] == 43
    assert after["source_stamp"] > before["source_stamp"]
