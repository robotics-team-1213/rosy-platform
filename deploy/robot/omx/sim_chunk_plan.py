"""pick-place-chunks (D-872 §2.4): arm S's chunk plan as the native SIM teacher's four phases.

grasp_planner builds the same top-down chunks the real cell runs (vertical descend, close, vertical
lift) and chunk_runner.transit_path the same rise-turn-descend travel; here they are aimed at the sim
cell's pick and place and handed to sim_pick_place_teacher in place of plan_transfer, so the sim's
owner, contact checks, attach/detach and judge_episode judge arm S's motion strategy. Body joints use
the plan's LeRobot units (tick 2048 = 0 rad, full 0..4095 range); the gripper unit is rad x 100, so
grip_open 100 = 1.0 rad and the grasp closes to the cell's width-matched target, never full close.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

from chunk_runner import transit_path
from grasp_planner import NAMES, Planner, norm_to_rad, rad_to_norm

PHASES = ("approach", "grasp", "transfer", "release")  # manipulation_plan.MOTION_PHASES
REAL = {"descend_m_s": 0.020, "lift_m_s": 0.030, "grip_s": 1.5, "settle_s": 0.5}  # grasp-plan.example.json


def sim_plan(*, home_q, transit_q, pick, place, approach_m, grip_open, grip_close, limits, fps=30) -> dict:
    """home_q/transit_q: joint1..5 rad; pick/place: (x, y, z, yaw_rad) of the grasp TCP; grips in rad."""
    def site(pose):
        x, y, z, yaw = pose
        return {"x": x, "y": y, "z": z, "yaw_deg": math.degrees(yaw)}

    return {"fps": fps, "home": [round(rad_to_norm(q), 3) for q in home_q], "pick": site(pick),
            "place": site(place), "approach_m": approach_m, "lift_m": approach_m, **REAL,
            "grip_open": round(grip_open * 100, 3), "grip_closed": round(grip_close * 100, 3),
            "transit": {name: round(rad_to_norm(transit_q[i]), 3)
                        for i, name in ((1, "shoulder_lift.pos"), (2, "elbow_flex.pos"), (3, "wrist_flex.pos"))},
            "limits": limits}


def thin(frames, step):
    """Keep a frame once it is `step` away from the last kept one, and the last frame: the teacher's
    short_targets interpolates between kept frames in steps of at most `step` again."""
    kept = [frames[0]]
    for frame in frames[1:-1]:
        if max(abs(a - b) for a, b in zip(frame, kept[-1])) >= step:
            kept.append(frame)
    return kept + ([frames[-1]] if len(frames) > 1 else [])


def phases(planner: Planner, joint_names, gripper_joint, step) -> list:
    p, c = planner.plan, planner.library()["chunks"]
    fps, opened, closed = planner.fps, p["grip_open"], p["grip_closed"]
    transit = {NAMES.index(k): float(v) for k, v in p["transit"].items()}
    home = list(p["home"]) + [opened]
    travel = lambda start, goal, grip: transit_path(start, goal, grip, fps, transit)  # noqa: E731
    approach = travel(home, c["above_pick"][0], opened) + c["descend_pick"]
    grasp = c["grasp_pick"]
    transfer = c["lift_pick"] + travel(c["lift_pick"][-1], c["above_place"][0], closed) + c["descend_place"]
    release = c["release_place"] + c["lift_place"] + travel(c["lift_place"][-1], home, opened)
    order = list(joint_names)
    index = {**{f"joint{i + 1}": i for i in range(5)}, gripper_joint: 5}

    def rad(frame):
        values = [norm_to_rad(v) for v in frame[:5]] + [frame[5] / 100]
        return tuple(values[index[n]] for n in order)

    result, start = [], rad(home)
    for phase_id, frames in zip(PHASES, (approach, grasp, transfer, release)):
        points = thin([rad(f) for f in frames], step)
        result.append(SimpleNamespace(phase_id=phase_id, joint_names=tuple(order), start_state_positions=start,
                                      points=tuple(SimpleNamespace(positions=q) for q in points)))
        start = points[-1]
    return result


def open_from(phase, gripper_joint, position):
    """The release phase opens from where the jaws stopped on the box: planned values below the measured
    position would command a close the box blocks (2026-10-25 sim: 0.387 rad asked, 0.420 held, no progress)."""
    i = phase.joint_names.index(gripper_joint)
    fix = lambda q: tuple(max(v, position) if k == i else v for k, v in enumerate(q))  # noqa: E731
    return SimpleNamespace(phase_id=phase.phase_id, joint_names=phase.joint_names,
                           start_state_positions=fix(phase.start_state_positions),
                           points=tuple(SimpleNamespace(positions=fix(p.positions)) for p in phase.points))
