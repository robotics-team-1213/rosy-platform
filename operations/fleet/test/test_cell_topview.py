"""Cell top-view precision docking at S3 (2026-11-27): the registration and offset math on stored real frames, the
verdicts, the correction loop with a fake camera, and every fail-closed path."""

import asyncio
import math
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from core_common.stop_pose import REPARK_MAX_LEFT_M
from fleet.hub.hub import HubError
from fleet.localization import topview_pose as tp
from fleet.server import named_stop_topview as nt
from fleet.server.auto_repark import auto_repark, evaluate_named_stop
from fleet.server.correction_corridor import correction_endpoint
from fleet.server.named_stop_decision import _aligned
from fleet.server.precision_correction_routes import CorrectionClearance
from fleet.server.trip_ports import TripConfig
from fleet.site_map import SitePlace
from fleet.traffic.trip_lease import HELD

ROOT = Path(__file__).resolve().parents[3]
DATA_FILE = ROOT / "deploy/site/cell-topview/s3.json"
FIXTURES = Path(__file__).parent / "fixtures/cell_topview"
LIVE = (FIXTURES / "s3_live.jpg").read_bytes()  # arm_s_top 2026-11-27, rosy_45 parked 3-4 cm off the training spot
TRAIN = (FIXTURES / "s3_train_ep000.jpg").read_bytes()
RUN = "11111111-1111-4111-8111-111111111111"
FIT = NS(apply=lambda point: tuple(point), yaw=0.0, max=0.0)
EVIDENCE = {"map_sha256": "a" * 64, "place": "S3"}
PLACE = SitePlace(id="S3", name="S3", x=1.0, y=0.5, yaw=math.pi, kind="stop", pinned=True, precision_stop=dict(
    evidence_ref="model S top view", reference_pose=(1.0, 0.5, math.pi), longitudinal_m=0.03, lateral_m=0.03,
    heading_rad=math.radians(5), position_uncertainty_m=0.008, heading_uncertainty_rad=0.035,
    max_correction_m=0.05))
PLACE_DATA = PLACE.model_dump(mode="json")


@pytest.fixture(scope="module")
def data():
    return tp.load_data(DATA_FILE)


def obs(dx=0.0, dy=0.0, dyaw=0.0, sigma=0.008):
    return {"dx": dx, "dy": dy, "dyaw": dyaw, "sigma_m": sigma, "sigma_rad": 0.035, "inliers": 40, "rms_px": 1.0,
            "marker_id": None}


def cv2_np():
    import cv2
    import numpy as np
    return cv2, np


# --- registration and offset math on real frames -------------------------------------------------------------

def test_live_frame_offset_matches_what_the_cell_showed(data):
    seen = tp.observe(data, LIVE, "rosy_45")
    # rosy_45 stood about 3 cm short in x and 3.4 cm to +y of the training spot, turned a few degrees (hand check of overlay.png)
    assert seen["dx"] == pytest.approx(-0.031, abs=0.004) and seen["dy"] == pytest.approx(0.0336, abs=0.004)
    assert math.degrees(seen["dyaw"]) == pytest.approx(-5.1, abs=1.5)
    assert seen["inliers"] >= data.min_inliers and seen["marker_id"] is None  # S3 crops the marker at the frame top


def test_a_training_frame_lies_inside_the_training_scatter(data):
    seen = tp.observe(data, TRAIN)
    assert math.hypot(seen["dx"], seen["dy"]) < 0.04 and abs(seen["dyaw"]) < math.radians(12)


