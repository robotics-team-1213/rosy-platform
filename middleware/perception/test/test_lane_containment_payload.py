"""D-468 producer reports observed support and unknown geometry uncertainty."""
import importlib.util
import itertools
import math
import re
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
import yaml
from control.sensing.perception.camera_ground import GroundPlane
from control.sensing.perception.lane_containment import (
    PAINT_HALF_WIDTH_M, RECEIVER_EXTRAPOLATION_M, containment_payload, geometry_error, projection_uncertainty_m)


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
    # The detector fits the paint centre; the payload carries the paint's inner edge.
    assert raw["boundaries"][0]["intercept_m"] == pytest.approx(.08-PAINT_HALF_WIDTH_M*math.hypot(1, .1))


def test_boundaries_are_the_paint_inner_edge_moved_inward_by_half_the_paint():
    keeper = {"boundaries": [dict(selected=True, side=side, ends_m=[[.1, y], [.3, y]])
                             for side, y in (("left", .0925), ("right", -.0925))]}
    edges = {b["side"]: b for b in containment_payload(keeper, ground(), stamp=1., source="GAZEBO",
                                                        camera_x=.033)["boundaries"]}
    assert edges["left"]["intercept_m"] == pytest.approx(.080)
    assert edges["right"]["intercept_m"] == pytest.approx(-.080)
    wide = containment_payload(keeper, ground(), stamp=1., source="GAZEBO", camera_x=.033,
                               paint_half_width_m=.02)["boundaries"]
    assert [b["intercept_m"] for b in wide] == pytest.approx([.0725, -.0725])


def test_paint_shift_does_not_change_the_projection_uncertainty():
    keeper = {"boundaries": [dict(selected=True, side="left", ends_m=[[.1, .0925], [.3, .0925]])]}
    u = [containment_payload(keeper, ground(), stamp=1., source="GAZEBO", camera_x=.033,
                             paint_half_width_m=p)["uncertainty_m"] for p in (0., PAINT_HALF_WIDTH_M)]
    assert u[0] == u[1]


def test_paint_edges_that_cross_send_no_corridor():
    # Two paint lines closer than one paint width leave no drivable edge pair: send none
    # (an empty corridor), never a crossed pair the contract would reject.
    keeper = {"boundaries": [dict(selected=True, side=side, ends_m=[[.1, y], [.3, y]])
                             for side, y in (("left", .01), ("right", -.01))]}
    assert containment_payload(keeper, ground(), stamp=1., source="GAZEBO", camera_x=.033)["boundaries"] == []


def _paint_runs_mm(x_m):
    """Paint intervals (mm, along y) of the 260919 STL on the floor line x = x_m."""
    bundle = Path(__file__).resolve().parents[1] / "map" / "map_v2_fleet"
    spec = importlib.util.spec_from_file_location("stl_scene", bundle / "scripts" / "stl_scene.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    runs = []
    for tri in mod.load_scene(bundle / "260919 MAP FILE.STL").lines:
        ys = [a[1]+(x_m-a[0])/(b[0]-a[0])*(b[1]-a[1]) for a, b in itertools.combinations(tri, 2)
              if (a[0]-x_m)*(b[0]-x_m) <= 0 and a[0] != b[0]]
        if len(ys) >= 2:
            runs.append([min(ys), max(ys)])
    merged = []
    for lo, hi in sorted(runs):
        if merged and lo <= merged[-1][1]+1e-6:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(round(lo*1000, 1), round(hi*1000, 1)) for lo, hi in merged]


def test_paint_half_width_and_lane_half_width_are_the_260919_stl_straights():
    # STL nominal, unmeasured: the south straight's two lane lines (x 0.5..0.9 m).
    for x in (.5, .7, .9):
        (lo1, hi1), (lo2, hi2) = [r for r in _paint_runs_mm(x) if -620 < r[0] < -350]  # inside the 5 mm border line at -630
        assert hi1-lo1 == hi2-lo2 == pytest.approx(2*PAINT_HALF_WIDTH_M*1000)
        assert (lo2+hi2)/2-(lo1+hi1)/2 == pytest.approx(2*.0925*1000)
    config = yaml.safe_load((REPO / "middleware" / "perception" / "config" / "line_follow.yaml").read_text(encoding="utf-8"))
    params = config["/**/line_observer_node"]["ros__parameters"]
    assert params["lane_half_width_m"] == .0925
    assert params["lane_paint_half_width_m"] == PAINT_HALF_WIDTH_M


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



