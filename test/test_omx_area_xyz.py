"""Tests for Unified AreaXYZ Coordinate System and ROSY Middleware -> rosy-cell Directive Execution (D-1014)."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "middleware/devices/omx/adapter", ROOT / "deploy/robot/omx", ROOT / "tools/sim"):
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


def test_omx_ai_profile_z_mm_landmarks_calibration_and_live_container_z_grasp(tmp_path: Path):
    import numpy as np
    from omx_adapter.z_profile import (
        OMX_AI_PROFILE_MM,
        SideViewZProfile,
        TopDepthZProfile,
        fk_landmarks_mm,
        reconcile_tcp_z_mm,
    )

    # 1. Exact OMX-AI CAD self-profile landmarks in mm (including stock wrist camera CAMERA_INNOMAKER_720P_11)
    assert OMX_AI_PROFILE_MM["base_plate_top_z_mm"] == 13.0
    assert OMX_AI_PROFILE_MM["joint1_xyz_mm"] == (-11.25, 0.0, 34.0)
    assert OMX_AI_PROFILE_MM["joint2_z_mm"] == 97.5
    assert OMX_AI_PROFILE_MM["joint2_above_plate_top_mm"] == 84.5
    assert OMX_AI_PROFILE_MM["tcp_v21_x_mm"] == 74.1
    assert OMX_AI_PROFILE_MM["wrist_cam_mount_part"] == "PR33_C02_F9_REV1_5"
    assert OMX_AI_PROFILE_MM["wrist_cam_part"] == "CAMERA_INNOMAKER_720P_11"
    assert OMX_AI_PROFILE_MM["wrist_cam_rel_link5_xyz_mm"] == (36.24, 0.0, 45.84)
    assert OMX_AI_PROFILE_MM["wrist_cam_pitch_from_approach_deg"] == 38.0
    assert OMX_AI_PROFILE_MM["wrist_cam_above_stock_tcp_mm"] == 55.69
    assert OMX_AI_PROFILE_MM["wrist_cam_above_v21_tcp_mm"] == 37.86

    fk0 = fk_landmarks_mm([0.0, 0.0, 0.0, 0.0, 0.0], unit="deg")
    assert fk0["landmarks_z_mm"]["base_bottom"] == 0.0
    assert fk0["landmarks_z_mm"]["base_plate_top"] == 13.0
    assert fk0["landmarks_z_mm"]["joint1"] == 34.0
    assert fk0["landmarks_z_mm"]["joint2"] == 97.5
    assert fk0["landmarks_z_mm"]["joint3"] == 210.65
    assert fk0["landmarks_z_mm"]["wrist_cam"] == 256.49

    fk_td = fk_landmarks_mm([0.0, 0.0, 0.0, 90.0, 0.0], unit="deg", tcp_x_mm=74.1)
    assert fk_td["wrist_cam_height_above_tcp_mm"] == 37.86
    fk_td_s = fk_landmarks_mm([0.0, 0.0, 0.0, 90.0, 0.0], unit="deg", tcp_x_mm=91.93)
    assert fk_td_s["wrist_cam_height_above_tcp_mm"] == 55.69

    rec = reconcile_tcp_z_mm(7.4)
    assert rec["tcp_length_delta_mm"] == 14.4
    assert rec["cad_jaw_tip_z_mm"] == 21.8
    assert rec["physical_jaw_tip_z_mm"] == 13.5

    # 2. AreaXYZ accepts and returns explicit mm coordinates
    slot_mm = resolve_area_xyz("pallet", col=2, row=1, tier=1, z_mm=7.4)
    assert slot_mm["z_mm"] == 7.4
    assert slot_mm["effective_xyz_mm"] == [158.0, -13.0, 7.4]
    assert slot_mm["surface_z_mm"] == 0.0
    assert slot_mm["top_z_mm"] == 30.0
    assert slot_mm["profile_anchor_mm"]["joint2_shoulder_z_mm"] == 97.5

    # 3. (A) Preflight calibration from self-profile landmarks & top depth base plate gauge (13.0 mm)
    td = TopDepthZProfile(measured_plate_top_mm=12.5, cad_plate_top_mm=13.0)
    assert td.depth_scale == 1.04
    assert td.raw_height_to_link0_z_mm(25.0) == 26.0

    cal_prof = cell_area_xyz.calibrate_z_profile_mm(
        tmp_path,
        arm_id="arm_b",
        landmark_observations=[(287.3, 13.0), (107.0, 97.5)],
        joint_state_deg=[0.0, -10.0, 15.0, 85.0, 0.0],
    )
    assert "side_view" in cal_prof
    side_fit = SideViewZProfile.from_dict(cal_prof["side_view"])
    assert abs(side_fit.v_to_z_mm(287.3) - 13.0) <= 0.3
    assert abs(side_fit.v_to_z_mm(107.0) - 97.5) <= 0.3

    # 4. (B) Live execution-time container Z-mm perception and automatic pick.z refinement
    side_img = np.full((480, 640, 3), (180, 180, 180), dtype=np.uint8)
    side_img[237:301, 232:288] = (30, 120, 240)
    live_obs = cell_area_xyz.perceive_slot_z_mm(side_img, col=2, row=1, tier=1, z_profile=cal_prof)
    assert live_obs["found"] is True
    assert live_obs["inferred_tier"] == 1
    assert live_obs["measured_top_z_mm"] > 33.0
    assert live_obs["measured_grasp_z_mm"] > 10.0


def test_container_spec_c3_c2_c1_slot_x_estimation_and_3d_frustum_roi():
    import numpy as np
    from omx_adapter.z_profile import CONTAINER_SPECS_MM, resolve_container_spec
    import cell_z_profile as czp

    # 1. ContainerSpec C3 / C2 / C1 catalog resolution & slot X candidates
    c3 = resolve_container_spec("C3")
    c2 = resolve_container_spec("container-v2-2")
    c1 = resolve_container_spec("1")
    assert c3["spec_id"] == "C3" and c3["expected_area_mm2"] == 2700.0 and c3["slot_x_candidates_mm"] == [0.0]
    assert c2["spec_id"] == "C2" and c2["expected_area_mm2"] == 1800.0 and c2["slot_x_candidates_mm"] == [-15.0, 15.0]
    assert c1["spec_id"] == "C1" and c1["expected_area_mm2"] == 900.0 and c1["slot_x_candidates_mm"] == [-30.0, 0.0, 30.0]
    assert set(CONTAINER_SPECS_MM.keys()) == {"C3", "C2", "C1"}

    # 2. 3D frustum ROI scaling across tiers and container specs
    roi_t1_c3 = czp.project_container_spec_roi(col=2, tier=1, spec_id="C3")
    roi_t3_c3 = czp.project_container_spec_roi(col=2, tier=3, spec_id="C3")
    roi_t1_c1 = czp.project_container_spec_roi(col=2, tier=1, spec_id="C1", x_offset_mm=30.0)
    assert roi_t3_c3["frustum_scale"] > roi_t1_c3["frustum_scale"]
    assert roi_t1_c1["spec_id"] == "C1"
    assert roi_t1_c1["expected_area_mm2"] == 900.0

    # 3. Bimodal (C2: +-15mm) and Trimodal (C1: -30/0/+30mm) slot X center estimation
    est_c3 = czp.estimate_slot_x_from_spec(None, None, col=2, row=1, spec_id="C3")
    assert est_c3["x_hat_mm"] == 0.0
    assert est_c3["needs_reobserve"] is False

    top_blank = np.zeros((480, 640, 3), dtype=np.uint8)
    est_c2_ambig = czp.estimate_slot_x_from_spec(top_blank, None, col=2, row=1, spec_id="C2")
    assert est_c2_ambig["spec_id"] == "C2"
    assert est_c2_ambig["candidates_mm"] == [-15.0, 15.0]

    # Synthesize warm container pixels shifted to the +15mm C2 sub-slot and +30mm C1 sub-slot
    top_c2_pos = np.full((480, 640, 3), (180, 180, 180), dtype=np.uint8)
    r_pos15 = czp.project_container_spec_roi(col=2, tier=1, spec_id="C2", x_offset_mm=15.0)["top_roi_px"]
    top_c2_pos[r_pos15[1]:r_pos15[3], r_pos15[0]:r_pos15[2]] = (20, 130, 240)
    est_c2_pos = czp.estimate_slot_x_from_spec(top_c2_pos, None, col=2, row=1, spec_id="C2")
    assert est_c2_pos["x_hat_mm"] in (-15.0, 15.0)

    top_c1_pos = np.full((480, 640, 3), (180, 180, 180), dtype=np.uint8)
    r_pos30 = czp.project_container_spec_roi(col=2, tier=1, spec_id="C1", x_offset_mm=30.0)["top_roi_px"]
    top_c1_pos[r_pos30[1]:r_pos30[3], r_pos30[0]:r_pos30[2]] = (20, 130, 240)
    est_c1_pos = czp.estimate_slot_x_from_spec(top_c1_pos, None, col=2, row=1, spec_id="C1")
    assert est_c1_pos["candidates_mm"] == [-30.0, 0.0, 30.0]


def test_round2_consensus_signed_z_judge_catches_nearest_bug_and_c1_area():
    from omx_adapter.z_profile import evaluate_signed_tier_residual_mm

    # 1. Tier 2 container slumped by 32.4 mm to 30.0 mm -> r_2 = -32.4 mm <= -4.0 mm -> FAIL: S2_TOPPLED_OR_SLUMPED
    # (Proves signed residual catches the nearest() bug where 30.0 mm used to match Tier 1 as PASS!)
    slumped_t2 = evaluate_signed_tier_residual_mm(30.0, expected_tier=2, valid_depth_ratio=0.92, spec_id="C3")
    assert slumped_t2["expected_top_z_mm"] == 62.4
    assert slumped_t2["r_k_mm"] == pytest.approx(-32.4)
    assert slumped_t2["verdict"] == "FAIL"
    assert slumped_t2["failure_code"] == "S2_TOPPLED_OR_SLUMPED"

    # 2. Confluence 27197547 Section 1 reproducer: Tier 2 at 47.61 mm -> r_2 = -14.79 mm -> FAIL: S2_TOPPLED_OR_SLUMPED
    conf_t2 = evaluate_signed_tier_residual_mm(
        47.61,
        expected_tier=2,
        valid_depth_ratio=0.85,
        dz_top_side_mm=16.76,
        tilt_deg=35.0,
        spec_id="C3",
    )
    assert conf_t2["r_k_mm"] == pytest.approx(-14.79)
    assert conf_t2["verdict"] == "FAIL"
    assert conf_t2["failure_code"] == "S2_TOPPLED_OR_SLUMPED"

    # 3. Unseated cone (+1.0 .. +3.0 mm) -> FAIL: S6_UNSEATED_CONE
    unseated = evaluate_signed_tier_residual_mm(64.2, expected_tier=2, valid_depth_ratio=0.95, spec_id="C3")
    assert unseated["r_k_mm"] == pytest.approx(1.8)
    assert unseated["verdict"] == "FAIL"
    assert unseated["failure_code"] == "S6_UNSEATED_CONE"

    # 4. C1 (900 mm^2) uses A_spec = 900 mm^2 so normal C1 (e.g. 810 mm^2 -> ratio 0.90 >= 0.65) is PASS
    c1_pass = evaluate_signed_tier_residual_mm(
        30.0,
        expected_tier=1,
        valid_depth_ratio=0.90,
        obs_area_mm2=810.0,
        spec_id="C1",
    )
    assert c1_pass["spec_id"] == "C1"
    assert c1_pass["area_ratio"] == pytest.approx(0.9)
    assert c1_pass["gate_ok"] is True
    assert c1_pass["verdict"] == "PASS"
    assert c1_pass["failure_code"] is None


def test_cell_spec_recovery_fsm_gates_skills_and_temp_directives():
    import cell_spec_recovery_fsm as csrf

    # 1. Execution Interlock Gates (pre_grasp, at_grasp, lift_verify, pre_place, post_release, leg_transition)
    g_ambig = csrf.evaluate_execution_gate("pre_grasp", sigma_x_mm=3.2)
    assert g_ambig["verdict"] == "UNKNOWN" and g_ambig["failure_code"] == "S5_X_BIMODAL_AMBIGUOUS"

    g_packed = csrf.evaluate_execution_gate("pre_grasp", clearance_min_mm=3.8)
    assert g_packed["verdict"] == "FAIL" and g_packed["failure_code"] == "S3_PACKED_NO_CLEARANCE"

    g_air = csrf.evaluate_execution_gate("at_grasp", gripper_pos=49.2, current_ma=42.0)
    assert g_air["verdict"] == "FAIL" and g_air["failure_code"] == "S4_EMPTY_AIR_CLOSE"

    g_lift_fail = csrf.evaluate_execution_gate("lift_verify", gripper_pos=53.92, current_ma=45.0, lift_delta_mm=4.5)
    assert g_lift_fail["verdict"] == "FAIL" and g_lift_fail["failure_code"] == "S4_SHALLOW_OR_SLIPPED_LIFT"

    g_lift_ok = csrf.evaluate_execution_gate("lift_verify", gripper_pos=54.2, current_ma=165.0, lift_delta_mm=18.0)
    assert g_lift_ok["verdict"] == "PASS" and g_lift_ok["ok"] is True

    g_post_cone = csrf.evaluate_execution_gate("post_release", z_gate={"r_k_mm": 1.9, "verdict": "FAIL"})
    assert g_post_cone["verdict"] == "FAIL" and g_post_cone["failure_code"] == "S6_UNSEATED_CONE"

    g_leg_block = csrf.evaluate_execution_gate("leg_transition", prior_leg_result="fault")
    assert g_leg_block["verdict"] == "FAIL" and g_leg_block["failure_code"] == "S7_PRIOR_LEG_FAILED_INTERLOCK"

    # 2. Recovery Skill Selection: In-Place (L1) vs S-Temp (L2) vs Safe Hold (L3)
    s_yaw = csrf.select_recovery_skill("S1_POSE_OFFSET_OR_YAW", yaw_err_deg=8.5, dy_mm=0.8, dx_mm=0.5)
    assert s_yaw["level"] == "L1" and s_yaw["skill"] == "wrist_yaw_servo"

    s_push_y = csrf.select_recovery_skill("S1_POSE_OFFSET_OR_YAW", dy_mm=4.2, dx_mm=1.0, yaw_err_deg=2.0)
    assert s_push_y["level"] == "L1" and s_push_y["skill"] == "push_align_side"

    s_push_x = csrf.select_recovery_skill("S1_POSE_OFFSET_OR_YAW", dx_mm=15.0, dy_mm=1.0, yaw_err_deg=2.0)
    assert s_push_x["level"] == "L1" and s_push_x["skill"] == "push_align_end"

    s_temp_s1 = csrf.select_recovery_skill("S1_POSE_OFFSET_OR_YAW", dy_mm=9.5, yaw_err_deg=16.0, temp_slot_free=True)
    assert s_temp_s1["level"] == "L2" and s_temp_s1["skill"] == "recenter_on_temp"

    s_free = csrf.select_recovery_skill("S3_PACKED_NO_CLEARANCE", free_push_open=True, tilt_deg=2.0)
    assert s_free["level"] == "L1" and s_free["skill"] == "free_push"

    s_clear = csrf.select_recovery_skill("S3_PACKED_NO_CLEARANCE", free_push_open=False, temp_slot_free=True, neighbor_removable=True)
    assert s_clear["level"] == "L2" and s_clear["skill"] == "clear_neighbor_then_pick"

    s_nudge = csrf.select_recovery_skill("S6_UNSEATED_CONE", r_k_mm=1.8, tilt_deg=3.0)
    assert s_nudge["level"] == "L1" and s_nudge["skill"] == "seat_nudge"

    s_s2_temp = csrf.select_recovery_skill("S2_TOPPLED_OR_SLUMPED", r_k_mm=-12.0, tilt_deg=15.0, temp_slot_free=True)
    assert s_s2_temp["level"] == "L2" and s_s2_temp["skill"] == "recenter_on_temp"

    s_s2_abort = csrf.select_recovery_skill("S2_TOPPLED_OR_SLUMPED", r_k_mm=-14.79, tilt_deg=35.0, temp_slot_free=True)
    assert s_s2_abort["level"] == "L3" and s_s2_abort["skill"] == "abort_safe_hold"

    # 3. Compile 2-leg S-Temp directives (Leg A -> temp_plate_b, Leg B -> destination with interlock)
    base_dir = build_directive(
        arm_id="arm_b",
        pick={"area": "pallet", "col": 1, "row": 1, "tier": 2},
        place={"area": "pallet", "col": 2, "row": 1, "tier": 2},
        directive_id="recenter-test",
        object_id="container-v2-2",
    )
    legs = csrf.compile_recenter_on_temp_directives(base_dir, temp_area="temp_plate_b", lane=2)
    assert len(legs) == 2
    assert legs[0]["place"]["area"] == "temp_plate_b" and legs[0]["temp_lane"] == 2
    assert legs[1]["pick"]["area"] == "temp_plate_b" and legs[1]["interlock_requires_leg"] == legs[0]["directive_id"]


def test_cell_fast_learner_and_contextual_choices_safety_sovereignty(tmp_path: Path):
    import numpy as np
    from cell_choices import Choices
    from cell_fast_learner import (
        FEATURE_NAMES_20D,
        InterventionWeightedLearner,
        ResidualFailureClassifier,
        combine_verdicts,
        extract_feature_vector_20d,
        rule_guard_verdict,
    )
    from omx_failsafe_synth_sim import CONFLUENCE_27197547_SEC1_REPRODUCER

    # 1. 20-D feature vector extraction
    assert len(FEATURE_NAMES_20D) == 20
    vec = extract_feature_vector_20d(CONFLUENCE_27197547_SEC1_REPRODUCER)
    assert vec.shape == (20,)
    assert vec[2] == 1.0  # is_c3
    assert vec[8] == pytest.approx(-14.79)  # r_k_mm

    # 2. Unidirectional Safety Sovereignty: rule guard FAIL can never be overridden by model PASS
    rule_out = rule_guard_verdict(CONFLUENCE_27197547_SEC1_REPRODUCER)
    assert rule_out["verdict"] == "FAIL"
    assert rule_out["failure_code"] == "S2_TOPPLED_OR_SLUMPED"
    combined = combine_verdicts(rule_out, {"verdict": "PASS", "failure_code": None, "pass_prob": 0.99})
    assert combined["verdict"] == "FAIL"
    assert combined["failure_code"] == "S2_TOPPLED_OR_SLUMPED"

    # Conversely, when rule guard is PASS, a model FAIL downgrades to FAIL (unidirectional refinement)
    nom_rule = rule_guard_verdict({"spec_id": "C3", "tier_k": 1, "r_k_mm": -0.2, "valid_depth_ratio": 0.95})
    assert nom_rule["verdict"] == "PASS"
    downgraded = combine_verdicts(nom_rule, {"verdict": "FAIL", "failure_code": "S1_POSE_OFFSET_OR_YAW", "pass_prob": 0.20})
    assert downgraded["verdict"] == "FAIL"
    assert downgraded["failure_code"] == "S1_POSE_OFFSET_OR_YAW"

    # 3. ResidualFailureClassifier & InterventionWeightedLearner persistence roundtrip
    clf = ResidualFailureClassifier()
    X_demo = np.vstack([
        extract_feature_vector_20d({"spec_id": "C3", "tier_k": 1, "r_k_mm": 0.0, "valid_depth_ratio": 0.95}),
        extract_feature_vector_20d(CONFLUENCE_27197547_SEC1_REPRODUCER),
    ])
    clf.fit(X_demo, ["PASS", "S2_TOPPLED_OR_SLUMPED"], false_pass_weight=5.0, epochs=60)
    clf_path = tmp_path / "clf.json"
    clf.save(clf_path)
    clf_loaded = ResidualFailureClassifier.load(clf_path)
    assert clf_loaded.evaluate_with_guard(CONFLUENCE_27197547_SEC1_REPRODUCER)["verdict"] == "FAIL"

    iwr = InterventionWeightedLearner(human_weight=5.0, normal_weight=1.0)
    iwr.record_episode(CONFLUENCE_27197547_SEC1_REPRODUCER, "recenter_on_temp", (0.0, 3.2, -6.5), human_intervention=True)
    iwr.fit(epochs=60)
    pred_iwr = iwr.predict(CONFLUENCE_27197547_SEC1_REPRODUCER, allowed_skills=["recenter_on_temp", "proceed"])
    assert pred_iwr["skill"] == "recenter_on_temp"

    # 4. Contextual Choices (LinUCB bandit with propensity logging)
    ch = Choices(tmp_path / "choices.json")
    ch.offer_contextual("recovery_skill", "push_align_side", "rule")
    ch.offer_contextual("recovery_skill", "recenter_on_temp", "temp")
    for _ in range(5):
        ch.outcome_contextual("recovery_skill", "recenter_on_temp", ok=True, reward=1.0, features=[1.0, 0.5, -0.8], propensity=0.8)
        ch.outcome_contextual("recovery_skill", "push_align_side", ok=False, reward=-0.5, features=[1.0, 0.5, -0.8], propensity=0.8)
    best_ctx = ch.best_contextual("recovery_skill", allowed=["push_align_side", "recenter_on_temp"], features=[1.0, 0.5, -0.8])
    assert best_ctx["value"] == "recenter_on_temp"
    assert 0.0 < best_ctx["propensity"] <= 1.0


def test_omx_failsafe_synth_sim_fast_learning_pipeline_end_to_end(tmp_path: Path):
    from omx_failsafe_synth_sim import run_fast_learning_pipeline, synthesize_failsafe_dataset

    ds = synthesize_failsafe_dataset(n_episodes=140, seed=42)
    assert ds["n_episodes"] == 140
    assert ds["X_train"].shape[1] == 20
    assert ds["confluence_27197547_reproducer"]["r_k_mm"] == -14.79

    report = run_fast_learning_pipeline(out_dir=tmp_path, n_sim=180, n_human_interventions=24)
    assert report["all_verified"] is True
    assert report["confluence_27197547_blocked"] is True
    assert report["false_pass_rate_val"] == 0.0
    assert report["slot_x_candidates_verified"] is True
    assert report["iwr_skill_accuracy"] >= 0.75
    assert (tmp_path / "fast-learning-report.json").exists()


def test_multiview_subzone_2d_to_3d_fusion_and_split_2d_modes():
    import cell_subzone_3d as csz
    import cell_z_profile as czp

    # 1. Sub-zone 30x30x30 mm grid projection (-30, 0, +30 mm) across Top & Side views
    rois = czp.build_slot_subzone_rois(col=2, row=1, tier=2)
    assert len(rois) == 3
    assert [r["x_center_mm"] for r in rois] == [-30.0, 0.0, 30.0]

    # 2. Mode 1 (fused_3d): Half-slumped C3 container where rear (-30mm) is at 62.4mm,
    #    center (0mm) at 56.0mm, and front (+30mm) slumped to 44.0mm -> FAIL: S2_TOPPLED_OR_SLUMPED
    res_slump = csz.evaluate_multiview_subzones(
        col=2, row=1, tier=2, spec_id="C3", mode="fused_3d",
        synthetic_subzones=[
            {"top_occ": 0.90, "side_occ": 0.90, "top_depth_z_mm": 62.4, "side_top_z_mm": 62.4},
            {"top_occ": 0.88, "side_occ": 0.88, "top_depth_z_mm": 56.0, "side_top_z_mm": 56.0},
            {"top_occ": 0.85, "side_occ": 0.85, "top_depth_z_mm": 44.0, "side_top_z_mm": 44.0},
        ],
    )
    assert res_slump["verdict"] == "FAIL"
    assert res_slump["failure_code"] == "S2_TOPPLED_OR_SLUMPED"
    assert res_slump["fused_3d"]["dz_span_mm"] == pytest.approx(-18.4)
    assert res_slump["fused_3d"]["slumped_subzone_x_mm"] == 30.0
    assert res_slump["recovery_skill"]["skill"] == "recenter_on_temp"

    # 3. Mode 1 (fused_3d) & Hybrid: Edge-perched cone (+30mm sub-zone at 64.3mm, r_k=+1.9mm)
    #    localizes perched_subzone_x_mm=30.0 and routes seat_nudge directly to nudge_x_mm=30.0
    res_cone = csz.evaluate_multiview_subzones(
        col=2, row=1, tier=2, spec_id="C3", mode="hybrid",
        synthetic_subzones=[
            {"top_occ": 0.92, "side_occ": 0.92, "top_depth_z_mm": 62.4, "side_top_z_mm": 62.4},
            {"top_occ": 0.92, "side_occ": 0.92, "top_depth_z_mm": 62.5, "side_top_z_mm": 62.5},
            {"top_occ": 0.90, "side_occ": 0.90, "top_depth_z_mm": 64.3, "side_top_z_mm": 64.3},
        ],
    )
    assert res_cone["verdict"] == "FAIL"
    assert res_cone["failure_code"] == "S6_UNSEATED_CONE"
    assert res_cone["fused_3d"]["perched_subzone_x_mm"] == 30.0
    assert res_cone["recovery_skill"]["skill"] == "seat_nudge"
    assert res_cone["recovery_skill"]["params"]["nudge_x_mm"] == 30.0

    # 4. Mode 2 (split_2d): C2 (30x60x30) occupying sub_1 and sub_2 ([0, 1, 1]) passes both Top XY and Side XZ,
    #    whereas C3 (30x90x30) with the same [0, 1, 1] mask fails span check (S1_POSE_OFFSET_OR_YAW)
    sub_two_cells = [
        {"top_occ": 0.05, "side_occ": 0.05, "top_depth_z_mm": 30.0, "side_top_z_mm": 30.0},
        {"top_occ": 0.90, "side_occ": 0.90, "top_depth_z_mm": 62.4, "side_top_z_mm": 62.4},
        {"top_occ": 0.90, "side_occ": 0.90, "top_depth_z_mm": 62.4, "side_top_z_mm": 62.4},
    ]
    res_c2_ok = csz.evaluate_multiview_subzones(
        col=2, row=1, tier=2, spec_id="C2", mode="split_2d", synthetic_subzones=sub_two_cells,
    )
    assert res_c2_ok["verdict"] == "PASS"
    assert res_c2_ok["split_2d"]["top_xy_pass"]["occupied_mask"] == [0, 1, 1]
    assert res_c2_ok["split_2d"]["top_xy_pass"]["x_hat_mm"] == pytest.approx(15.0)

    res_c3_short = csz.evaluate_multiview_subzones(
        col=2, row=1, tier=2, spec_id="C3", mode="split_2d", synthetic_subzones=sub_two_cells,
    )
    assert res_c3_short["verdict"] == "FAIL"
    assert res_c3_short["failure_code"] == "S1_POSE_OFFSET_OR_YAW"

    # 5. Adaptive Hybrid: D435 specular dropout on C2 (valid_depth_ratio=0.10, top_occ=0.10)
    #    automatically promotes Side XZ (`side_xz_promoted`) and avoids false L0 reobserve delay
    res_dropout = csz.evaluate_multiview_subzones(
        col=2, row=1, tier=2, spec_id="C2", mode="adaptive_hybrid",
        synthetic_subzones=[
            {"top_occ": 0.05, "side_occ": 0.05, "valid_depth_ratio": 0.10, "side_top_z_mm": 30.0},
            {"top_occ": 0.10, "side_occ": 0.90, "valid_depth_ratio": 0.12, "side_top_z_mm": 62.4},
            {"top_occ": 0.10, "side_occ": 0.92, "valid_depth_ratio": 0.10, "side_top_z_mm": 62.4},
        ],
    )
    assert res_dropout["active_mode"] == "side_xz_promoted"
    assert res_dropout["verdict"] == "PASS"
    assert res_dropout["recovery_skill"]["skill"] == "proceed"

    # 6. Full 3x1x3 (9-voxel) column reconstruction: stair-step vs unsupported overhang
    col_stair = csz.reconstruct_slot_voxel_column_3x3(
        top_occ_by_subzone=(0.9, 0.9, 0.9),
        subzone_top_z_mm=(62.4, 30.0, 30.0),
    )
    assert col_stair["verdict"] == "PASS"
    assert col_stair["is_stair_step"] is True
    assert col_stair["stair_step_tiers"] == [2, 1, 1]

    col_overhang = csz.reconstruct_slot_voxel_column_3x3(
        top_occ_by_subzone=(0.9, 0.9, 0.9),
        side_tier_occ_grid=[
            [1.0, 1.0, 0.0],  # Tier 1 missing under +30mm
            [1.0, 1.0, 0.9],  # Tier 2 overhanging at +30mm
            [0.0, 0.0, 0.0],
        ],
    )
    assert col_overhang["verdict"] == "FAIL"
    assert col_overhang["unsupported_overhang"] is True
    assert col_overhang["unsupported_overhangs"][0]["x_center_mm"] == 30.0


def test_slot_matrix_identity_wrong_slot_trench_reorient_and_12_scenarios(tmp_path):
    """Verify 3x2 slot matrix identity check, S8/S9/S10 recovery plans, and 12-scenario dataset simulation."""
    from deploy.robot.omx import cell_slot_matrix_audit as csma

    # 1. Wrong slot landed (intended C2_R1 -> landed in C3_R1)
    b1 = csma.build_empty_pallet_board(tier=1)
    a1 = csma.build_empty_pallet_board(tier=1)
    b1["slots"]["C1_R1"].update({"occ_ratio": 0.92, "z_top_mm": 29.8, "spec_id": "C3"})
    a1["slots"]["C3_R1"].update({"occ_ratio": 0.90, "z_top_mm": 29.8, "spec_id": "C3"})
    aud_wrong = csma.audit_slot_matrix_identity(b1, a1, pick_slot=(1, 1, 1), target_slot=(2, 1, 1), spec_id="C3")
    assert aud_wrong["passed"] is False
    assert aud_wrong["target_slot_matched"] is False
    assert aud_wrong["failure_code"] == "S8_WRONG_SLOT_LANDED"
    assert aud_wrong["actual_location"] == "C3_R1"
    plan_wrong = csma.compile_slot_recovery_plan(aud_wrong)
    assert plan_wrong["skill"] == "re_pick_wrong_slot_to_target"
    assert plan_wrong["from_wrong_slot"] == [3, 1, 1]
    assert plan_wrong["to_target_slot"] == [2, 1, 1]
    assert len(plan_wrong["directives"]) == 1

    # 2. Dropped in shallow trench (trench_1_2) -> rescue_from_trench_to_temp (2-leg via temp_plate_b)
    a_trench = csma.build_empty_pallet_board(tier=1)
    a_trench["trenches"]["trench_1_2"].update({"occ_ratio": 0.85, "z_top_mm": 11.0, "yaw_deg": -78.0, "tilt_deg": 8.0})
    aud_trench = csma.audit_slot_matrix_identity(b1, a_trench, pick_slot=(1, 1, 1), target_slot=(2, 1, 1), spec_id="C2")
    assert aud_trench["failure_code"] == "S9_DROPPED_IN_TRENCH"
    plan_trench = csma.compile_slot_recovery_plan(aud_trench)
    assert plan_trench["skill"] == "rescue_from_trench_to_temp"
    assert len(plan_trench["directives"]) == 2
    assert plan_trench["directives"][0]["place"]["area"] == "temp_plate_b"

    # 3. Rotated 90 deg transverse in target slot -> reorient_via_temp_plate (-90 deg correction)
    a_rot = csma.build_empty_pallet_board(tier=1)
    a_rot["slots"]["C2_R1"].update({"occ_ratio": 0.85, "z_top_mm": 29.8, "yaw_deg": 0.0})
    aud_rot = csma.audit_slot_matrix_identity(b1, a_rot, pick_slot=(1, 1, 1), target_slot=(2, 1, 1), spec_id="C3")
    assert aud_rot["target_slot_matched"] is True
    assert aud_rot["failure_code"] == "S10_ROTATED_TRANSVERSE_OR_DIAGONAL"
    assert aud_rot["yaw_err_deg"] == pytest.approx(90.0)
    plan_rot = csma.compile_slot_recovery_plan(aud_rot)
    assert plan_rot["skill"] == "reorient_via_temp_plate"
    assert plan_rot["wrist_yaw_correction_deg"] == pytest.approx(-90.0)
    assert plan_rot["reoriented_yaw_deg"] == pytest.approx(-90.0)
    assert len(plan_rot["directives"]) == 2

    # 4. Run full 12-scenario closed-loop catalog & verify dataset export
    sim_summary = csma.simulate_scenario_catalog_and_collect_dataset(out_dir=tmp_path)
    assert sim_summary["total_scenarios"] == 12
    assert sim_summary["recovered_to_nominal_count"] == 11
    assert sim_summary["safe_aborted_count"] == 1
    assert sim_summary["all_resolved_safely"] is True
    assert (tmp_path / "scenario-recovery-dataset.json").exists()


def test_crane_standby_transition_and_multi_zone_redirect():
    """Verify 2-phase crane-lift fold+pan transition and automatic fallback zone redirect on obstruction."""
    pinky_pick = [39.15, -4.32, 8.03, 48.03, -13.36, 58.0]
    standby = [0.0, -27.0, 18.0, 46.0, -5.0, 58.1]
    phases = cell_area_xyz.build_crane_standby_transition(pinky_pick, standby, lift_step=0.032, pan_step=0.045)
    assert len(phases) == 2
    assert phases[0]["phase"] == "crane_lift_fold"
    assert phases[0]["pose"][0] == pytest.approx(39.15)
    assert phases[0]["pose"][1] <= -27.0
    assert phases[0]["pose"][2] >= 22.0
    assert phases[0]["max_step"] == pytest.approx(0.032)
    assert phases[1]["phase"] == "crane_pan_standby"
    assert phases[1]["pose"] == standby
    assert phases[1]["max_step"] == pytest.approx(0.045)

    directive = {
        "arm_id": "arm_s",
        "pick": {"area": "pinky", "col": 2, "row": 1, "tier": 1},
        "place": {"area": "belt", "col": 2, "row": 1, "tier": 1},
    }
    redir = cell_area_xyz.redirect_place_on_zone_obstruction(
        directive,
        obstructed_zones=("belt",),
        fallback_zones=("temp_plate_b", "pallet"),
        lane=2,
        tier=1,
    )
    assert redir["redirected"] is True
    assert redir["redirected_from_area"] == "belt"
    assert redir["redirected_to_area"] == "temp_plate_b"
    assert redir["place"]["area"] == "temp_plate_b"
    assert redir["place"]["col"] == 2


def test_arm_s_zones_wrist_corridor_jaw_gate_and_crane_lift_waypoints():
    import numpy as np
    import cell_spec_recovery_fsm as csrf

    # 1. Yellow table pad (H=22 in HSV, BGR=(40, 215, 235)) is ignored; real orange C3 (BGR=(20, 95, 240)) is detected
    top_img = np.full((480, 640, 3), (40, 215, 235), dtype=np.uint8)
    wrist_img = np.full((480, 640, 3), (40, 215, 235), dtype=np.uint8)

    # SC1: belt_center empty -> S8_EMPTY_PICK_ZONE_REDIRECT
    aud_sc1 = csrf.audit_arm_s_zones_and_wrist_corridor(top_img, wrist_img, expected_zone="belt_center")
    assert aud_sc1["passed"] is False
    assert aud_sc1["failure_code"] == "S8_EMPTY_PICK_ZONE_REDIRECT"
    assert csrf.select_recovery_skill(aud_sc1["failure_code"])["skill"] == "redirect_pick_to_pinky_tray"

    # SC2: Container dropped on pinky_front_floor + visible in wrist left_outside, jaw corridor empty -> S9 & S10
    top_sc2 = top_img.copy()
    top_sc2[215:280, 105:225] = (20, 95, 240)
    wrist_sc2 = wrist_img.copy()
    wrist_sc2[100:360, 25:175] = (20, 95, 240)
    aud_sc2 = csrf.audit_arm_s_zones_and_wrist_corridor(
        top_sc2, wrist_sc2, expected_zone="pinky_tray", require_wrist_corridor=True
    )
    assert aud_sc2["passed"] is False
    assert aud_sc2["failure_code"] == "S9_FLOOR_DROPPED_AND_S10_WRIST_CORRIDOR_MISALIGNED"
    assert csrf.select_recovery_skill(aud_sc2["failure_code"])["skill"] == "redirect_pick_to_belt_far"

    # SC3: Real C3 container on belt_far + centered in wrist jaw corridor -> PASS
    top_sc3 = top_img.copy()
    top_sc3[110:185, 530:635] = (20, 95, 240)
    wrist_sc3 = wrist_img.copy()
    wrist_sc3[140:370, 215:435] = (20, 95, 240)
    aud_sc3 = csrf.audit_arm_s_zones_and_wrist_corridor(
        top_sc3, wrist_sc3, expected_zone="belt_far", require_wrist_corridor=True
    )
    assert aud_sc3["passed"] is True
    assert aud_sc3["failure_code"] is None
    assert aud_sc3["wrist_corridor"]["corridor_centered"] is True

    # 2. Jaw telemetry gate: empty air (<51.0), valid 30mm C3 hold (51.0..57.2), wedged/rim bite (>57.2)
    assert csrf.audit_grasp_jaw_gate(48.82)["failure_code"] == "S11_EMPTY_JAW_CLOSURE_AIR_GRASP"
    assert csrf.audit_grasp_jaw_gate(54.19)["passed"] is True
    assert csrf.audit_grasp_jaw_gate(57.85)["failure_code"] == "S12_WEDGED_OR_RIM_BITE"

    # 3. Crane lift waypoints from full extension (b_far) cap upward shoulder_lift step to 0.021 (0.63 u/s)
    wps = csrf.compile_crane_lift_waypoints(
        [-27.685, 6.538, -9.91, 53.457, 17.882, 46.5],
        [0.0, -27.0, 18.0, 46.0, -5.0, 46.5],
        full_extension=True,
    )
    assert len(wps) == 2
    assert wps[0]["max_step"] == pytest.approx(0.021)
    assert wps[0]["pose"][1] == pytest.approx(-16.0)
    assert wps[1]["max_step"] == pytest.approx(0.045)










