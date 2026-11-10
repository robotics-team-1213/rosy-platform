"""Tests for Unified AreaXYZ Coordinate System and ROSY Middleware -> rosy-cell Directive Execution (D-1014)."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "middleware/devices/omx/adapter", ROOT / "deploy/robot/omx"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from omx_adapter.area_xyz import AREA_XYZ_SCHEMA, DIRECTIVE_SCHEMA, build_directive, resolve_area_xyz  # noqa: E402
import cell_area_xyz  # noqa: E402

SAMPLE_BASE_PLAN = {
    "fps": 30,
    "home": [0.76, -62.25, 52.92, 51.7, 44.71],
    "grip_closed": 48.8,
    "grip_open": 58.2,
    "grip_release": 57.6,
    "hold_current_ma": 93,
    "transit_speed": 0.82,
    "descend_pick_guard_frac": 0.30,
    "descend_place_guard_frac": 0.26,
    "tcp_x_m": 0.0885,
    "limits": {
        "joints_rad": {
            "joint1": [-3.14, 3.14],
            "joint2": [-2.05, 1.57],
            "joint3": [-1.57, 1.53],
            "joint4": [-1.8, 2.0],
            "joint5": [-3.14, 3.14],
        },
        "workspace_min_m": [-0.05, -0.24, 0.005],
        "workspace_max_m": [0.26, 0.24, 0.145],
        "singularity_radius_m": 0.03,
    },
}


def test_resolve_area_xyz_unifies_slot_and_explicit_coordinates_across_tiers():
    t1 = resolve_area_xyz("pallet", col=1, row=1, tier=1)
    t2 = resolve_area_xyz("pallet", col=3, row=1, tier=2)
    t3 = resolve_area_xyz("pallet", col=2, row=1, tier=3, x=0.1580, y=-0.0130, z=0.0674)

    assert t1["schema"] == AREA_XYZ_SCHEMA
    assert t1["site_id"] == "pallet-l0"
    assert t1["effective_xyz_m"] == [0.128, -0.012, 0.0074]

    assert t2["site_id"] == "pallet-l1"
    assert t2["effective_xyz_m"] == [0.1988, -0.003, 0.0398]

    assert t3["site_id"] == "pallet-l2"
    assert t3["tier"] == 3
    assert t3["effective_xyz_m"] == [0.158, -0.013, 0.0674]

    with pytest.raises(ValueError):
        resolve_area_xyz("pallet", x=0.45, y=0.0, z=0.02)


def test_middleware_directive_executes_on_cell_and_stacks_tier3_with_autocal(tmp_path: Path):
    directive = build_directive(
        arm_id="arm_b",
        pick={"area": "pallet", "col": 3, "row": 1, "tier": 2, "x": 0.1935, "y": -0.0030, "z": 0.0398},
        place={"area": "pallet", "col": 2, "row": 1, "tier": 3, "x": 0.1580, "y": -0.0130, "z": 0.0674},
        directive_id="test-tier3-stack",
        vision_refine=False,
    )
    assert directive["schema"] == DIRECTIVE_SCHEMA
    assert directive["pick"]["tier"] == 2
    assert directive["place"]["tier"] == 3

    grasp_calls = 0

    def fake_act(cmd: str):
        nonlocal grasp_calls
        if cmd == "run grasp_pick":
            grasp_calls += 1
            if grasp_calls == 1:
                # Attempt 1: skewed/wedged grasp at 56.9 units -> triggers reinsert_and_retry
                return {"ok": True, "holding": True, "state": [0.0, -10.0, 15.0, 45.0, 41.0, 56.9], "gripper_current_ma": 150.0}
            # Attempt 2: centered stable grasp at 54.36 units -> proceeds and updates arm-cal-arm_b.json
            return {"ok": True, "holding": True, "state": [0.0, -10.0, 15.0, 45.0, 41.0, 54.36], "gripper_current_ma": 172.0}
        return {"ok": True, "holding": True, "state": [0.0, -10.0, 15.0, 45.0, 41.0, 54.36], "gripper_current_ma": 120.0}

    res = cell_area_xyz.execute_directive(
        directive,
        base_plan=SAMPLE_BASE_PLAN,
        work_dir=tmp_path,
        act_fn=fake_act,
        max_attempts=2,
    )
    assert res["result"] == "placed"
    assert res["place"]["effective_xyz_m"][2] == 0.0674
    assert res["calibration"]["samples"] == 1
    assert (tmp_path / "arm-cal-arm_b.json").exists()
    cmds = [s["command"] for s in res["steps"]]
    assert "run release_pick" in cmds
    assert "run descend_place" in cmds
    assert "run release_place" in cmds


def test_empty_grasp_recovery_lowers_z_and_verify_stack_outcome_checks_side_camera(tmp_path: Path):
    import numpy as np

    directive = build_directive(
        arm_id="arm_b",
        pick={"area": "pallet", "col": 3, "row": 1, "tier": 2, "x": 0.2045, "y": -0.0030, "z": 0.0398},
        place={"area": "pallet", "col": 2, "row": 1, "tier": 3, "x": 0.1580, "y": -0.0130, "z": 0.0674},
        directive_id="test-empty-recover-verify",
        vision_refine=False,
    )
    grasp_calls = 0

    def fake_act(cmd: str):
        nonlocal grasp_calls
        if cmd == "run grasp_pick":
            grasp_calls += 1
            if grasp_calls == 1:
                # Attempt 1: jaws close in thin air above the container (52.65 units, 55 mA, holding=False)
                return {"ok": True, "holding": False, "state": [0.0, 5.79, 2.56, 40.76, 47.06, 52.65], "gripper_current_ma": 55.0}
            # Attempt 2 (after recovery lowered z and adjusted x to 0.1988): solid grasp at 54.35 units, 168 mA
            return {"ok": True, "holding": True, "state": [0.0, 5.9, 3.1, 40.2, 47.0, 54.35], "gripper_current_ma": 168.0}
        return {"ok": True, "holding": True, "state": [0.0, 5.9, 3.1, 40.2, 47.0, 54.35], "gripper_current_ma": 115.0}

    frame_calls = 0

    def fake_frame(cam: str):
        nonlocal frame_calls
        img = np.full((480, 640, 3), (180, 180, 180), dtype=np.uint8)
        if cam == "side":
            frame_calls += 1
            if frame_calls == 1:
                # Before pick: Col 3 Tier 2 (295..368, 182..250) has orange container
                img[182:250, 295:368] = (30, 120, 240)
            else:
                # After place: Col 3 Tier 2 is vacated, Col 2 Tier 3 (225..292, 114..182) has orange container
                img[114:182, 225:292] = (30, 120, 240)
        return img

    res = cell_area_xyz.execute_directive(
        directive,
        base_plan=SAMPLE_BASE_PLAN,
        work_dir=tmp_path,
        act_fn=fake_act,
        frame_fn=fake_frame,
        max_attempts=3,
    )
    assert res["result"] == "placed"
    assert res["task_verified"] is True
    assert res["verification"]["verified"] is True
    assert len(res["recovery"]) == 1
    assert res["pick"]["x"] == 0.1988
    assert res["pick"]["z"] < 0.0398

