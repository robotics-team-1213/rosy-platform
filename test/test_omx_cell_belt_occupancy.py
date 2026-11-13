"""cell_belt_occupancy: one belt region reads occupied / empty / unknown, and every reading it cannot prove is unknown."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_belt_occupancy as cbo  # noqa: E402

STANDBY = [0.0, -27.0, 18.0, 46.0, -5.0, 58.1]  # arm_s standby: clear of the belt
EXTENDED = [-8.9, -14.7, 22.8, 42.0, 38.3, 54.1]  # arm_s reaching over the belt
NOW = 1_000_000.0
REGION = (300, 55, 420, 115)


def frame(container_at=None, belt=True):
    """Grey floor, yellow table, a dark belt strip centred (430, 100) at 12 deg, optional red-orange container."""
    top = np.full((480, 640, 3), (150, 150, 145), dtype=np.uint8)
    top[220:470, 220:550] = (95, 210, 220)
    if belt:
        cv2.fillConvexPoly(top, np.int32(cv2.boxPoints(((430.0, 100.0), (340.0, 110.0), 12.0))), (42, 42, 40))
    if container_at is not None:
        cv2.fillConvexPoly(top, np.int32(cv2.boxPoints((container_at, (75.0, 26.0), 12.0))), (35, 45, 235))
    return top


def read(image, roi=REGION, **kw):
    receipt = kw.pop("receipt", {"image": image, "source_seq": 7, "source_stamp": NOW})
    kw.setdefault("camera_moved", False)
    kw.setdefault("joint_state_norm", STANDBY)
    return cbo.read_belt_occupancy(receipt, roi, now=NOW, **kw)


def test_container_inside_the_region_is_occupied():
    res = read(frame((360.0, 85.0)))
    assert (res["occupancy"], res["reason"]) == ("occupied", "container_in_region")
    assert res["containers_in_region"][0]["inside"] >= cbo.INSIDE


def test_clear_region_on_a_seen_belt_is_empty():
    res = read(frame((360.0, 85.0)), roi=(470, 60, 560, 130))
    assert (res["occupancy"], res["reason"]) == ("empty", "region_clear")


def test_nothing_seen_without_the_belt_is_not_empty():
    res = read(frame(belt=False), roi=(30, 20, 120, 90))
    assert (res["occupancy"], res["reason"]) == ("unknown", "belt_not_seen")


@pytest.mark.parametrize("moved, reason", [(True, "calibration_moved"), (None, "calibration_unverified")])
def test_unconfirmed_calibration_is_unknown_even_with_a_container(moved, reason):
    assert read(frame((360.0, 85.0)), camera_moved=moved)["reason"] == reason


@pytest.mark.parametrize("receipt, reason", [
    (None, "no_frame"),
    ({"image": None, "source_stamp": NOW}, "no_frame"),
    ({"image": "img", "source_stamp": None}, "no_source_stamp"),
    ({"image": "img", "source_stamp": float("nan")}, "no_source_stamp"),
    ({"image": "img", "source_stamp": 0.0}, "no_source_stamp"),
    ({"image": "img", "source_stamp": NOW - cbo.FRESH_S - 0.5}, "stale_frame"),
    ({"image": "img", "source_stamp": NOW + 5.0}, "stale_frame"),
])
def test_missing_or_old_frames_are_unknown(receipt, reason):
    res = cbo.read_belt_occupancy(receipt, REGION, camera_moved=False, joint_state_norm=STANDBY, now=NOW)
    assert (res["occupancy"], res["reason"]) == ("unknown", reason)


@pytest.mark.parametrize("joints, reason", [(None, "arm_state_unknown"), ([0.0, 1.0], "arm_state_unknown"),
                                            (EXTENDED, "arm_occluding_belt")])
def test_an_arm_state_that_does_not_prove_a_clear_view_is_unknown(joints, reason):
    assert read(frame((360.0, 85.0)), joint_state_norm=joints)["reason"] == reason


@pytest.mark.parametrize("roi", [(600, 60, 700, 120), (-10, 60, 80, 120), (300, 55, 300, 115)])
def test_a_region_not_wholly_in_the_frame_is_unknown(roi):
    assert read(frame((360.0, 85.0)), roi=roi)["reason"] == "roi_out_of_frame"


@pytest.mark.parametrize("x", [275.0, 265.0])  # about 40 % and under 15 % inside: a sliver is still not empty
def test_a_container_across_the_region_edge_is_unknown(x):
    res = read(frame((x, 85.0)))
    assert (res["occupancy"], res["reason"]) == ("unknown", "container_at_region_edge")
    assert 0 < res["edge_containers"][0]["inside"] < cbo.INSIDE
