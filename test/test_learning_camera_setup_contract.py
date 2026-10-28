"""D-792 camera setup contract: sealed reference (features or markers), agreement, Episode setup record."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts/learning/src"))
from rosy.contracts.learning.artifacts import seal
from rosy.contracts.learning.camera_setup import judge, pose_error, validate_reference, validate_setup

MOUNT = {"height_cm": 45.0, "distance_cm": 40.0, "tilt_deg": 39.3, "pan_deg": 90.0, "roll_deg": 0.0}
MARKERS = [{"id": i, "size_cm": 6.0, "center_cm": [x, 0.0],
            "corners_px": [[10.0 + i, 10.0], [20.0 + i, 10.0], [20.0 + i, 20.0], [10.0 + i, 20.0]]}
           for i, x in enumerate([-20.0, 0.0, 20.0])]


def reference(method="markers", **measured):
    markers = method == "markers"
    return seal({
        "schema": "rosy.camera-setup-reference/1", "camera_role": "front", "camera_identity": "omx-front-usb-1",
        "width": 640, "height": 480, "fps": 30,
        "intrinsics": {"camera_info_sha256": "c" * 64, "revision": "r1", "k": [600.0, 600.0, 320.0, 240.0],
                       "dist": [0.0, 0.0, 0.0, 0.0, 0.0]},
        "method": method, "marker_dictionary": "DICT_4X4_50" if markers else None,
        "markers": MARKERS if markers else [],
        "mount": {"measured": {**dict.fromkeys(MOUNT), **measured}, "estimated": MOUNT if markers else None},
        "check_pose": None,
        "reference_still": "d" * 64,
        "guides": [{"kind": "edge", "label": "table front", "points": [[0, 400], [640, 400]], "closed": False}],
        "created_at": "2026-10-18T09:00:00+09:00", "created_by": "operator",
    })


def check(verdict="ok", method="features", **values):
    numbers = {"px_mean": 1.0, "px_max": 2.0, "d_pan_deg": 0.0, "d_tilt_deg": 0.0, "d_roll_deg": 0.0,
               "d_scale_pct": 0.0 if method == "features" else None,
               "d_height_cm": None if method == "features" else 0.0,
               "d_distance_cm": None if method == "features" else 0.0}
    if verdict == "unmeasurable":
        numbers = dict.fromkeys(numbers)
    return {"method": method, "matches": 400, "pose_error_rad": None, **numbers, **values, "verdict": verdict}


def test_sealed_references_round_trip_and_tampering_fails():
    for doc in (reference(), reference("features", height_cm=45.0)):
        assert validate_reference(doc) == doc
    with pytest.raises(ValueError, match="canonical revision"):
        validate_reference({**reference(), "fps": 15})


def test_features_reference_carries_no_markers_or_estimate():
    doc = reference("features")
    with pytest.raises(ValueError, match="no markers"):
        validate_reference(seal({**doc, "markers": MARKERS}))
    with pytest.raises(ValueError, match="no markers"):
        validate_reference(seal({**doc, "mount": {**doc["mount"], "estimated": MOUNT}}))


def test_measured_mount_must_agree_with_the_marker_estimate():
    with pytest.raises(ValueError, match="height_cm disagrees"):
        validate_reference(reference(height_cm=50.0))
    with pytest.raises(ValueError, match="tilt_deg disagrees"):
        validate_reference(reference(tilt_deg=45.0))


def test_judge_thresholds_scale_with_resolution_and_skip_unmeasured():
    ok = {k: v for k, v in check().items() if k not in ("method", "matches", "pose_error_rad", "verdict")} | {
        "px_mean": 2.5, "px_max": 5.0}
    assert judge(ok, 640, 480) == "ok"
    assert judge(ok, 320, 240) == "adjust"  # the same pixels are twice as large at half resolution
    assert judge(ok, 1280, 960) == "ok"
    assert judge({**ok, "d_tilt_deg": 1.2}, 640, 480) == "adjust"
    assert judge({**ok, "d_scale_pct": -1.5}, 640, 480) == "adjust"
    assert judge({**ok, "d_height_cm": None, "d_distance_cm": None}, 640, 480) == "ok"
    assert judge({**ok, "d_height_cm": -0.6}, 640, 480) == "adjust"
    assert judge(None, 640, 480) == "unmeasurable"


def test_episode_setup_record():
    record = {"reference_revision": "a" * 64, "before": check(), "after": check("adjust", d_pan_deg=-1.4),
              "mode": "shadow"}
    assert validate_setup(record) == record
    assert validate_setup({**record, "before": check("ok", "markers"), "after": None})
    assert validate_setup({**record, "before": check("unmeasurable"), "after": None})
    with pytest.raises(ValueError, match="no measurements"):
        validate_setup({**record, "before": check("unmeasurable", px_mean=1.0)})
    with pytest.raises(ValueError, match="does not measure d_height_cm"):
        validate_setup({**record, "before": check(d_height_cm=0.2)})
    with pytest.raises(ValueError, match="does not measure d_scale_pct"):
        validate_setup({**record, "before": check("ok", "markers", d_scale_pct=0.0)})
    with pytest.raises(ValueError, match="enforce mode"):
        validate_setup({**record, "before": check("adjust"), "mode": "enforce"})


def test_wrist_reference_has_a_bounded_check_pose():
    pose = {"joint_names": ["joint1", "joint2"], "positions_rad": [0.1, -0.4], "tolerance_rad": 0.01}
    doc = seal({**reference("features"), "camera_role": "front", "check_pose": pose})
    assert validate_reference(doc) == doc
    assert pose_error(doc, {"joint1": 0.1, "joint2": -0.43, "joint3": 9.0}) == pytest.approx(0.03)
    assert pose_error(reference("features"), None) is None
    with pytest.raises(ValueError, match="joint readback"):
        pose_error(doc, {"joint1": 0.1})
    for bad, message in [({**pose, "tolerance_rad": 0.2}, "finite number"),
                         ({**pose, "positions_rad": [0.1]}, "one position per joint"),
                         ({**pose, "joint_names": ["joint1", "joint1"]}, "unique joint names")]:
        with pytest.raises(ValueError, match=message):
            validate_reference(seal({**doc, "check_pose": bad}))
    record = {"reference_revision": "a" * 64, "before": check(pose_error_rad=0.004), "after": None, "mode": "shadow"}
    assert validate_setup(record) == record
