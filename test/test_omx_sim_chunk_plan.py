"""pick-place-chunks: arm S's chunk plan becomes the SIM teacher's four phases, aimed at the sim targets."""
import importlib.util
import json
import math
from pathlib import Path
import sys

import pytest

pytest.importorskip("yaml")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("sim_chunk_plan", OMX / "sim_chunk_plan.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    import grasp_planner
finally:
    sys.path.remove(str(OMX))

LIMITS = json.loads((OMX / "grasp-plan.example.json").read_text())["limits"]
NAMES = ("joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1")
PICK, PLACE = (0.16, 0.08, 0.03, 0.0), (0.16, -0.08, 0.035, 0.0)
GRIP_CLOSE, STEP = 0.4, 0.03


@pytest.fixture(scope="module")
def planned():
    probe = grasp_planner.Planner({"fps": 30, "limits": LIMITS})
    home_q = probe.solve(0.12, 0.0, 0.12, 0.0, 0.0)
    transit_q = probe.solve(0.12, 0.0, 0.14, 0.0, home_q[4])
    plan = m.sim_plan(home_q=home_q, transit_q=transit_q, pick=PICK, place=PLACE,
                      grip_open=1.0, grip_close=GRIP_CLOSE, limits=LIMITS)
    planner = grasp_planner.Planner(plan)
    return planner, m.phases(planner, NAMES, "gripper_joint_1", STEP)


def tcp(planner, q):
    return planner.kin.fk(list(q[:5]))


def test_the_four_phases_run_in_the_teacher_order_and_each_starts_where_the_last_ended(planned):
    _, phases = planned
    assert tuple(p.phase_id for p in phases) == m.PHASES
    for before, after in zip(phases, phases[1:]):
        assert after.start_state_positions == before.points[-1].positions
    for phase in phases:  # thinned, so the teacher's 0.8 s per target stays bounded, but never coarser than a step
        path = [phase.start_state_positions, *[p.positions for p in phase.points]]
        assert max(max(abs(a - b) for a, b in zip(p, q)) for p, q in zip(path, path[1:])) <= STEP + 0.01
    assert phases[-1].points[-1].positions == pytest.approx(phases[0].start_state_positions, abs=1e-3)  # back home


def test_the_grasp_and_release_happen_at_the_sim_targets_with_the_width_matched_close(planned):
    planner, (approach, grasp, transfer, release) = planned
    at_pick, at_place = tcp(planner, approach.points[-1].positions), tcp(planner, transfer.points[-1].positions)
    assert math.dist((at_pick.x, at_pick.y, at_pick.z), PICK[:3]) < 0.002
    assert math.dist((at_place.x, at_place.y, at_place.z), PLACE[:3]) < 0.002
    above = len(approach.points) - len(planner.library()["chunks"]["descend_pick"])
    assert {p.positions[5] for p in approach.points[above:]} == {1.0}  # open from above the box down
    assert grasp.points[-1].positions[5] == pytest.approx(GRIP_CLOSE)  # never the full close
    assert all(p.positions[5] == pytest.approx(GRIP_CLOSE) for p in transfer.points)
    body = [p.positions[:5] for p in grasp.points]
    assert max(abs(a - b) for q in body for a, b in zip(q, body[0])) < 1e-9  # the arm is still while it closes


def test_travel_between_sites_rises_before_it_turns(planned):
    planner, (_, _, transfer, _) = planned
    path = [p.positions for p in transfer.points]
    turning = [i for i, (p, q) in enumerate(zip(path, path[1:])) if abs(q[0] - p[0]) > 1e-6]
    assert turning and min(tcp(planner, path[i]).z for i in turning) > PICK[2] + 0.03


def test_the_release_opens_from_where_the_jaws_stopped_on_the_box(planned):
    _, (*_, release) = planned
    held = GRIP_CLOSE + 0.02  # the box keeps the jaws a little wider than the width-matched close
    assert release.points[0].positions[5] < held  # as planned, the first release target would close further
    opened = m.open_from(release, "gripper_joint_1", held)
    assert min(p.positions[5] for p in opened.points) >= held and opened.start_state_positions[5] == held
    assert opened.points[-1].positions[5] == release.points[-1].positions[5] == pytest.approx(1.0)
    assert [p.positions[:5] for p in opened.points] == [p.positions[:5] for p in release.points]


def test_the_sim_keeps_the_real_plans_motion_values_and_only_moves_the_sites(planned):
    planner, _ = planned
    real = json.loads(m.REAL_PLAN.read_text())
    assert {k: planner.plan[k] for k in m.MOTION if k in real} == {k: real[k] for k in m.MOTION if k in real}
    assert "keep_out" not in planner.plan  # the real cell's wall is not a motion value


def test_the_sim_replays_frame_for_frame_what_chunk_runner_streams():
    """Oracle: chunk_runner's own goto (transit_path from the held target, library transit, gripper_closed and
    transit_speed) around the library's chunks, built here without Planner.stream."""
    probe = grasp_planner.Planner({"fps": 30, "limits": LIMITS})
    home_q = probe.solve(0.12, 0.0, 0.12, 0.0, 0.0)
    transit_q = probe.solve(0.12, 0.0, 0.14, 0.0, home_q[4])
    real = dict(json.loads(m.REAL_PLAN.read_text()), transit_speed=0.5)
    planner = grasp_planner.Planner(m.sim_plan(home_q=home_q, transit_q=transit_q, pick=PICK, place=PLACE,
                                               grip_open=1.0, grip_close=GRIP_CLOSE, limits=LIMITS, real=real))
    library = planner.library()
    sys.path.insert(0, str(OMX))
    try:
        from chunk_runner import NAMES as RUNNER_NAMES, transit_path
    finally:
        sys.path.remove(str(OMX))
    transit = {RUNNER_NAMES.index(k): float(v) for k, v in library["transit"].items()}
    goto = lambda held, chunk: transit_path(held, chunk[0], library["gripper_closed"], library["fps"],  # noqa: E731
                                            transit, library["transit_speed"])
    c, home = library["chunks"], list(planner.plan["home"]) + [planner.plan["grip_open"]]
    streamed = goto(home, c["above_pick"]) + c["descend_pick"] + c["grasp_pick"] + c["lift_pick"]
    streamed += goto(streamed[-1], c["above_place"]) + c["descend_place"] + c["release_place"] + c["lift_place"]
    streamed += goto(streamed[-1], [home])
    phases = m.phases(planner, NAMES, "gripper_joint_1", 0.0)
    replayed = [p.positions for phase in phases for p in phase.points]
    expected = [tuple(grasp_planner.norm_to_rad(v) for v in f[:5]) + (f[5] / 100,) for f in streamed]
    assert library["transit_speed"] == 0.5 and len(replayed) == len(expected)
    assert all(a == pytest.approx(b, abs=1e-12) for a, b in zip(replayed, expected))
