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

    # Case 3: Top view shows container placed horizontally (ê°€ë¡œ, horizontal_ew) when vertical (ì„¸ë¡œ, yaw=-90) is required
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


def test_fused_hover_alignment_and_smooth_rail_belt_retract(tmp_path, monkeypatch):
    import cell_area_vision_align as align
    import cell_realignment_pipeline as crp

    directive = build_directive(
        arm_id="arm_b",
        pick={"area": "pallet", "col": 3, "row": 1, "tier": 1, "x": 0.1935, "y": -0.003, "z": 0.0074},
        place={"area": "pallet", "col": 2, "row": 1, "tier": 1},
        vision_refine=True,
    )
    calls = []
    replans = []
    side_obs = {"found": True, "within_zone": True, "dx_m": 0.004}
    wrist_obs = {"found": True, "along_mm": 5.0, "across_mm": 3.0}
    monkeypatch.setattr(align, "measure_side_gripper_zone_offset", lambda *a, **k: side_obs)
    monkeypatch.setattr(align.cell_fingers, "resolve_wrist_servo_offset", lambda *a, **k: wrist_obs)

    def plan_once(cur, base, **kwargs):
        replans.append(list(cur["pick"]["effective_xyz_m"]))
        return {"compiled": True}, {"pick": {"yaw_deg": -90}, "grip_open": 58.2}, {}

    monkeypatch.setattr(align, "plan_library_from_directive", plan_once)
    def act(cmd):
        calls.append(cmd)
        return {"ok": True, "state": [0, 0, 0, 0, 0, 58.2]}

    lib, plan, cal, obs, refined = align.refine_pick_pose_at_hover(
        cur_directive=directive, base_plan=SAMPLE_BASE_PLAN, lib={},
        plan={"pick": {"yaw_deg": -90}, "grip_open": 58.2}, cal={},
        lib_path=tmp_path / "test.library.json", work_dir=tmp_path, kinematics_root=None,
        arm_id="arm_b", exec_cfg={"vision_refine": True, "wrist_samples": 1},
        frame_fn=lambda camera: object(), before_side=object(), above_shaking=False,
        run_cmd=act, wrist_log=[],
    )
    assert refined and obs == wrist_obs
    assert len(replans) == 1
    assert len([cmd for cmd in calls if cmd.startswith("load ")]) == 1
    assert calls.count("goto above_pick") == 1
    assert replans[0][0] != pytest.approx(0.1935)
    assert replans[0][1] != pytest.approx(-0.003)

    calls.clear()
    replans.clear()
    align.refine_pick_pose_at_hover(
        cur_directive=directive, base_plan=SAMPLE_BASE_PLAN, lib={},
        plan={"pick": {"yaw_deg": -90}, "grip_open": 58.2}, cal={},
        lib_path=tmp_path / "test.library.json", work_dir=tmp_path, kinematics_root=None,
        arm_id="arm_b", exec_cfg={"vision_refine": True, "wrist_passes": 2},
        frame_fn=lambda camera: object(), before_side=object(), above_shaking=False,
        run_cmd=act, wrist_log=[],
    )
    assert len(replans) == 2 and calls.count("goto above_pick") == 2

    phases = crp.compile_rail_and_belt_safe_standby_waypoints(
        [-22.98, -11.55, 37.73, 44.27, 22.1, 59.32]
    )
    assert all(phase["smooth_frames"][-1] == phase["pose"] for phase in phases)
    frames = phases[0]["combined_smooth_frames"]
    assert frames[-1] == phases[-1]["pose"]
    assert all(max(abs(a - b) for a, b in zip(left, right)) < 0.2
               for left, right in zip(frames, frames[1:]))


def test_chained_post_place_keeps_audit_steps(tmp_path):
    directive = build_directive(
        arm_id="arm_b",
        pick={"area": "pallet", "col": 3, "row": 1, "tier": 1},
        place={"area": "pallet", "col": 2, "row": 1, "tier": 1},
        vision_refine=False,
    )
    directive["execution"] = {"chain_post_place": True}
    called = []

    def act(cmd):
        called.append(cmd)
        return {"ok": True, "holding": True, "state": [0, -10, 15, 45, 41, 54.36], "gripper_current_ma": 172.0}

    result = cell_area_xyz.execute_directive(
        directive, base_plan=SAMPLE_BASE_PLAN, work_dir=tmp_path, act_fn=act, max_attempts=1,
    )
    assert result["result"] == "placed"
    assert called.count("chain run lift_place ; park") == 1
    assert "run lift_place" not in called and "park" not in called
    assert [step["command"] for step in result["steps"]][-3:] == [
        "chain run lift_place ; park", "run lift_place", "park",
    ]


def test_stay_in_hover_macro_stops_before_place_and_release(tmp_path):
    directive = build_directive(
        arm_id="arm_b",
        pick={"area": "pallet", "col": 3, "row": 1, "tier": 2},
        place={"area": "pallet", "col": 2, "row": 1, "tier": 3},
        vision_refine=False,
    )
    directive["execution"] = {"stay_in_hover": True}
    commands = []

    def act(cmd):
        commands.append(cmd)
        return {"ok": True, "holding": True, "state": [0, -10, 15, 45, 41, 54.36], "gripper_current_ma": 172.0}

    result = cell_area_xyz.execute_directive(
        directive, base_plan=SAMPLE_BASE_PLAN, work_dir=tmp_path, act_fn=act, max_attempts=1,
    )
    assert "goto above_place" in commands
    assert "run descend_place" not in commands
    assert "run release_place" not in commands
    assert "run lift_place" not in commands
    assert "park" not in commands
    assert result["result"] == "hover"
    assert result["steps"][-1]["command"] == "goto above_place"
