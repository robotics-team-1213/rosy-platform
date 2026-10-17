"""D-792 camera setup contract: sealed reference, measured/estimated agreement, Episode setup record."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts/learning/src"))
from rosy.contracts.learning.artifacts import seal
from rosy.contracts.learning.camera_setup import judge, validate_reference, validate_setup

MOUNT = {"height_cm": 45.0, "distance_cm": 40.0, "tilt_deg": 39.3, "pan_deg": 90.0, "roll_deg": 0.0}


def reference(**measured):
    return seal({
        "schema": "rosy.camera-setup-reference/1", "camera_role": "front", "camera_identity": "omx-front-usb-1",
        "width": 640, "height": 480, "fps": 30,
        "intrinsics": {"camera_info_sha256": "c" * 64, "revision": "r1", "k": [600.0, 600.0, 320.0, 240.0],
                       "dist": [0.0, 0.0, 0.0, 0.0, 0.0]},
        "marker_dictionary": "DICT_4X4_50",
        "markers": [{"id": i, "size_cm": 6.0, "center_cm": [x, 0.0],
                     "corners_px": [[10.0 + i, 10.0], [20.0 + i, 10.0], [20.0 + i, 20.0], [10.0 + i, 20.0]]}
                    for i, x in enumerate([-20.0, 0.0, 20.0])],
        "mount": {"measured": {**dict.fromkeys(MOUNT), **measured}, "estimated": MOUNT},
        "reference_still": "d" * 64,
        "guides": [{"kind": "edge", "label": "table front", "points": [[0, 400], [640, 400]], "closed": False}],
        "created_at": "2026-10-18T09:00:00+09:00", "created_by": "operator",
    })


def check(verdict="ok", **values):
    numbers = {"marker_px_mean": 1.0, "marker_px_max": 2.0, **{"d_" + k: 0.0 for k in MOUNT}}
    if verdict == "unmeasurable":
        numbers = dict.fromkeys(numbers)
    return {"markers_seen": 4, **numbers, **values, "verdict": verdict}


def test_sealed_reference_round_trips_and_tampering_fails():
    doc = reference(height_cm=44.5)
    assert validate_reference(doc) == doc
    with pytest.raises(ValueError, match="canonical revision"):
        validate_reference({**doc, "fps": 15})


def test_measured_mount_must_agree_with_the_marker_estimate():
    with pytest.raises(ValueError, match="height_cm disagrees"):
        validate_reference(reference(height_cm=50.0))
    with pytest.raises(ValueError, match="tilt_deg disagrees"):
        validate_reference(reference(tilt_deg=45.0))


def test_judge_thresholds_scale_with_resolution():
    ok = {"marker_px_mean": 2.5, "marker_px_max": 5.0, **{"d_" + k: 0.0 for k in MOUNT}}
    assert judge(ok, 640, 480) == "ok"
    assert judge(ok, 320, 240) == "adjust"  # the same pixels are twice as large at half resolution
    assert judge({**ok, "d_height_cm": -0.6}, 640, 480) == "adjust"
    assert judge({**ok, "d_tilt_deg": 1.2}, 640, 480) == "adjust"
    assert judge(None, 640, 480) == "unmeasurable"


def test_episode_setup_record():
    record = {"reference_revision": "a" * 64, "before": check(), "after": check("adjust", d_height_cm=-1.0),
              "mode": "shadow"}
    assert validate_setup(record) == record
    assert validate_setup({**record, "before": check("unmeasurable"), "after": None})
    with pytest.raises(ValueError, match="no measurements"):
        validate_setup({**record, "before": check("unmeasurable", marker_px_mean=1.0)})
    with pytest.raises(ValueError, match="enforce mode"):
        validate_setup({**record, "before": check("adjust"), "mode": "enforce"})
