"""D-468 producer reports observed support and unknown geometry uncertainty."""
import math
from pathlib import Path
from types import SimpleNamespace
import pytest
import yaml
from control.sensing.perception.camera_ground import GroundPlane
from control.sensing.perception.lane_containment import containment_payload, geometry_error, projection_uncertainty_m


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
PROFILE = yaml.safe_load((Path(__file__).resolve().parents[3] / "middleware" / "apps" / "device" /
    "pinky" / "profile" / "config" / "camera_nominal.yaml").read_text(encoding="utf-8"))
RECORD = {**PROFILE, "pitch_rad": math.radians(11.2), "roll_rad": math.radians(-1.5), "height_m": .0575}
INTERVALS = {"uncertainty": {"pitch_deg": .25, "roll_deg": .5, "height_m": .005}}


def keeper(far):
    return {"boundaries": [dict(selected=True, side="left", ends_m=[[.12, .0925], [far, .0925]])]}


def payload(far, profile, intervals, source):
    g = SimpleNamespace(height_m=profile["height_m"], pitch_rad=profile["pitch_rad"], focal_px=profile["fx"],
        principal_x=profile["cx"], principal_y=profile["cy"], max_range_m=profile["max_range_m"])
    return containment_payload(keeper(far), g, stamp=1., source=source, camera_x=PROFILE["x_offset_m"],
                               geometry_bounds=geometry_error(profile, intervals))["uncertainty_m"]


def test_uncertainty_grows_with_range_and_nominal_exceeds_calibrated():
    nominal = [payload(far, PROFILE, None, "NOMINAL") for far in (.2, .3, .4)]
    calibrated = [payload(far, RECORD, INTERVALS, "CALIBRATED") for far in (.2, .3, .4)]
    assert nominal == sorted(nominal) and len(set(nominal)) == 3
    assert calibrated == sorted(calibrated) and len(set(calibrated)) == 3
    assert all(n > c for n, c in zip(nominal, calibrated))


def test_geometry_error_is_unknown_without_a_stated_bound():
    assert geometry_error({k: v for k, v in PROFILE.items() if k != "pitch_uncertainty_rad"}, None) is None
    assert geometry_error(RECORD, {"uncertainty": None}) is None
    assert geometry_error(RECORD, {}) is None
    assert geometry_error(PROFILE, None, overridden={"pitch_rad"}) is None
    # A record that kept the base height (height band None) borrows the nominal height bound.
    kept = geometry_error(RECORD, {"uncertainty": {**INTERVALS["uncertainty"], "height_m": None}})
    assert kept[1] == PROFILE["height_uncertainty_m"]
    # The ground ignores roll, so a record's fitted roll counts as error on top of its band.
    assert geometry_error(RECORD, INTERVALS)[2] == pytest.approx(math.radians(1.5+.5))


@pytest.mark.parametrize("d", [.1, .2, .3])
@pytest.mark.parametrize("dp,dh", [(1, 1), (1, -1), (-1, 1), (-1, -1)])
def test_bound_covers_the_true_projection_error(d, dp, dh):
    # Image a floor point with the true geometry (nominal +- the bounds), read it back with the
    # nominal plane: the lateral error stays inside the declared uncertainty (roll set aside).
    pitch_e, height_e, _roll = geometry_error(PROFILE, None)
    h, th = PROFILE["height_m"], PROFILE["pitch_rad"]
    th_t, h_t, f, y = th+dp*pitch_e, h+dh*height_e, PROFILE["fx"], .0925
    z = d*math.cos(th_t)+h_t*math.sin(th_t)
    row, col = PROFILE["cy"]+f*(h_t*math.cos(th_t)-d*math.sin(th_t))/z, PROFILE["cx"]+f*y/z
    plane = GroundPlane(h, th, f, PROFILE["cx"], PROFILE["cy"], 5.)
    got = plane.distance(row)
    error = abs(plane.lateral(col, row)-y)
    bound = projection_uncertainty_m(plane, (pitch_e, height_e, 0.), far_m=got, lateral_m=y)
    assert error <= bound


def test_a_ray_that_may_clear_the_true_horizon_is_excessive_not_bounded():
    g = SimpleNamespace(height_m=.06, pitch_rad=.14, focal_px=281.6)
    assert projection_uncertainty_m(g, (.07, 0., 0.), far_m=1., lateral_m=.09) == 1.0