@pytest.mark.parametrize("angle, shift", [(3.0, (0, 0)), (-4.0, (12, -9))])
def test_a_camera_that_moved_since_does_not_change_the_answer(data, angle, shift):
    cv2, np = cv2_np()
    frame = cv2.imdecode(np.frombuffer(LIVE, np.uint8), cv2.IMREAD_COLOR)
    matrix = cv2.getRotationMatrix2D((320, 240), angle, 1.0)
    matrix[:, 2] += shift
    moved = cv2.warpAffine(frame, matrix, (640, 480), borderMode=cv2.BORDER_REPLICATE)
    seen, base = tp.observe(data, cv2.imencode(".jpg", moved)[1].tobytes()), tp.observe(data, LIVE)
    assert math.hypot(seen["dx"] - base["dx"], seen["dy"] - base["dy"]) < 0.006
    assert abs(seen["dyaw"] - base["dyaw"]) < math.radians(2.5)


def test_marker_of_another_robot_is_refused_and_the_own_one_is_reported(data):
    cv2, np = cv2_np()
    frame = cv2.imdecode(np.frombuffer(LIVE, np.uint8), cv2.IMREAD_COLOR)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)

    def with_marker(marker_id):
        out = frame.copy()
        make = getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker  # OpenCV 4.6 on CI
        marker = make(dictionary, marker_id, 120)
        out[300:420, 20:140] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)  # left of the registration mask
        return cv2.imencode(".jpg", out)[1].tobytes()

    assert tp.observe(data, with_marker(45), "rosy_45")["marker_id"] == 45
    assert tp.observe(data, with_marker(9), "rosy_45")["marker_id"] is None  # not a Pinky: no refusal
    with pytest.raises(tp.TopviewError) as refused:
        tp.observe(data, with_marker(46), "rosy_45")
    assert refused.value.reason == "marker_other_robot"


def test_frames_that_cannot_be_trusted_raise_a_reason(data):
    cv2, np = cv2_np()
    frame = cv2.imdecode(np.frombuffer(LIVE, np.uint8), cv2.IMREAD_COLOR)
    flat = cv2.imencode(".jpg", np.full((480, 640, 3), 90, np.uint8))[1].tobytes()
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    orange = cv2.inRange(hsv, np.array(data.tray_hsv[0]), np.array(data.tray_hsv[1])) > 0
    orange[:, 340:] = False
    no_tray = frame.copy()
    no_tray[orange] = (110, 110, 110)
    small = cv2.resize(frame, (320, 240))
    for jpeg, reason in ((flat, ("registration_no_features", "registration_too_few_matches", "registration_too_few_inliers")),
                         (cv2.imencode(".jpg", no_tray)[1].tobytes(), ("tray_not_found", "tray_too_small")),
                         (cv2.imencode(".jpg", small)[1].tobytes(), ("frame_unreadable",)), (b"not a jpeg", ("frame_unreadable",))):
        with pytest.raises(tp.TopviewError) as refused:
            tp.observe(data, jpeg)
        assert refused.value.reason in reason


def test_self_calibration_recovers_the_scale_from_one_move_and_the_axes_from_two():
    base = [[0.0, 1 / 1160], [1 / 1160, 0.0]]
    true = [[0.0, 1 / 1000], [1 / 1000, 0.0]]
    move = ((100.0, 100.0), (100.0 + 50.0, 100.0 + 30.0))  # (u, v) before / after
    site = (30 / 1000, 50 / 1000)
    scaled = tp.solve_px_to_site([(*move, site)], base)
    assert scaled[0][1] == pytest.approx(true[0][1]) and scaled[1][0] == pytest.approx(true[1][0])
    other = ((100.0, 100.0), (130.0, 150.0))
    two = tp.solve_px_to_site([(*move, site), (*other, (50 / 1000, 30 / 1000))], base)
    assert sum(two, []) == pytest.approx(sum(true, []), abs=1e-9)
    with pytest.raises(tp.TopviewError):
        tp.solve_px_to_site([((1.0, 1.0), (1.0, 1.0), (0.0, 0.0))], base)


# --- the verdict ------------------------------------------------------------------------------------------------

def test_inside_tolerance_is_in_tolerance_and_names_its_source():
    verdict = nt.topview_decision(PLACE, obs(0.005, -0.004, 0.02))
    assert verdict["decision"] == "IN_TOLERANCE" and verdict["source"] == "cell_topview"


