"""D-468 producer reports observed support and unknown geometry uncertainty."""
import itertools
import math
import re
from pathlib import Path
from types import SimpleNamespace
import pytest
import yaml
from control.sensing.perception.camera_ground import GroundPlane
from control.sensing.perception.lane_containment import (
    RECEIVER_EXTRAPOLATION_M, containment_payload, geometry_error, projection_uncertainty_m)


def ground():
    return SimpleNamespace(height_m=.055, pitch_rad=.21, focal_px=281.6,
        principal_x=160., principal_y=120., max_range_m=1.)


def test_payload_preserves_original_image_and_measured_support():
    keeper = {"boundaries": [dict(selected=True, side="left",
                ends_m=[[.2,.1],[.4,.12]])]}
    raw = containment_payload(keeper, ground(), stamp=1.25, source="NOMINAL", camera_x=.033)
    assert raw["stamp"] == 1.25
    assert raw["uncertainty_m"] is None
    assert raw["boundaries"][0]["observed_x_min_m"] == .2
    assert raw["boundaries"][0]["intercept_m"] == pytest.approx(.08)


def test_geometry_change_invalidates_identity_and_unselected_edges_are_ignored():
    keeper = {"boundaries": [dict(selected=False, side="left", ends_m=[[.2,.1],[.4,.12]])]}
    g = ground()
    before = containment_payload(keeper, g, stamp=1., source="NOMINAL", camera_x=.033)
    g.pitch_rad += .01
    after = containment_payload(keeper, g, stamp=2., source="NOMINAL", camera_x=.033)
    assert before["geometry_id"] != after["geometry_id"]
    assert before["boundaries"] == []


def test_absent_ground_does_not_fabricate_calibration():
    assert containment_payload({}, None, stamp=1., source="NOMINAL", camera_x=.033) is None


@pytest.mark.parametrize("source", ["NOMINAL", "CALIBRATED"])
def test_device_grounds_without_a_geometry_error_keep_unknown_uncertainty(source):
    assert containment_payload({}, ground(), stamp=1., source=source, camera_x=.033)["uncertainty_m"] is None


def test_gazebo_ground_declares_the_detector_pixel_error_only():
    # Exact sim camera geometry: 2 px lateral at the farthest ground range's depth, nothing else.
    g = ground()
    g.max_range_m = .6
    raw = containment_payload({}, g, stamp=1., source="GAZEBO", camera_x=.033)
    depth = .6*math.cos(.21)+.055*math.sin(.21)
    assert raw["uncertainty_m"] == pytest.approx(2*depth/281.6)
    assert raw["uncertainty_m"] < .015  # inside the D-468 receiver's MAX_UNCERTAINTY_M


# D-468 uncertainty for real grounds: URDF nominal bounds (camera_nominal.yaml) vs a
# camera_profile record's score bands (D-47 table: 8kcn pitch 11.2 +-0.25 deg, roll -1.5 deg,
# height 0.0575 +-0.005 m; the roll band is not in the table, 0.5 deg is one fine roll step).
REPO = Path(__file__).resolve().parents[3]
PROFILE = yaml.safe_load((REPO / "middleware" / "apps" / "device" / "pinky" / "profile" / "config" /
                          "camera_nominal.yaml").read_text(encoding="utf-8"))
RECORD = {**PROFILE, "pitch_rad": math.radians(11.2), "roll_rad": math.radians(-1.5), "height_m": .0575}
BANDS = {"pitch_deg": .25, "roll_deg": .5, "height_m": .005}
INTERVALS = {"uncertainty": BANDS}


def keeper(far):
    # A fixed 0.1 m support moved out: a longer support would shorten the extrapolation lever.
    return {"boundaries": [dict(selected=True, side="left", ends_m=[[far-.1, .0925], [far, .0925]])]}


def plane(profile):
    return GroundPlane(profile["height_m"], profile["pitch_rad"], profile["fx"], profile["cx"], profile["cy"], 5.)


def payload(far, profile, intervals, source):
    return containment_payload(keeper(far), plane(profile), stamp=1., source=source, camera_x=PROFILE["x_offset_m"],
                               geometry_bounds=geometry_error(profile, intervals))["uncertainty_m"]


def test_uncertainty_grows_with_range_and_nominal_exceeds_calibrated():
    nominal = [payload(far, PROFILE, None, "NOMINAL") for far in (.2, .3, .4)]
    calibrated = [payload(far, RECORD, INTERVALS, "CALIBRATED") for far in (.2, .3, .4)]
    assert nominal == sorted(nominal) and len(set(nominal)) == 3
    assert calibrated == sorted(calibrated) and len(set(calibrated)) == 3
    assert all(n > c for n, c in zip(nominal, calibrated))


