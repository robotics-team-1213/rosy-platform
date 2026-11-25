"""Offline ruler crop evidence comes from the source pixels and explicit field readings."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools/calibration/ceiling_ruler_crop.py"


@pytest.fixture
def ceiling_jpeg(tmp_path):
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    generate = getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker
    frame = np.full((360, 720, 3), 230, dtype=np.uint8)
    frame[28:108, 30:110] = generate(dictionary, 45, 80)[:, :, np.newaxis]
    frame[135:215, 405:485] = generate(dictionary, 46, 80)[:, :, np.newaxis]
    frame[35:230, 510:550] = [10, 180, 240]  # Occluded/blank ruler region.
    source = tmp_path / "ceiling.jpg"
    assert cv2.imwrite(str(source), frame)
    return source


def run_tool(source, crop, *args):
    return subprocess.run(
        [sys.executable, str(TOOL), str(source), "--out", str(crop), *args],
        text=True, capture_output=True, check=False,
    )


def test_crop_preserves_pixels_and_keeps_field_reading_separate(ceiling_jpeg, tmp_path):
    crop = tmp_path / "ruler.png"
    result = run_tool(
        ceiling_jpeg, crop, "--marker", "46", "--roi", "15", "15", "580", "250", "--field-marker", "45",
        "--datum", "north wall face", "--station-end-wall-mm", "228", "--marker-wall-mm", "160",
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    image = evidence["image_evidence"]
    assert image["source_sha256"] == hashlib.sha256(ceiling_jpeg.read_bytes()).hexdigest()
    assert image["crop_sha256"] == hashlib.sha256(crop.read_bytes()).hexdigest()
    assert image["crop_xyxy"] == [15, 15, 580, 250]
    assert image["marker_id"] == 46 and len(image["marker_corners_xy"]) == 4
    decoded = cv2.imread(str(ceiling_jpeg))
    np.testing.assert_array_equal(cv2.imread(str(crop)), decoded[15:250, 15:580])
    assert evidence["field_measurement"] == {
        "source": "field_reported",
        "datum": "north wall face",
        "marker_id": 45,
        "station_end_wall_mm": 228,
        "marker_wall_mm": 160,
        "inset_mm": 68,
    }


def test_no_field_report_produces_no_measurement(ceiling_jpeg, tmp_path):
    crop = tmp_path / "default.png"
    result = run_tool(ceiling_jpeg, crop, "--marker", "45")
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["image_evidence"]["crop_xyxy"][:2] == [0, 0]
    assert evidence["field_measurement"] is None


@pytest.mark.parametrize("args,error", [
    (("--marker", "47"), "ArUco marker 47"),
    (("--marker", "45", "--roi", "400", "20", "700", "340"), "include"),
    (("--marker", "45", "--station-end-wall-mm", "228", "--marker-wall-mm", "160"), "datum"),
])
def test_refusal_does_not_write_crop(ceiling_jpeg, tmp_path, args, error):
    crop = tmp_path / "refused.png"
    result = run_tool(ceiling_jpeg, crop, *args)
    assert result.returncode != 0 and error in result.stderr
    assert not crop.exists()