def test_a_record_that_states_its_fit_step_is_floored_at_that_step():
    from control.sensing.perception import camera_extrinsic as ce
    tiny = {"pitch_deg": .01, "roll_deg": .01, "height_m": .0001}
    pitch, height, roll, _px = geometry_error(RECORD, {"uncertainty": tiny, "fit_step": ce.PC_FINE_STEPS})
    assert pitch == pytest.approx(math.radians(.1))
    assert height == pytest.approx(.001)
    assert roll == pytest.approx(math.radians(1.5+.1))
    # A continuous fit (camera_board/1: solvePnP, no grid) states zero steps. Its scatter bands
    # cannot see shared systematic error, so it must state "systematic", added to each band.
    zero = {"pitch_deg": 0., "roll_deg": 0., "height_m": 0.}
    systematic = {"pitch_deg": .2, "roll_deg": .1, "height_m": .002}
    assert geometry_error(RECORD, {"uncertainty": tiny, "fit_step": zero}) is None
    pitch, height, roll, _px = geometry_error(RECORD, {"uncertainty": tiny, "fit_step": zero, "systematic": systematic})
    assert pitch == pytest.approx(math.radians(.01+.2)) and height == pytest.approx(.0001+.002)
    assert roll == pytest.approx(math.radians(1.5+.01+.1))
    for bad in ({"pitch_deg": -.1, "roll_deg": .1, "height_m": .001}, {"pitch_deg": .1},
                {"pitch_deg": float("nan"), "roll_deg": .1, "height_m": .001}, "0.1", None):
        assert geometry_error(RECORD, {"uncertainty": tiny, "fit_step": zero, "systematic": bad}) is None
    for bad in ({"pitch_deg": -.1, "roll_deg": .1, "height_m": .001}, {"pitch_deg": .1}, "0.1", None):
        assert geometry_error(RECORD, {"uncertainty": tiny, "fit_step": bad}) is None


@pytest.mark.parametrize("step", [{"pitch_deg": 1e-9, "roll_deg": 1e-9, "height_m": 1e-9},
                                  {"pitch_deg": .1, "roll_deg": 0., "height_m": .001},
                                  {"pitch_deg": .05, "roll_deg": .1, "height_m": .001}])
def test_a_step_finer_than_the_pc_grid_needs_a_systematic_term(step):
    tiny = {"pitch_deg": .01, "roll_deg": .01, "height_m": .0001}
    assert geometry_error(RECORD, {"uncertainty": tiny, "fit_step": step}) is None
    systematic = {"pitch_deg": .2, "roll_deg": .1, "height_m": .002}
    assert geometry_error(RECORD, {"uncertainty": tiny, "fit_step": step, "systematic": systematic}) is not None


def test_a_stated_systematic_is_added_to_a_grid_fit_too():
    from control.sensing.perception import camera_extrinsic as ce
    tiny = {"pitch_deg": .01, "roll_deg": .01, "height_m": .0001}
    systematic = {"pitch_deg": .2, "roll_deg": .1, "height_m": .002}
    pitch, height, roll, _px = geometry_error(RECORD, {"uncertainty": tiny, "fit_step": ce.PC_FINE_STEPS,
                                                       "systematic": systematic})
    assert pitch == pytest.approx(math.radians(.1+.2)) and height == pytest.approx(.001+.002)
    assert roll == pytest.approx(math.radians(1.5+.1+.1))
    assert geometry_error(RECORD, {"uncertainty": tiny, "fit_step": ce.PC_FINE_STEPS, "systematic": "x"}) is None

