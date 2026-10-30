"""Top-down pick/place chunks: vertical tool, straight vertical moves, still jaws while closing, no wrist twist."""
import importlib.util
import json
import math
from pathlib import Path
import sys

import pytest

pytest.importorskip("yaml")
ROOT = Path(__file__).parents[1]
OMX = ROOT / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("grasp_planner", OMX / "grasp_planner.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.remove(str(OMX))

PLAN = json.loads((OMX / "grasp-plan.example.json").read_text())


@pytest.fixture(scope="module")
def planned():
    planner = m.Planner(PLAN)
    return planner, planner.library()


def fk(planner, frame):
    return planner.kin.fk([m.norm_to_rad(v) for v in frame[:5]])


def test_unit_conversion_round_trips_and_keeps_tick_2048_at_zero():
    assert m.rad_to_norm(0.0) == pytest.approx(0.0244, abs=1e-3)  # tick 2048 sits just above the 0..4095 middle
    for rad in (-2.0, -0.5, 0.3, 1.9):
        assert m.norm_to_rad(m.rad_to_norm(rad)) == pytest.approx(rad, abs=1e-6)


def test_every_frame_keeps_the_tool_vertical_and_the_moves_straight(planned):
    planner, library = planned
    for name in ("descend_pick", "lift_pick", "descend_place", "lift_place"):
        poses = [fk(planner, f) for f in library["chunks"][name]]
        assert all(p.tool_down_error_rad < math.radians(1.5) for p in poses), name
        xs, ys, zs = ([getattr(p, a) for p in poses] for a in "xyz")
        assert max(xs) - min(xs) < 0.002 and max(ys) - min(ys) < 0.002, name  # straight up or down
        assert (zs[-1] < zs[0]) is name.startswith("descend"), name


def test_the_jaws_move_only_while_the_arm_stands_still(planned):
    _, library = planned
    for name, closing in (("grasp_pick", True), ("release_place", False)):
        frames = library["chunks"][name]
        assert all(f[:5] == frames[0][:5] for f in frames), name
        grips = [f[5] for f in frames]
        assert (grips[-1] < grips[0]) is closing and grips[-1] in (PLAN["grip_closed"], PLAN["grip_open"])


def test_no_wrist_twist_and_no_base_sweep_within_a_site(planned):
    _, library = planned
    for site in ("pick", "place"):
        frames = [f for k in ("above", "descend", "lift") for f in library["chunks"][f"{k}_{site}"]]
        assert max(f[0] for f in frames) - min(f[0] for f in frames) < 0.5  # base fixed
        assert max(f[4] for f in frames) - min(f[4] for f in frames) < 0.5  # wrist roll fixed


def test_the_grasp_chunk_is_judged_by_the_runner_and_steps_stay_small(planned):
    _, library = planned
    assert "grasp_pick" in library["chunks"] and library["hold_current_ma"] == PLAN["hold_current_ma"]
    for frames in library["chunks"].values():
        assert not m.too_fast(frames, PLAN["fps"])  # the guard streams at GUARD_UNITS_PER_S


def test_the_cycle_trajectory_is_a_valid_recordable_a_b_replay(tmp_path):
    sys.path.insert(0, str(OMX))
    try:
        trajectory = m.Planner(PLAN).cycle_trajectory()
        teach = importlib.import_module("teach_trajectory")
    finally:
        sys.path.remove(str(OMX))
    path = tmp_path / "cycle.json"
    path.write_text(json.dumps(trajectory))
    loaded = teach.load(path, fps=PLAN["fps"])  # what record_session --replay checks before the arm moves
    a, reset, b = (loaded["segments"][k] for k in ("A", "reset", "B"))
    assert a[1] - a[0] == b[1] - b[0] and reset[1] > reset[0]
    frames = loaded["frames"]
    assert not m.too_fast(frames, PLAN["fps"])
    assert frames[0][:5] == pytest.approx(PLAN["home"], abs=0.5) and frames[-1][:5] == pytest.approx(PLAN["home"], abs=0.01)
    assert loaded["source"]["planner"].startswith("grasp_planner")


def test_an_unreachable_target_is_refused_before_any_chunk_exists():
    plan = dict(PLAN, pick=dict(PLAN["pick"], x=0.30, y=0.20))
    with pytest.raises(SystemExit, match="IK"):
        m.Planner(plan).library()


def test_the_release_lifts_by_its_own_height_while_the_pick_keeps_a_low_lift():
    planner = m.Planner(dict(PLAN, lift_m=0.03, release_lift_m=0.07))
    lib = planner.library()
    rise = lambda name: fk(planner, lib["chunks"][name][-1]).z - fk(planner, lib["chunks"][name][0]).z  # noqa: E731
    assert rise("lift_pick") == pytest.approx(0.03, abs=0.002)
    assert rise("lift_place") == pytest.approx(0.07, abs=0.002)  # 3 cm let the park's closing jaws retake the box


def test_a_far_target_keeps_its_grasp_and_travel_ends_where_the_arm_still_has_margin():
    """2026-10-26: a container 0.24 m out was graspable top-down; only the 7 cm lift point above it was not."""
    far = dict(PLAN["pick"], x=0.078, y=0.229, z=0.050)
    planner = m.Planner(dict(PLAN, pick=far))
    library = planner.library()
    reach = library["source"]["reach"]["pick"]
    assert m.MIN_STANDOFF_M <= reach["approach_m"] < PLAN["approach_m"] + 1e-6 and reach["margin_m"] > 0
    grasp = fk(planner, library["chunks"]["descend_pick"][-1])
    assert math.dist((grasp.x, grasp.y, grasp.z), (far["x"], far["y"], far["z"])) < 0.002
    lifted = fk(planner, library["chunks"]["lift_pick"][-1])
    assert planner.reach_margin(lifted.x, lifted.y, lifted.z, far["yaw_deg"]) >= m.REACH_MARGIN_M - 1e-4
    assert lifted.z - far["z"] >= m.MIN_STANDOFF_M - 0.002, "it still lifts clear of the tray"


def test_a_path_past_the_keep_out_line_is_refused_before_any_chunk_exists():
    with pytest.raises(SystemExit, match="keep_out"):
        m.Planner(dict(PLAN, keep_out={"x_max_m": 0.10})).library()
    assert m.Planner(dict(PLAN, keep_out={"x_max_m": 0.30})).library()["chunks"]


def test_keep_out_counts_the_gripper_body_not_only_the_tool_tip():
    """2026-10-27: the TCP stayed 2 cm inside the line while the wrist and gripper hit the wall behind the belt."""
    planner = m.Planner(PLAN)
    library = planner.library()
    tip = max(fk(planner, f).x for frames in library["chunks"].values() for f in frames)
    with pytest.raises(SystemExit, match="wrist or gripper"):
        m.Planner(dict(PLAN, keep_out={"x_max_m": round(tip + m.BODY_MARGIN_M / 2, 3)})).library()


def test_a_lift_the_wrist_cannot_reach_is_shortened_inside_the_joint_limit():
    """2026-10-27: the arm S wrist stops at 1.89 rad; a 7 cm top-down lift needed more and ran into it."""
    planner = m.Planner(PLAN)
    library = planner.library()
    top = PLAN["limits"]["joints_rad"]["joint4"][1]
    q4 = [m.norm_to_rad(f[3]) for frames in library["chunks"].values() for f in frames]
    assert max(q4) <= top + 1e-3
    wide = m.Planner(dict(PLAN, limits=dict(PLAN["limits"], joints_rad=dict(PLAN["limits"]["joints_rad"], joint4=[-0.3, 2.3]))))
    lifted = lambda p: p.height(p.library()["chunks"]["lift_pick"][-1])
    assert lifted(planner) <= lifted(wide) + 1e-6
