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
        for a, b in zip(frames, frames[1:]):
            assert max(abs(u - v) for u, v in zip(a[:5], b[:5])) <= m.MAX_STEP


def test_an_unreachable_target_is_refused_before_any_chunk_exists():
    plan = dict(PLAN, pick=dict(PLAN["pick"], x=0.30, y=0.20))
    with pytest.raises(SystemExit, match="IK"):
        m.Planner(plan).library()