def test_a_sideways_offset_is_corrected_in_the_robots_own_axes():
    # target heading pi: robot-forward is -x, robot-left is -y. Robot 4 cm to +y of the target: the target is 4 cm to its left
    verdict = nt.topview_decision(PLACE, obs(0.0, 0.04, 0.0))
    assert verdict["decision"] == "REPARK" and verdict["forward_m"] == pytest.approx(0.0, abs=1e-4)
    assert verdict["left_m"] == pytest.approx(0.04, abs=1e-4)
    both = nt.topview_decision(PLACE, obs(-0.03, 0.04, 0.0))  # 3 cm past the target along -x: it lies 3 cm behind
    assert both["decision"] == "REPARK" and math.hypot(both["forward_m"], both["left_m"]) == pytest.approx(0.05, abs=1e-3)
    assert both["forward_m"] == pytest.approx(-0.03, abs=1e-3)


def test_a_turned_robot_and_a_long_move_are_holds_not_corrections():
    assert nt.topview_decision(PLACE, obs(0.0, 0.0, math.radians(6)))["reason"] == "heading_outside_limits"
    assert nt.topview_decision(PLACE, obs(0.0, 0.07, 0.0))["reason"] == "outside_repark_limits"
    assert nt.topview_decision(PLACE, obs(0.0, 0.0, 0.0, sigma=0.04))["reason"] == "correction_below_resolution"


def test_a_noisy_registration_widens_the_margin_instead_of_passing():
    assert nt.topview_decision(PLACE, obs(0.015, 0.0, 0.0, sigma=0.008))["decision"] == "IN_TOLERANCE"
    assert nt.topview_decision(PLACE, obs(0.015, 0.0, 0.0, sigma=0.02))["decision"] == "REPARK"


def test_the_stored_verdict_expires_and_needs_a_still_robot():
    pose = {"x": 1.0, "y": 0.5, "yaw": math.pi}
    record = {"place": "S3", "decision": {"decision": "REPARK"}, "read_at": 100.0, "pose": pose}
    assert nt.current_verdict(record, {"pose": pose}, 105.0, "S3") == {"decision": "REPARK"}
    assert nt.current_verdict(record, {"pose": pose}, 111.0, "S3") is None
    assert nt.current_verdict(record, {"pose": {**pose, "x": 1.02}}, 105.0, "S3") is None
    assert nt.current_verdict(record, {"pose": pose}, 105.0, "S4") is None  # another stop never reuses it
    assert nt.current_verdict(record, {}, 105.0, "S3") is None and nt.current_verdict(None, {"pose": pose}, 105.0, "S3") is None


# --- the camera --------------------------------------------------------------------------------------------------

def headers(seq, stamp=1000.0, date="Fri, 27 Nov 2026 00:00:00 GMT"):
    from email.utils import parsedate_to_datetime
    served = parsedate_to_datetime(date).timestamp()
    return {"X-Frame-Seq": str(seq), "X-Source-Stamp": str(served + stamp), "Date": date}


def camera(frames, monkeypatch, results):
    queue, seen = list(frames), list(results)

    async def fetch():
        return b"jpeg", queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(nt, "observe", lambda data, jpeg, robot: dict(seen.pop(0) if len(seen) > 1 else seen[0]))

    async def nap(_):
        return None

    return nt.CellTopview(NS(max_frame_age_s=2.0), fetch, sleep=nap)


def test_two_fresh_agreeing_frames_are_averaged(monkeypatch):
    cam = camera([headers(1, -0.5), headers(2, -0.5)], monkeypatch, [obs(0.01, 0.02, 0.0), obs(0.012, 0.022, 0.01)])
    seen = asyncio.run(cam.read("rosy_45"))
    assert seen["dx"] == pytest.approx(0.011) and seen["dy"] == pytest.approx(0.021) and seen["dyaw"] == pytest.approx(0.005)


