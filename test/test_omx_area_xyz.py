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


def test_target_zone_deviation_triggers_failure_and_recovery_mode():
    import numpy as np

    before_side = np.full((480, 640, 3), (180, 180, 180), dtype=np.uint8)
    # Col 1 Tier 1 (155..220, 252..315) occupied before pick
    before_side[252:315, 155:220] = (30, 120, 240)

    # Case 1: Container never left source zone -> verified=False, recovery_mode="re_pick_and_re_place"
    after_unmoved = before_side.copy()
    v1 = cell_area_xyz.verify_stack_outcome(
        before_side=before_side,
        after_side=after_unmoved,
        pick={"col": 1, "tier": 1},
        place={"col": 2, "tier": 3},
    )
    assert v1["verified"] is False
    assert v1["recovery_mode"] == "re_pick_and_re_place"

    # Case 2: Source vacated and container landed inside Col 2 Tier 3 zone (226..292, 120..195) -> verified=True
    after_placed = np.full((480, 640, 3), (180, 180, 180), dtype=np.uint8)
    after_placed[125:190, 230:288] = (30, 120, 240)
    v2 = cell_area_xyz.verify_stack_outcome(
        before_side=before_side,
        after_side=after_placed,
        pick={"col": 1, "tier": 1},
        place={"col": 2, "tier": 3},
    )
    assert v2["verified"] is True
    assert v2["recovery_mode"] is None
    assert v2["place_slot"]["zone"]["within_zone"] is True

    # Case 3: Top view shows container placed horizontally (가로, horizontal_ew) when vertical (세로, yaw=-90) is required
    top_horiz = np.full((480, 640, 3), (180, 180, 180), dtype=np.uint8)
    top_horiz[205:227, 372:418] = (30, 120, 240)
    v3 = cell_area_xyz.verify_stack_outcome(
        before_side=before_side,
        after_side=after_placed,
        after_top=top_horiz,
        pick={"col": 1, "tier": 1},
        place={"col": 2, "row": 1, "tier": 3, "yaw_deg": -90.0},
    )
    assert v3["verified"] is False
    assert v3["recovery_mode"] == "re_orient_and_re_place"
    assert v3["place_slot"]["top_zone"]["orientation_class"] == "horizontal_ew"

    # Case 4: Safe 180-deg pick yaw normalization keeps wrist_roll away from cable limit
    assert cell_area_xyz.normalize_pick_yaw_deg(45.0, x_m=0.088, y_m=-0.088) == -135.0


