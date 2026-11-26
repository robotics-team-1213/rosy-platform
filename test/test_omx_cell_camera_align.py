"""Camera alignment against a calibration reference (2026-11-27)."""
import os
import sys
import time
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_camera_align as ca  # noqa: E402


def scene(seed=3):
    rng = np.random.default_rng(seed)
    img = np.full((480, 640, 3), 90, np.uint8)
    for _ in range(160):
        x, y = int(rng.integers(0, 620)), int(rng.integers(0, 460))
        cv2.rectangle(img, (x, y), (x + int(rng.integers(6, 40)), y + int(rng.integers(6, 40))), tuple(int(c) for c in rng.integers(0, 255, 3)), -1)
    return img


def jpg(img):
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


def test_a_shifted_and_turned_camera_is_measured_and_a_still_one_is_aligned():
    ref = scene()
    moved = cv2.warpAffine(ref, cv2.getRotationMatrix2D((320, 240), -2.0, 0.95), (640, 480), borderValue=(90, 90, 90))
    moved = cv2.warpAffine(moved, np.float32([[1, 0, 30], [0, 1, 0]]), (640, 480), borderValue=(90, 90, 90))
    r = ca.align(jpg(ref), jpg(moved), 6.0)
    assert r["ok"] and not r["aligned"] and r["max_px"] > 25 and len(r["arrows"]) == 20
    assert r["shift_px"][0] == pytest.approx(30, abs=4) and abs(r["rotation_deg"]) == pytest.approx(2.0, abs=0.5)
    assert r["scale"] == pytest.approx(0.95, abs=0.02)
    same = ca.align(jpg(ref), jpg(ref), 6.0)
    assert same["ok"] and same["aligned"] and same["max_px"] <= 1.0
    assert ca.align(jpg(ref), jpg(cv2.resize(ref, (320, 240))), 6.0) == {"ok": False, "why": "size 640x480 vs 320x240"}


def test_references_list_older_images_beside_the_map_and_only_those_can_be_named(tmp_path):
    cell = tmp_path / "cell-arm-b"
    (cell / "generations" / "g1").mkdir(parents=True)
    (cell / "calibration-history" / "20261126T000000.000000-map").mkdir(parents=True)
    (cell / "frames").mkdir()
    current = cell / "reference-top.jpg"
    for p in (current, cell / "generations" / "g1" / "reference-top.jpg",
              cell / "calibration-history" / "20261126T000000.000000-map" / "ref.jpg", cell / "frames" / "x-top.jpg"):
        p.write_bytes(b"jpg")
    (cell / "calibration-history" / "20261126T000000.000000-map" / "cal.json").write_text("{}")
    os.utime(cell / "generations" / "g1" / "reference-top.jpg", (time.time() - 100, time.time() - 100))
    refs = ca.references(current)
    assert [r["id"] for r in refs] == ["current", "calibration-history/20261126T000000.000000-map/ref.jpg",
                                      "generations/g1/reference-top.jpg"]
    assert ca.reference_path(current, "generations/g1/reference-top.jpg") == (cell / "generations/g1/reference-top.jpg").resolve()
    for bad in ("../reference-top.jpg", "frames/x-top.jpg", "/etc/passwd", ""):
        assert ca.reference_path(current, bad) is None
    assert ca.references(None) == [] and ca.references(cell / "missing.jpg") == []
    outside = tmp_path / "secret.jpg"
    outside.write_bytes(b"x")
    try:
        (cell / "reference-top-link.jpg").symlink_to(outside)
    except OSError:
        return  # no symlink permission on this host
    ca._CACHE.clear()
    assert all("link" not in r["id"] for r in ca.references(current))