@pytest.mark.parametrize("frames, results, reason", [
    ([headers(1, -3.5), headers(2, -3.5)], [obs()], "frame_stale"),
    ([headers(1, 2.5), headers(2, 2.5)], [obs()], "frame_stale"),  # stamped in the future
    ([headers(1, -0.5)], [obs()], "frame_not_advancing"),
    ([headers(1, -0.5), headers(2, -0.5)], [obs(0.0), obs(0.03)], "frames_disagree"),  # the robot was moving
    ([{"Date": "x"}], [obs()], "frame_unstamped"),
])
def test_a_camera_that_cannot_prove_a_still_fresh_robot_is_no_evidence(monkeypatch, frames, results, reason):
    cam = camera(frames, monkeypatch, results)
    with pytest.raises(tp.TopviewError) as refused:
        asyncio.run(cam.read("rosy_45"))
    assert refused.value.reason == reason


def test_the_camera_is_off_unless_configured_and_a_missing_cell_raises(tmp_path):
    assert nt.CellTopview.from_env({}) is None
    jobs = tmp_path / "jobs.json"
    jobs.write_text('{"cells": {}}', encoding="utf-8")
    with pytest.raises(ValueError):
        nt.CellTopview.from_env({nt.CONFIG_ENV: str(DATA_FILE), "ROSY_FLEET_CELL_JOBS": str(jobs)})


# --- the loop ----------------------------------------------------------------------------------------------------

class Core:
    def __init__(self):
        self.posts, self.armed_now = [], False

    def armed(self, robot_id):
        return self.armed_now

    async def send(self, trip_id, clearance):
        self.posts.append(clearance)
        self.armed_now = True
        return {"accepted": True}


class FakeTopview:
    def __init__(self, *reads):
        self.reads, self.calls = list(reads), 0

    def covers(self, place_id):
        return place_id == "S3"

    async def read(self, robot_id):
        self.calls += 1
        value = self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]
        if isinstance(value, Exception):
            raise value
        return value


def state(**override):
    base = {"pose_frame": "map", "pose": {"x": 1.0, "y": 0.5, "yaw": math.pi},
            "evidence": {"pose": {"evidence": "fresh"}, "velocity": {"evidence": "fresh"}},
            "safety": {"estop": False}, "localization": {"state": "LOCALIZED", "pose_frame": "map"}}
    return {**base, **override}


def rig(topview, core, corrections=3, camera_pose=None):
    async def check(live, evidence, place):
        verdict = (live.view["detail"].get(nt.KEY) or {}).get("decision") or {"forward_m": 0.04}
        return {**verdict, "site_end": [1.0, 0.5], "terminal_arc": "arc"}

    async def map_pose(robot_id):
        return NS(camera_x=camera_pose[0] if camera_pose else None, camera_y=camera_pose[1] if camera_pose else None)

    live = NS(open=True, view={"robot_id": "pinky", "trip_id": "trip", "hold": None, "lease": {"state": HELD},
                               "detail": {"named_stop_operation": {"run_id": RUN}}})
    runner = NS(config=TripConfig(cell_topview_corrections=corrections), check_named_correction=check,
                auto_named_correction=core, map_pose=map_pose, cell_topview=topview, _clock=lambda: 50.0)
    return runner, live


def evaluate(runner, live, snapshot=None):
    return asyncio.run(evaluate_named_stop(runner, live, EVIDENCE, PLACE_DATA, FIT, snapshot or state()))


def test_an_offset_stop_is_corrected_from_the_camera_then_confirmed_without_the_ceiling_camera():
    core = Core()
    runner, live = rig(FakeTopview(obs(-0.02, 0.04, 0.0), obs(0.003, 0.002, 0.0)), core)
    first = evaluate(runner, live)  # no ceiling sighting at all: the top view is its own evidence
    assert first["source"] == "cell_topview" and first["decision"] == "REPARK" and first["auto_repark"] == "dispatched"
    (clearance,) = core.posts
    assert clearance.left_m == pytest.approx(0.04, abs=1e-3) and clearance.forward_m == pytest.approx(-0.02, abs=1e-3)
    reads = runner.cell_topview.calls
    assert evaluate(runner, live)["auto_repark"] == "running" and runner.cell_topview.calls == reads  # no re-read mid-move
    core.armed_now = False
    done = evaluate(runner, live)
    assert done["decision"] == "IN_TOLERANCE" and done["source"] == "cell_topview" and len(core.posts) == 1
    assert _aligned(live, PLACE_DATA, FIT, state(), runner._clock) is True  # the confirmation reads the same verdict