def test_parallel_sim_precheck_and_multistage_task_plan(tmp_path: Path):
    import numpy as np

    d_t2 = build_directive(
        arm_id="arm_b",
        directive_id="stage1-tier2",
        pick={"area": "pallet", "col": 1, "row": 1, "tier": 1, "x": 0.1214, "y": -0.0219, "z": 0.0085, "yaw_deg": -90.0, "apply_bias": False},
        place={"area": "pallet", "col": 2, "row": 1, "tier": 2, "x": 0.1605, "y": -0.0060, "z": 0.0390, "yaw_deg": -90.0, "apply_bias": False},
    )
    d_t3 = build_directive(
        arm_id="arm_b",
        directive_id="stage2-tier3",
        pick={"area": "pallet", "col": 2, "row": 2, "tier": 1, "x": 0.1536, "y": -0.0948, "z": 0.0085, "yaw_deg": 47.3, "apply_bias": False},
        place={"area": "pallet", "col": 2, "row": 1, "tier": 3, "x": 0.1605, "y": -0.0060, "z": 0.0685, "yaw_deg": -90.0, "apply_bias": False},
    )

    pre = cell_area_xyz.sim_precheck_and_optimize_directive(d_t3, SAMPLE_BASE_PLAN, work_dir=tmp_path)
    assert pre["ok"] is True
    assert pre["normalized_pick_yaw_deg"] == -132.7
    assert pre["clearance_lift_m"] >= 0.085
    assert pre["wrist_roll_range_units"][0] >= 44.0

    stage_state = {"stage": 0}

    def fake_act(cmd: str) -> dict:
        if cmd == "run grasp_pick":
            return {"ok": True, "holding": True, "gripper_current_ma": 152, "state": [0.0, 0.0, 0.0, 0.0, 48.0, 54.6]}
        if cmd in ("run lift_pick", "goto above_place"):
            return {"ok": True, "holding": True, "gripper_current_ma": 148, "state": [0.0, 0.0, 0.0, 0.0, 48.0, 54.5]}
        if cmd == "run release_place":
            stage_state["stage"] += 1
        return {"ok": True, "state": [0.0, 0.0, 0.0, 0.0, 48.0, 58.2]}

    def fake_frame(role: str):
        img = np.full((480, 640, 3), (180, 180, 180), dtype=np.uint8)
        if role == "side":
            if stage_state["stage"] == 0:
                img[252:315, 175:225] = (30, 120, 240)
            elif stage_state["stage"] == 1:
                img[190:252, 226:296] = (30, 120, 240)
            else:
                img[190:252, 226:296] = (30, 120, 240)
                img[120:195, 226:296] = (30, 120, 240)
        elif role == "top":
            img[170:260, 380:410] = (30, 120, 240)
        return img

    plan_res = cell_area_xyz.execute_task_plan(
        [
            {"stage_id": "tier2", "candidates": [d_t2]},
            {"stage_id": "tier3", "candidates": [d_t2, d_t3]},
        ],
        base_plan=SAMPLE_BASE_PLAN,
        work_dir=tmp_path,
        act_fn=fake_act,
        frame_fn=fake_frame,
        parallel_sim=True,
    )
    assert plan_res["task_verified"] is True
    assert plan_res["stages_completed"] == 2
    assert set(plan_res["used_candidates"]) == {"stage1-tier2", "stage2-tier3"}


def test_live_perception_vanishing_projection_base_and_candidates():
    import numpy as np
    import cell_area_zones as caz

    # 1. Vanishing point (322, 383) projection reproduces the verified physical transfer points within <= 2.0 mm
    p0_x, p0_y = caz.top_pixel_to_arm_xy_vanishing(305.4, 222.9, h_top_m=0.030)
    p1_x, p1_y = caz.top_pixel_to_arm_xy_vanishing(353.9, 220.6, h_top_m=0.030)
    p2_x, p2_y = caz.top_pixel_to_arm_xy_vanishing(428.6, 217.5, h_top_m=0.030)
    p3_x, p3_y = caz.top_pixel_to_arm_xy_vanishing(463.5, 225.7, h_top_m=0.030)
    assert abs(p0_x - 0.1155) <= 0.0020 and abs(p0_y - (-0.0130)) <= 0.0030
    assert abs(p1_x - 0.1486) <= 0.0020 and abs(p1_y - (-0.0120)) <= 0.0020
    assert abs(p2_x - 0.1942) <= 0.0020 and abs(p2_y - (-0.0100)) <= 0.0020
    assert abs(p3_x - 0.2150) <= 0.0020 and abs(p3_y - (-0.0150)) <= 0.0020

    # 2. Live base container perception (Yellow container in top + side views)
    top_img = np.full((480, 640, 3), (180, 180, 180), dtype=np.uint8)
    side_img = np.full((480, 640, 3), (180, 180, 180), dtype=np.uint8)
    top_img[190:250, 338:370] = (20, 210, 230)
    side_img[252:288, 185:232] = (20, 210, 230)
    live_base = caz.perceive_live_base(top_img, side_img, preferred_col=2)
    assert live_base["found"] is True
    assert 0.140 <= live_base["arm_xy"][0] <= 0.155
    assert 2 in live_base["side_roi_by_tier"] and 3 in live_base["side_roi_by_tier"]

    # 3. Live pickable orange container candidates perception (Row 1 + Belt + Row 2 horizontal)
    # Add orange container in Row 1 (u=290..322, v=190..255) and Belt (u=368..400, v=45..110)
    top_img[190:255, 290:322] = (25, 110, 240)
    top_img[45:110, 368:400] = (25, 110, 240)
    cands = caz.perceive_live_pick_candidates(top_img)
    areas = {c["area"] for c in cands}
    assert "pallet" in areas
    assert "belt" in areas


