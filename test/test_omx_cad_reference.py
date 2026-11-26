import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "sim"))
try:
    from omx_cad_reference import project_centers
finally:
    sys.path.pop(0)


def write_image(tmp_path, name, image):
    path = tmp_path / name
    assert cv2.imwrite(str(path), image)
    return path


def pair(tmp_path, shift, blank_patch=False):
    rng = np.random.default_rng(17)
    image = rng.integers(0, 255, (360, 480), np.uint8)
    if blank_patch:
        image[75:290, 120:365] = 126
    matrix = np.float32([[1, 0, shift], [0, 1, 0]])
    moved = cv2.warpAffine(image, matrix, (480, 360))
    return write_image(tmp_path, "a.png", image), write_image(tmp_path, "b.png", moved)


def test_identity_binds_bytes_and_rejects_invalid_center(tmp_path):
    path = write_image(tmp_path, "a.png", np.zeros((50, 60), np.uint8))
    key = hashlib.sha256(path.read_bytes()).hexdigest()
    pts = {"slot": [20.25, 30.]}
    mapped, evidence = project_centers(path, path, pts)
    assert mapped == pts
    assert evidence["source_sha256"] == evidence["reference_sha256"] == key
    assert evidence["method"] == "identical_bytes"
    with pytest.raises(ValueError, match="invalid source"):
        project_centers(path, path, {"slot": [100, 0]})


def test_one_pixel_change_checked_on_held_out_features(tmp_path):
    a, b = pair(tmp_path, 1)
    mapped, evidence = project_centers(a, b, {"slot": [240., 180.]})
    assert mapped["slot"] == pytest.approx([241., 180.], abs=0.1)
    assert evidence["local"]["slot"]["agree"] >= 5
    assert np.isfinite(evidence["local"]["slot"]["max_residual_px"])
    assert evidence["reference_sha256"] != evidence["source_sha256"]


def test_camera_displacement_rejected(tmp_path):
    with pytest.raises(ValueError, match="camera displacement"):
        project_centers(*pair(tmp_path, 10), {"slot": [240, 180]})


def test_unseen_fixture_rejected_even_when_background_matches(tmp_path):
    with pytest.raises(ValueError, match="local held-out"):
        project_centers(*pair(tmp_path, 1, blank_patch=True), {"slot": [240, 180]})