def test_the_loop_stops_at_the_configured_number_of_corrections():
    core = Core()
    runner, live = rig(FakeTopview(obs(0.0, 0.04, 0.0)), core, corrections=2)
    for expected in (1, 2):
        assert evaluate(runner, live)["auto_repark"] == "dispatched" and len(core.posts) == expected
        core.armed_now = False
    held = evaluate(runner, live)
    assert (held["decision"], held["reason"]) == ("HOLD", "auto_correction_limit") and len(core.posts) == 2


def test_a_move_past_core_limits_makes_no_call():
    core = Core()
    runner, live = rig(FakeTopview(obs(0.0, 0.08, 0.0)), core)
    assert evaluate(runner, live)["reason"] == "outside_repark_limits" and not core.posts


@pytest.mark.parametrize("failure, reason", [(tp.TopviewError("camera_unreachable"), "camera_unreachable"),
                                             (tp.TopviewError("frame_stale"), "frame_stale"),
                                             (tp.TopviewError("registration_too_few_inliers"), "registration_too_few_inliers"),
                                             (RuntimeError("vision blew up"), "topview_RuntimeError"),
                                             (KeyError("X-Frame-Seq"), "topview_KeyError")])
def test_no_camera_evidence_keeps_the_unchanged_slam_verdict(failure, reason):
    core = Core()
    runner, live = rig(FakeTopview(failure), core)
    live.view["detail"][nt.KEY] = {"stale": "record"}
    result = evaluate(runner, live)  # the robot's own pose is on target
    assert result["decision"] == "IN_TOLERANCE" and result["topview_unavailable"] == reason and "source" not in result
    assert nt.KEY not in live.view["detail"] and not core.posts
    short = evaluate(runner, live, state(pose={"x": 1.04, "y": 0.5, "yaw": math.pi}))  # SLAM: 4 cm short
    assert (short["decision"], short["reason"]) == ("HOLD", "camera_sighting_required")  # the old rules, unchanged
    assert short["topview_unavailable"] == reason and not core.posts


def test_a_robot_the_camera_sees_turned_around_is_no_evidence():
    core = Core()
    runner, live = rig(FakeTopview(obs(0.0, 0.04, 0.0)), core)  # the undirected tray axis reads "on heading"
    result = evaluate(runner, live, state(pose={"x": 1.0, "y": 0.5, "yaw": 0.0}))  # the robot itself says it faces +x
    assert result["topview_unavailable"] == "heading_disagrees_with_pose" and not core.posts and "source" not in result


def test_a_stop_the_camera_does_not_cover_never_reads_it():
    core = Core()
    runner, live = rig(FakeTopview(obs(0.0, 0.04, 0.0)), core)
    other = {**PLACE_DATA, "id": "S4"}
    asyncio.run(evaluate_named_stop(runner, live, EVIDENCE, other, FIT, state()))
    assert runner.cell_topview.calls == 0 and not core.posts


