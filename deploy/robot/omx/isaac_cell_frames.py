#!/usr/bin/env python3
"""Arm S chunk frames for the Isaac cell (learning/envs/isaac/arm_s_cell_fixture.py), one file per scenario.

The real cell's plan (home, transit height, limits; grasp-plan.example.json) aims the same top-down chunks
and rise-turn-descend travel at the Isaac cell's box and place point; every 30 fps frame is kept (no
thinning) so Isaac replays exactly what chunk_runner would stream. Body joints in radians, the gripper in
the Isaac CAD gripper's radians (open 1.0; closed -0.12, a force-limited squeeze that stops on the box).

  isaac_cell_frames.py --scenario overhang --out frames-overhang.json
  isaac_cell_frames.py --case case.json --out frames-case.json   (a case from cell_cases.py)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from grasp_planner import NAMES, Planner, norm_to_rad  # noqa: E402
from sim_chunk_plan import phases as chunk_phases, sim_plan  # noqa: E402

SCHEMA = "rosy.omx-isaac-cell-frames.v1"
JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1")
GRASP_DEPTH, RELEASE_DZ = 0.015, 0.004


def fixture():
    path = HERE.parents[2] / "learning/envs/isaac/arm_s_cell_fixture.py"
    spec = importlib.util.spec_from_file_location("arm_s_cell_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frames_for(scenario, plan: dict | None = None) -> dict:
    """``scenario``: a fixture scenario name, or a case dict (``arm_s_cell_fixture.check_case``)."""
    f = fixture()
    case = f.spec(scenario)
    plan = plan or json.loads((HERE / "grasp-plan.example.json").read_text())
    (bx, by, _), yaw = f.box_start(scenario)
    ax, ay = case.get("aim", (0.0, 0.0))  # the pick aimed off the box, as a map or arm error would aim it
    px, py, top = f.place_point(scenario)
    on_belt = case["place"] == "belt"
    grasp_z = f.TRAY["top"] + f.BOX - GRASP_DEPTH
    site_yaw = math.radians(plan["pick"]["yaw_deg"] + case["grasp_turn"])  # the site's yaw, turned by the case
    place_yaw = math.radians(plan["place"]["yaw_deg"] if on_belt else plan["pick"]["yaw_deg"])
    transit = {NAMES.index(k): v for k, v in plan["transit"].items()}
    transit_q = [norm_to_rad(transit.get(i, plan["home"][i])) for i in range(5)]
    arm = sim_plan(home_q=[norm_to_rad(v) for v in plan["home"]], transit_q=transit_q,
                   pick=(bx + ax, by + ay, grasp_z, site_yaw), place=(px, py, top + f.BOX - GRASP_DEPTH + RELEASE_DZ, place_yaw),
                   approach_m=plan["approach_m"], grip_open=f.FIXTURE["gripper_open_rad"],
                   grip_close=f.FIXTURE["gripper_closed_rad"], limits=plan["limits"], fps=f.FIXTURE["frame_fps"])
    phases = chunk_phases(Planner(arm), JOINTS, "gripper_joint_1", 0.0)  # step 0: keep every frame
    return {"schema": SCHEMA, "scenario": scenario if isinstance(scenario, str) else "case",
            **({} if isinstance(scenario, str) else {"case": case}), "fps": f.FIXTURE["frame_fps"], "joints": list(JOINTS),
            "fixture_revision": f.FIXTURE["revision"], "box_start_m": [bx, by], "box_yaw_deg": yaw,
            "start": list(phases[0].start_state_positions),
            "phases": [{"phase_id": p.phase_id, "frames": [list(q.positions) for q in p.points]} for p in phases]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--scenario", choices=sorted(fixture().SCENARIOS))
    which.add_argument("--case", type=Path, help="a case JSON from cell_cases.py")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    value = frames_for(args.scenario or json.loads(args.case.read_text()))
    args.out.write_text(json.dumps(value))
    print(json.dumps({"out": str(args.out), "frames": sum(len(p["frames"]) for p in value["phases"])}))


if __name__ == "__main__":
    main()
