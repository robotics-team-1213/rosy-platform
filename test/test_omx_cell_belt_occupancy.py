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
ON_BELT = (450, 80, 520, 115)  # wholly on the belt strip, away from the container
CHECKED = {"camera_moved": False, "camera_shift": {"ok": True, "max_px": 0.4}}  # cell_calibrate.check against a reference


def frame(container_at=None, belt=True, speck_at=None, slab=False):
    """Grey floor, yellow table, a dark belt strip centred (430, 100) at 12 deg, optional red-orange container."""
    top = np.full((480, 640, 3), (150, 150, 145), dtype=np.uint8)
    top[220:470, 220:550] = (95, 210, 220)
    if belt:
        cv2.fillConvexPoly(top, np.int32(cv2.boxPoints(((430.0, 100.0), (340.0, 110.0), 12.0))), (42, 42, 40))
    if slab:  # one long orange object, big enough for the belt detector to take its outline for the belt
        cv2.fillConvexPoly(top, np.int32(cv2.boxPoints(((360.0, 85.0), (200.0, 60.0), 12.0))), (35, 45, 235))
    if container_at is not None:
        cv2.fillConvexPoly(top, np.int32(cv2.boxPoints((container_at, (75.0, 26.0), 12.0))), (35, 45, 235))
    if speck_at is not None:  # orange under the detector's 250 px area floor
        cv2.rectangle(top, (speck_at[0] - 6, speck_at[1] - 6), (speck_at[0] + 6, speck_at[1] + 6), (35, 45, 235), -1)
    return top


def read(image, roi=REGION, **kw):
    receipt = kw.pop("receipt", {"image": image, "source_seq": 7, "source_stamp": NOW})
    kw.setdefault("calibration", CHECKED)
    kw.setdefault("joint_state_norm", STANDBY)
    return cbo.read_belt_occupancy(receipt, roi, now=NOW, **kw)


def test_container_inside_the_region_is_occupied():
    res = read(frame((360.0, 85.0)))
    assert (res["occupancy"], res["reason"]) == ("occupied", "container_in_region")
    assert res["containers_in_region"][0]["inside"] >= cbo.INSIDE


def test_clear_region_on_a_seen_belt_is_empty():
    res = read(frame((360.0, 85.0)), roi=ON_BELT)
    assert (res["occupancy"], res["reason"]) == ("empty", "region_clear")


@pytest.mark.parametrize("image, roi, reason", [
    (frame(belt=False), (30, 20, 120, 90), "belt_not_seen"),
    (frame((360.0, 85.0), belt=False), REGION, "belt_not_seen"),  # a container in the region is still no proof without the belt
    (frame(belt=False, slab=True), (320, 70, 400, 100), "belt_not_seen"),  # an orange slab is not a belt
    (frame((360.0, 85.0)), (30, 20, 120, 90), "region_off_belt"),  # the belt is seen, elsewhere
    (frame((360.0, 85.0), speck_at=(485, 97)), ON_BELT, "unexplained_orange"),
    (frame((360.0, 85.0), speck_at=(445, 97)), ON_BELT, "unexplained_orange"),  # reaches in by two columns
])
def test_nothing_detected_is_not_empty_without_proof(image, roi, reason):
    res = read(image, roi=roi)
    assert (res["occupancy"], res["reason"]) == ("unknown", reason)


@pytest.mark.parametrize("calibration, reason", [
    ({"camera_moved": True, "camera_shift": {"ok": False}}, "calibration_moved"),
    ({"camera_moved": False, "no_reference": True}, "calibration_unverified"),  # check() without a reference frame
    ({"camera_moved": False}, "calibration_unverified"),
    ({}, "calibration_unverified"),
    (None, "calibration_unverified"),
])
def test_unconfirmed_calibration_is_unknown_even_with_a_container(calibration, reason):
    res = read(frame((360.0, 85.0)), calibration=calibration)
    assert (res["occupancy"], res["reason"]) == ("unknown", reason)


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
    res = cbo.read_belt_occupancy(receipt, REGION, calibration=CHECKED, joint_state_norm=STANDBY, now=NOW)
    assert (res["occupancy"], res["reason"]) == ("unknown", reason)


@pytest.mark.parametrize("joints, reason", [(None, "arm_state_unknown"), ([0.0, 1.0], "arm_state_unknown"),
                                            (EXTENDED, "arm_occluding_belt")])
def test_an_arm_state_that_does_not_prove_a_clear_view_is_unknown(joints, reason):
    res = read(frame((360.0, 85.0)), joint_state_norm=joints)
    assert (res["occupancy"], res["reason"]) == ("unknown", reason)


@pytest.mark.parametrize("roi", [(600, 60, 700, 120), (-10, 60, 80, 120), (300, 55, 300, 115)])
def test_a_region_not_wholly_in_the_frame_is_unknown(roi):
    res = read(frame((360.0, 85.0)), roi=roi)
    assert (res["occupancy"], res["reason"]) == ("unknown", "roi_out_of_frame")


@pytest.mark.parametrize("x", [275.0, 265.0])  # about 40 % and under 15 % inside: a sliver is still not empty
def test_a_container_across_the_region_edge_is_unknown(x):
    res = read(frame((x, 85.0)))
    assert (res["occupancy"], res["reason"]) == ("unknown", "container_at_region_edge")
    assert 0 < res["edge_containers"][0]["inside"] < cbo.INSIDE