def test_geometry_error_is_unknown_without_a_stated_bound():
    assert geometry_error({k: v for k, v in PROFILE.items() if k != "pitch_uncertainty_rad"}, None) is None
    assert geometry_error({k: v for k, v in RECORD.items() if k != "detector_lateral_px"}, INTERVALS) is None
    assert geometry_error(RECORD, {"uncertainty": None}) is None
    assert geometry_error(RECORD, {}) is None
    assert geometry_error(PROFILE, None, overridden={"pitch_rad"}) is None
    for key in BANDS:  # a zero band is a rounded fit, not a perfect one
        assert geometry_error(RECORD, {"uncertainty": {**BANDS, key: 0.0}}) is None
    # A record that kept the base height (height band None) borrows the nominal height bound.
    kept = geometry_error(RECORD, {"uncertainty": {**BANDS, "height_m": None}})
    assert kept[1] == PROFILE["height_uncertainty_m"]
    # The ground ignores roll, so a record's fitted roll counts as error on top of its band.
    assert geometry_error(RECORD, INTERVALS)[2] == pytest.approx(math.radians(1.5+.5))


def test_record_bands_are_floored_at_one_fit_search_step():
    from control.sensing.perception import camera_extrinsic as ce
    pitch, height, roll, _px = geometry_error(RECORD, {"uncertainty": {"pitch_deg": .01, "roll_deg": .01,
                                                                       "height_m": .0001}})
    assert pitch == pytest.approx(math.radians(ce.FINE_PITCH_STEP_DEG))
    assert height == ce.FINE_HEIGHT_STEP_M
    assert roll == pytest.approx(math.radians(1.5+ce.FINE_ROLL_STEP_DEG))


def test_receiver_extrapolation_is_mirrored():
    text = (REPO / "middleware" / "core" / "services" / "core_features" / "line_follow" /
            "lane_return_evidence.py").read_text(encoding="utf-8")
    assert re.search(r"MAX_EXTRAPOLATION_M = ([0-9.]+)", text).group(1) in (".3", "0.3")
    assert RECEIVER_EXTRAPOLATION_M == .3


def _image(x, y, h, pitch, roll, f, cx, cy):
    # The true camera images the floor point x ahead of the lens, y aside (reviewer check.py).
    depth = x*math.cos(pitch)+h*math.sin(pitch)
    down = -x*math.sin(pitch)+h*math.cos(pitch)
    xr, yr = y*math.cos(roll)-down*math.sin(roll), y*math.sin(roll)+down*math.cos(roll)
    return cx+f*xr/depth, cy+f*yr/depth


def _excess(profile, error, truths):
    # Worst (true error - declared bound) over far ranges, boundary slopes and true geometries.
    g = plane(profile)
    worst = -1.
    for far, slope, (dp, dh, roll) in itertools.product((.15, .2, .3, .4), (0., .2, .4), truths):
        near = .12-PROFILE["x_offset_m"]
        line = lambda x: .0925+slope*(x-near)  # noqa: E731
        read = []
        for x in (near, far):
            col, row = _image(x, line(x), g.height_m+dh, g.pitch_rad+dp, roll, g.focal_px, g.principal_x, g.principal_y)
            read.append((g.distance(row), g.lateral(col, row)))
        (x1, y1), (x2, y2) = read
        read_slope = (y2-y1)/(x2-x1)
        error_m = max(abs(y1+read_slope*(x-x1)-line(x))
                      for x in (x1-RECEIVER_EXTRAPOLATION_M, x2+RECEIVER_EXTRAPOLATION_M))
        worst = max(worst, error_m-projection_uncertainty_m(g, error, [tuple(read)]))
    return worst


def test_bound_covers_the_true_projection_error_for_the_nominal_profile():
    p, h, r, _px = error = geometry_error(PROFILE, None)
    truths = [(sp*p, sh*h, sr*r) for sp in (-1, 0, 1) for sh in (-1, 0, 1) for sr in (-1, 0, 1)]
    assert _excess(PROFILE, error, truths) <= 0


def test_bound_covers_the_true_projection_error_for_a_record():
    error = geometry_error(RECORD, INTERVALS)
    p, h = math.radians(BANDS["pitch_deg"]), BANDS["height_m"]
    rolls = [sign*math.radians(-1.5+sr*BANDS["roll_deg"]) for sign in (-1, 1) for sr in (-1, 0, 1)]
    truths = [(sp*p, sh*h, roll) for sp in (-1, 1) for sh in (-1, 1) for roll in rolls]
    assert _excess(RECORD, error, truths) <= 0


def test_a_ray_that_may_clear_the_true_horizon_is_excessive_not_bounded():
    g = SimpleNamespace(height_m=.06, pitch_rad=.14, focal_px=281.6)
    assert projection_uncertainty_m(g, (.07, 0., 0., 2.), [((.5, .09), (1., .09))]) == 1.0