def test_the_confirmation_needs_the_verdict_young_and_the_robot_still():
    pose = state()["pose"]
    live = NS(view={"detail": {nt.KEY: {"place": "S3", "decision": {"decision": "IN_TOLERANCE"}, "read_at": 50.0,
                                          "pose": pose}}})
    assert _aligned(live, PLACE_DATA, FIT, state(), lambda: 52.0) is True
    assert _aligned(live, PLACE_DATA, FIT, state(), lambda: 70.0) is False
    assert _aligned(live, PLACE_DATA, FIT, state(pose={**pose, "y": 0.52}), lambda: 52.0) is False
    live.view["detail"][nt.KEY]["decision"] = {"decision": "REPARK"}
    assert _aligned(live, PLACE_DATA, FIT, state(), lambda: 52.0) is False
    live.view["detail"][nt.KEY] = {"place": "S4", "decision": {"decision": "REPARK"}, "read_at": 50.0, "pose": pose}
    assert _aligned(live, PLACE_DATA, FIT, state(), lambda: 52.0) is True  # an S4 record is ignored: SLAM says on target


def test_the_sideways_move_is_part_of_the_clearance_and_the_corridor_endpoint():
    assert correction_endpoint({"pose": {"x": 1.0, "y": 0.0, "yaw": 0.0}}, 0.02, 0.03) == pytest.approx((1.02, 0.03))
    assert correction_endpoint({"pose": {"x": 0.0, "y": 0.0, "yaw": math.pi / 2}}, 0.0, 0.03) == pytest.approx((-0.03, 0.0))
    with pytest.raises(HubError):  # below the 5 mm resolution, or past the sideways cap
        correction_endpoint({"pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}}, 0.0, 0.004)
    with pytest.raises(HubError):
        correction_endpoint({"pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}}, 0.0, REPARK_MAX_LEFT_M + 0.01)


def test_clearance_left_move_is_bounded_and_defaults_to_straight():
    base = dict(nav_run_id=RUN, map_sha256="a" * 64, forward_m=0.02, site_end=(1.0, 0.5), cable_and_path_clear=True)
    assert CorrectionClearance(**base).left_m == 0.0
    assert CorrectionClearance(**base, left_m=REPARK_MAX_LEFT_M).left_m == REPARK_MAX_LEFT_M
    with pytest.raises(ValidationError):
        CorrectionClearance(**base, left_m=REPARK_MAX_LEFT_M + 0.01)


def test_the_top_view_stop_is_exempt_from_lane_realign():
    from test_trip_lane_realign import Rig
    rig_ = Rig("loop_right:fwd")  # ends at S3
    rig_.runner.cell_topview = NS(covers=lambda place: place == "S3")
    for _ in range(3):
        replace, record = rig_.tick(0.08, 0.06)
        assert not replace and record["kind"] == "excluded" and not record["slow"]
    plain = Rig("loop_right:fwd")
    plain.tick(0.08, 0.06)
    assert plain.tick(0.08, 0.06)[1]["kind"] != "excluded"
    leaving = Rig("upper_east:fwd")  # starts at S3: the way out stays watched
    leaving.runner.cell_topview = NS(covers=lambda place: place == "S3")
    leaving.tick(0.08, 0.06)
    assert leaving.tick(0.08, 0.06)[1]["kind"] != "excluded"


def test_the_operator_script_makes_a_valid_s3_precision_stop_without_touching_other_places():
    import importlib.util
    import json
    from test_trip_nav2_route import _south_loop_map
    spec = importlib.util.spec_from_file_location("s3_topview_script", ROOT / "tools/ops/s3_topview_precision_stop.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    raw = json.loads(_south_loop_map().model_dump_json(by_alias=True))
    others = [p for p in raw["places"] if p["id"] != "S3"]
    out = script.apply_precision_stop(raw, json.loads(DATA_FILE.read_text(encoding="utf-8")))
    from fleet.site_map import SiteMap
    placed = next(p for p in SiteMap.model_validate(out).places if p.id == "S3")
    assert placed.pinned and placed.precision_stop.reference_pose == (placed.x, placed.y, placed.yaw)
    assert (placed.x, placed.y) == pytest.approx((0.751, -0.252)) and placed.yaw == pytest.approx(math.pi + 0.0334 - math.tau, abs=1e-3) and placed.precision_stop.max_correction_m == 0.05
    assert [p for p in out["places"] if p["id"] != "S3"] == others