def test_receiver_extrapolation_is_mirrored():
    text = (REPO / "middleware" / "core" / "services" / "core_features" / "line_follow" /
            "lane_return_evidence.py").read_text(encoding="utf-8")
    assert re.search(r"MAX_EXTRAPOLATION_M = ([0-9.]+)", text).group(1) in (".3", "0.3")
    assert RECEIVER_EXTRAPOLATION_M == .3


def _truth(h, pitch, roll, a, b):
    # Independent rotation-matrix camera (reviewer check.py): floor point along normalized ray (a, b).
    fwd = np.array([math.cos(pitch), 0., -math.sin(pitch)])
    right, down = np.array([0., 1., 0.]), np.array([-math.sin(pitch), 0., -math.cos(pitch)])
    r, d = right*math.cos(roll)+down*math.sin(roll), -right*math.sin(roll)+down*math.cos(roll)
    ray = fwd+np.outer(a, r)+np.outer(b, d)
    t = np.where(ray[:, 2] < 0, h/np.maximum(-ray[:, 2], 1e-12), np.nan)
    return ray[:, 0]*t, ray[:, 1]*t


def _excess(profile, error, rolls):
    # Worst (true error - declared bound) over read boundaries and true geometries: pitch and height
    # at their bounds, roll at every level in ``rolls`` (interior too), each end's column +-px.
    pitch_e, height_e, _roll, px = error
    h, th, f = profile["height_m"], profile["pitch_rad"], profile["fx"]
    g = plane(profile)
    u1, u2 = (u.ravel() for u in np.meshgrid([-px/f, px/f], [-px/f, px/f]))
    worst = -1.
    # The last two pairs/slopes hold the re-review's interior-roll worst cases.
    for (x1, x2), s, y0 in itertools.product(((.12, .2), (.2, .3), (.12, .45), (.4, .45), (.09, .29), (.13, .43)),
                                             (-.4, 0., .2, .4, .5), (-.12, 0., .06, .12)):
        ends = ((x1, y0), (x2, y0+s*(x2-x1)))
        stated = projection_uncertainty_m(g, error, [ends])
        rays = []
        for x, y in ends:
            depth = x*math.cos(th)+h*math.sin(th)
            rays.append((y/depth, (h*math.cos(th)-x*math.sin(th))/depth))
        for dp, dh, roll in itertools.product((-pitch_e, pitch_e), (-height_e, height_e), rolls):
            tx1, ty1 = _truth(h+dh, th+dp, roll, rays[0][0]+u1, np.full(4, rays[0][1]))
            tx2, ty2 = _truth(h+dh, th+dp, roll, rays[1][0]+u2, np.full(4, rays[1][1]))
            if np.isnan(tx1).any() or np.isnan(tx2).any():
                assert stated == 1.0
                continue
            ts = (ty2-ty1)/(tx2-tx1)
            true = max(np.abs(y0+s*(x-x1)-(ty1+ts*(x-tx1))).max()
                       for x in (x1-RECEIVER_EXTRAPOLATION_M, x2+RECEIVER_EXTRAPOLATION_M))
            worst = max(worst, min(true, 1.0)-stated)
    return worst


def test_bound_covers_the_true_projection_error_for_the_nominal_profile():
    error = geometry_error(PROFILE, None)
    assert _excess(PROFILE, error, np.linspace(-error[2], error[2], 21)) <= 1e-12


def test_bound_covers_the_true_projection_error_for_a_record():
    # True roll anywhere in the record's -1.5 +-0.5 deg band, either sign convention.
    error = geometry_error(RECORD, INTERVALS)
    band = np.radians(np.linspace(-1.5-BANDS["roll_deg"], -1.5+BANDS["roll_deg"], 21))
    assert _excess(RECORD, error, np.concatenate([band, -band])) <= 1e-12


def test_a_ray_that_may_clear_the_true_horizon_is_excessive_not_bounded():
    g = SimpleNamespace(height_m=.06, pitch_rad=.14, focal_px=281.6)
    assert projection_uncertainty_m(g, (.07, 0., 0., 2.), [((.5, .09), (1., .09))]) == 1.0