def test_calculus_grasp_dynamics_stiffness_and_slip_derivatives():
    import cell_arm_cal

    # 1. Empty closure in air: jaw reaches near-closed deadband (49.2)
    r_empty = {"ok": True, "holding": False, "gripper_current_ma": 34.0, "state": [0, 0, 0, 0, 48.0, 49.2]}
    d_empty = cell_arm_cal.evaluate_grasp_dynamics(r_empty, closed=48.8, open_pos=57.85)
    assert d_empty["holding"] is False
    assert d_empty["regime"] == "empty_closure"

    # 2. Fluctuating low current (42 mA < static 65 mA) but physical 30mm jaw arrest (q=53.6) -> holding=True
    r_low_curr = {"ok": True, "holding": False, "gripper_current_ma": 42.0, "state": [0, 0, 0, 0, 48.0, 53.6]}
    d_low = cell_arm_cal.evaluate_grasp_dynamics(r_low_curr, closed=48.8, open_pos=57.85, baseline_current_ma=65.0)
    assert d_low["holding"] is True
    assert d_low["regime"] == "stable_hold"
    assert cell_arm_cal.infer_holding(r_low_curr, closed=48.8, min_current_ma=65.0) is True

    # 3. Elastic pad settling during lift (55.68 -> 54.29 -> 54.25): NOT a slip!
    r_g1 = {"ok": True, "holding": True, "gripper_current_ma": 155.0, "state": [0, 0, 0, 0, 48.0, 55.68]}
    r_l1 = {"ok": True, "holding": True, "gripper_current_ma": 132.0, "state": [0, 0, 0, 0, 48.0, 54.29]}
    r_a1 = {"ok": True, "holding": True, "gripper_current_ma": 128.0, "state": [0, 0, 0, 0, 48.0, 54.25]}
    d_settle = cell_arm_cal.evaluate_grasp_dynamics(r_g1, r_lift=r_l1, r_above_place=r_a1, closed=48.8, open_pos=57.85)
    assert d_settle["holding"] is True
    assert d_settle["regime"] == "elastic_settle"
    assert d_settle["d2q_settle"] > 0.0

    # 4. True slip collapse during lift (52.31 -> 49.18): dq_lift = -3.13u collapses into deadband
    r_g2 = {"ok": True, "holding": True, "gripper_current_ma": 144.0, "state": [0, 0, 0, 0, 48.0, 52.31]}
    r_l2 = {"ok": True, "holding": False, "gripper_current_ma": 88.0, "state": [0, 0, 0, 0, 48.0, 49.18]}
    d_slip = cell_arm_cal.evaluate_grasp_dynamics(r_g2, r_lift=r_l2, closed=48.8, open_pos=57.85)
    assert d_slip["holding"] is False
    assert d_slip["regime"] == "slip_collapse"
    assert d_slip["dq_lift"] < -3.0


def test_ship_z_search_recovery_and_contact_z_clearance():
    import cell_area_zones

    directive = {
        "pick": {"area": "ship", "col": 1, "tier": 1, "x": 0.165, "y": -0.145, "z": 0.004, "effective_xyz_m": [0.165, -0.145, 0.004], "yaw_deg": 0.0},
        "execution": {},
    }
    rec_empty = cell_area_zones.diagnose_and_recover_pick(
        attempt=0,
        cur_directive=directive,
        r_desc={"ok": True},
        r_grasp={"ok": True, "state": [0, 0, 0, 0, 0, 49.5], "gripper_current_ma": 40.0},
        cal={"held_30mm": 54.0},
        tried_xs=[],
    )
    assert rec_empty["recovered_pick_xyz_m"][2] < 0.004

    rec_contact = cell_area_zones.diagnose_and_recover_pick(
        attempt=1,
        cur_directive=directive,
        r_desc={"ok": False, "contact_z": 0.012},
        r_grasp={},
        cal={"held_30mm": 54.0},
        tried_xs=[0.165],
    )
    assert rec_contact["recovered_pick_xyz_m"][2] == pytest.approx(0.016)






