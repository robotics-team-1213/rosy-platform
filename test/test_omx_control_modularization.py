from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np

OMX_DIR = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
ADAPTER_DIR = Path(__file__).resolve().parents[1] / "middleware/devices/omx/adapter"
FOUNDATION_DIR = Path(__file__).resolve().parents[1] / "contracts/foundation"
VISION_INGRESS_DIR = Path(__file__).resolve().parents[1] / "operations/overhead"
for _p in (OMX_DIR, ADAPTER_DIR, FOUNDATION_DIR, VISION_INGRESS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_area_recovery as car  # noqa: E402
import cell_area_xyz  # noqa: E402
import cell_area_zones as caz  # noqa: E402
import cell_control_core as ccc  # noqa: E402
import cell_fingers as cf  # noqa: E402
import cell_fleet_pipeline as cfp  # noqa: E402
import cell_problem_pipeline as cpp  # noqa: E402
import cell_rl_policy as crp  # noqa: E402
import cell_task_runner as ctr  # noqa: E402
import grasp_planner as gp  # noqa: E402
import vla_handover_broker as vhb  # noqa: E402


def test_reexports_preserve_public_entrypoints() -> None:
    """All refactored modules preserve 100% backward-compatible symbol identity."""
    assert gp.rad_to_norm is ccc.rad_to_norm
    assert gp.norm_to_rad is ccc.norm_to_rad
    assert vhb.clamp_lerobot_norm_action is ccc.clamp_lerobot_norm_action
    assert vhb.compute_stud_release_residual is ccc.compute_stud_release_residual
    assert cell_area_xyz.build_plan_from_directive is ccc.build_plan_from_directive
    assert cell_area_xyz.plan_library_from_directive is ccc.plan_library_from_directive
    assert cell_area_xyz.sim_precheck_and_optimize_directive is ccc.sim_precheck_and_optimize_directive
    assert cell_area_xyz.execute_task_plan is cfp.execute_task_plan
    assert caz.diagnose_and_recover_pick is car.diagnose_and_recover_pick
    assert cell_area_xyz.diagnose_and_recover_pick is car.diagnose_and_recover_pick
    assert cpp.update_il_rl_from_run is crp.update_il_rl_from_run
    assert cpp.apply_learned_il_rl_residual is crp.apply_learned_il_rl_residual
    assert ctr.FleetModelPipeline is cfp.FleetModelPipeline
    assert vhb.FleetModelPipeline is cfp.FleetModelPipeline


def test_control_core_workspace_clamping_and_wrist_step() -> None:
    """`apply_wrist_xy_step` projects along/across offsets by `yaw_deg`, honors `finger_sign['across']`, and clamps per arm."""
    xyz_s = ccc.apply_wrist_xy_step(
        [0.0535, 0.1720, 0.0200],
        {"found": True, "dx_mm": -10.0, "dy_mm": 4.0},
        arm_id="arm_s",
        yaw_deg=-85.0,
        use_direct_structural_gain=True,
    )
    assert xyz_s[0] == round(0.0535 - 0.50 * 0.004, 5)
    assert xyz_s[1] == round(0.1720 + 0.65 * 0.010, 5)

    # Test across sign propagation via `project_wrist_offset_xy_m`
    dx_pos, dy_pos = ccc.project_wrist_offset_xy_m(
        {"along_mm": 0.0, "across_mm": 10.0},
        arm_id="arm_b",
        yaw_deg=-90.0,
        cal={"finger_sign": {"along": -1.0, "across": -1.0}},
        gain_along=0.60,
        gain_across=0.50,
    )
    assert dx_pos == 0.0
    assert dy_pos == -0.005

    xyz_b = ccc.apply_wrist_xy_step(
        [0.0560, 0.1540, 0.0085],
        {"found": True, "along_mm": 20.0},
        arm_id="arm_b",
        cal={"finger_sign": {"along": -1.0}},
        yaw_deg=-90.0,
        gain_along=0.60,
    )
    assert xyz_b[0] == 0.0550
    assert abs(xyz_b[1]) <= 0.1550


def test_rl_speed_scale_wired_into_build_plan(tmp_path: Path) -> None:
    """`rl_speed_scale` from `apply_learned_il_rl_residual` scales `transit_speed` and `lift_m_s` within safe bounds."""
    base_plan = json.loads((OMX_DIR / "grasp-plan.example.json").read_text(encoding="utf-8"))
    directive = {
        "schema": "rosy.omx-cell-area-xyz-directive.v1",
        "directive_id": "test-rl-speed",
        "arm_id": "arm_s",
        "pick": {"area": "pinky", "x": 0.0535, "y": 0.1720, "z": 0.0200, "yaw_deg": -85.0},
        "place": {"area": "belt", "x": 0.1250, "y": -0.0550, "z": 0.0250, "yaw_deg": -85.0},
        "execution": {"rl_speed_scale": 1.15},
    }
    plan, _ = ccc.build_plan_from_directive(directive, base_plan, work_dir=tmp_path)
    assert plan["rl_speed_scale"] == 1.15
    assert plan["transit_speed"] > float(base_plan.get("transit_speed", 0.82))
    assert plan["transit_speed"] <= 0.85  # the loader refuses a faster library


def test_across_mm_classified_and_recorded_in_problem_pipeline() -> None:
    """Large `across_mm` wrist offsets are classified as `wrist_offset_or_visual_hazard` and stored in `sim_reproducer`."""
    cat = cpp.classify_problem(fail_stage="run grasp_pick", wrist_obs={"along_mm": 0.4, "across_mm": -4.2})
    assert cat == "wrist_offset_or_visual_hazard"
    case = cpp.build_problem_case(arm_id="arm_s", vision={"along_mm": 0.4, "across_mm": -4.2})
    assert case["sim_reproducer"]["initial_across_offset_mm"] == -4.2


def test_resolve_wrist_servo_offset_structural_fallback_and_auto_color() -> None:
    """`resolve_wrist_servo_offset` handles `finger_color='auto'` and falls back to `structural_container_between_fingers`."""
    img = np.full((480, 640, 3), 38, dtype=np.uint8)
    img[10:340, 180:450] = (150, 195, 235)
    obs = cf.resolve_wrist_servo_offset(img, {"finger_color": "auto"}, prefer_structural=True)
    assert obs["found"] is True
    assert obs["mode"] == "structural"
    assert "along_mm" in obs and "across_mm" in obs
    assert obs["views_consistent"] is True


def test_hybrid_knn_il_rl_residual_and_fleet_handover_barrier(tmp_path: Path) -> None:
    """`knn_il_residual` interpolates `il-demos.jsonl` via RBF kernel and `FleetModelPipeline` enforces handover barrier."""
    il_path = tmp_path / "il-demos.jsonl"
    il_path.write_text(
        json.dumps({
            "t": 1.0,
            "bucket": "pinky_horiz",
            "state": [0.0535, 0.1720, 0.0200, -85.0, 1],
            "expert_action_xyz": [0.0565, 0.1700, 0.0200],
            "place_xyz": [0.1250, -0.0550, 0.0250],
            "reward": 1.8,
            "verified": True,
        })
        + "\n",
        encoding="utf-8",
    )
    il_res = crp.knn_il_residual(tmp_path, "pinky_horiz", [0.0540, 0.1720, 0.0200])
    assert il_res is not None
    assert il_res["dx_m"] == 0.003
    assert il_res["dy_m"] == -0.002

    # Without rl-policy.json, apply_learned_il_rl_residual still applies the IL k-NN residual!
    d = {
        "arm_id": "arm_s",
        "pick": {"area": "pinky", "x": 0.0535, "y": 0.1720, "z": 0.0200, "effective_xyz_m": [0.0535, 0.1720, 0.0200]},
    }
    d_out = crp.apply_learned_il_rl_residual(tmp_path, d)
    assert d_out["pick"]["x"] == round(0.0535 + 0.003, 5)
    assert d_out["pick"]["y"] == round(0.1720 - 0.002, 5)

    # Test FleetModelPipeline parallel pre-staging & handover barrier
    pipe = cfp.FleetModelPipeline(tmp_path)
    mission = pipe.run_fleet_mission(shuttle_cycles=2, stack_tiers=(1,))
    assert mission["handover_barrier_ok"] is True
    assert mission["prestaged_count"] == 1
    assert mission["stages"][-1].get("handover_prestaged") is True


def test_belt_intercept_tactile_compliance_and_object_pose_split(tmp_path: Path) -> None:
    """Verify the 3 Round-3 Codex-orchestrated upgrades:
    1) Dynamic belt intercept (`predict_moving_belt_intercept`)
    2) Tactile compliance & early touchdown (`evaluate_tactile_place_compliance`)
    3) `cell_object_pose.py` / `cell_objects.py` split & backward compatibility."""
    import cell_object_pose as cop
    import cell_objects as cob

    # 1. Dynamic belt intercept
    res_ok = ccc.predict_moving_belt_intercept(
        {"t": 1.0, "x": 0.120, "y": -0.060},
        {"t": 1.2, "x": 0.128, "y": -0.056},
        lead_time_s=0.25,
        arm_id="arm_a",
    )
    assert res_ok["ok"] is True
    assert res_ok["intercept_xy_m"] == (0.138, -0.051)
    assert res_ok["abort_reason"] is None

    res_fast = ccc.predict_moving_belt_intercept(
        {"t": 1.0, "x": 0.120, "y": -0.060},
        {"t": 1.1, "x": 0.150, "y": -0.060},
        lead_time_s=0.20,
        arm_id="arm_a",
        max_speed_m_s=0.12,
    )
    assert res_fast["ok"] is False
    assert res_fast["abort_reason"] == "belt_speed_exceeds_limit"

    pipe = cfp.FleetModelPipeline(tmp_path)
    pre_dyn = pipe.prestage_cell_ab_handover(
        tier=1,
        belt_obs=({"t": 0.0, "x": 0.122, "y": -0.058}, {"t": 0.2, "x": 0.126, "y": -0.054}),
        lead_time_s=0.25,
    )
    assert pre_dyn["ok"] is True
    assert pre_dyn["intercept"]["intercept_xy_m"] == (0.131, -0.049)

    # 2. Tactile place compliance
    tac_full = ccc.evaluate_tactile_place_compliance({"ok": True}, target_z_m=0.0085, current_z_m=0.0085)
    assert tac_full["compliant"] is True and tac_full["early_touchdown"] is False

    tac_early = ccc.evaluate_tactile_place_compliance(
        {"ok": False, "error": "contact in descend_place"},
        target_z_m=0.0085,
        current_z_m=0.0102,
        holding=True,
    )
    assert tac_early["compliant"] is True and tac_early["early_touchdown"] is True

    tac_high_crash = ccc.evaluate_tactile_place_compliance(
        {"ok": False, "error": "contact in descend_place"},
        target_z_m=0.0085,
        current_z_m=0.0250,
        holding=True,
    )
    assert tac_high_crash["compliant"] is False

    # 3. `cell_object_pose` / `cell_objects` re-export parity
    for sym in ("to_mm", "measure", "colour_name", "colour_tag", "container_structure", "decision_ai_verify", "top_face", "outline"):
        assert getattr(cob, sym) is getattr(cop, sym)

    # 4. Contract-gated OMX handoff stage execution (`rosy.fleet-r-cell-contract.v1`)
    locked_handoff = {
        "handoff_lease_id": "cell_s:pinky_1:16",
        "cell_id": "cell_s",
        "station_place": "S3",
        "robot_id": "pinky_1",
        "wheel_brake_locked": True,
        "bed_ready": True,
        "v_cmd_mps": 0.0,
    }
    res_contract = pipe.run_contract_handoff_stage(locked_handoff, stage_id="handoff-s3-1")
    assert res_contract["contract_version"] == "rosy.fleet-r-cell-contract.v1"
    assert res_contract["receipt"]["phase"] == "RELEASED"
    assert res_contract["receipt"]["amr_motion_inhibited"] is False
    assert res_contract["receipt"]["goal_evidence_digest"].startswith("sha256:")

    moving_handoff = {**locked_handoff, "v_cmd_mps": 0.05}
    res_aborted = pipe.run_contract_handoff_stage(moving_handoff, stage_id="handoff-s3-bad")
    assert res_aborted["receipt"]["phase"] == "ABORTED"
    assert res_aborted["receipt"]["reason"] == "AMR_NOT_LOCKED_AT_HANDOFF"
    assert res_aborted["stage_result"] is None


def test_round4_runner_guards_pipeline_stages_auto_safety_and_debate_consensus() -> None:
    """Verify Round-4 Codex-orchestrated modular splits and control upgrades:
    1) `chunk_runner_guards` adaptive contact guard & command builders
    2) `cell_pipeline_stages` / `cell_pipeline` re-export parity
    3) `cell_auto_safety` / `cell_auto_pick` candidate quality scoring (`score_pick_candidate`)
    4) `cell_grasp_debate` consensus evidence weighting (`compute_consensus_evidence_weight`)."""
    import cell_auto_pick as cap
    import cell_auto_safety as cas
    import cell_grasp_debate as cgd
    import cell_pipeline as cp
    import cell_pipeline_stages as cps
    import chunk_runner_guards as crg
    import chunk_runner_run as crr

    # 1. `chunk_runner_guards` adaptive contact guard
    assert crr.contact_limits is crg.contact_limits
    _, ticks, tripped, lag = crg.evaluate_adaptive_contact_guard(
        [2.0, 6.2, 1.5, 1.0, 0.5],
        contact_start=[5.5, 5.5, 5.5, 5.5, 5.5],
        contact_ticks=0,
        step_delta_units=6.0,
    )
    assert tripped is False and ticks == 0 and lag == 6.2
    moved = crg.build_jog_target(["jog", "shoulder_pan.pos", "2.5"], [0.0] * 6, [0.0] * 6)
    assert moved[0] == 2.5

    # 2. `cell_pipeline_stages` / `cell_pipeline` re-export parity
    for sym in ("calibrate", "scene", "grip_to", "coarse_map", "start_reference", "at_start", "reset", "grasp_yaw", "recover"):
        assert getattr(cp, sym) is getattr(cps, sym)

    # 3. `cell_auto_safety` / `cell_auto_pick` candidate scoring & re-exports
    for sym in ("session_caps", "Aborted", "Monitor", "Guarded", "object_sized", "finger_room", "after_failure", "square_entry", "open_episode", "close_episode"):
        assert getattr(cap, sym) is getattr(cas, sym)
    s_clear = cas.score_pick_candidate(
        {"object": {"jaw_margin_mm": 11.0, "raw_m": [0.06, 0.17], "structure": {"shape_score": 0.92}}},
        start_xy=(0.05, 0.17),
    )
    s_tight = cas.score_pick_candidate(
        {"object": {"jaw_margin_mm": 2.0, "raw_m": [0.18, 0.05], "structure": {"shape_score": 0.58}, "split_from": 2}},
        start_xy=(0.05, 0.17),
    )
    assert s_clear > s_tight

    # 4. `cell_grasp_debate` consensus evidence weighting
    assert cgd.compute_consensus_evidence_weight({}) == 1.0
    w_high = cgd.compute_consensus_evidence_weight({}, il_confidence=0.95, shape_score=0.92)
    w_low = cgd.compute_consensus_evidence_weight({}, il_confidence=0.10, shape_score=0.35)
    assert w_high > 1.0 > w_low
    dec = cgd.debate_and_decide(
        stage="run grasp_pick",
        telemetry={"verdict": "proceed", "class": "stable", "reason": "ok"},
        vision={"verdict": "reinsert", "class": "unstable_skewed", "dx_mm": 4.0, "dy_mm": -2.0, "reason": "skew"},
        il_confidence=0.10,
        shape_score=0.35,
    )
    assert dec["verdict"] == "reinsert_and_retry"
    assert dec["evidence_weight"] == w_low
    assert abs(dec["dx_mm"]) < 4.0


def test_6dof_se3_ik_and_7dof_nullspace_redundancy_and_fleet_stages(tmp_path: Path) -> None:
    """Verify 5-DOF, 6-DOF (SE(3) tilted pose), and 7-DOF (Null-Space elbow swivel & obstacle clearance)
    kinematics, N-DOF jitter suppression, 6D RL orientation residuals, and Fleet execution."""
    import math
    import cell_rl_policy as crp
    import joint_jitter as jj
    import multi_dof_kinematics as mdk

    # 1. 6-DOF full SE(3) IK on a tilted container/tray pose (roll=6 deg, pitch=82 deg, yaw=-85 deg)
    ik6 = mdk.solve_se3_ik([0.165, 0.045, 0.035], [6.0, 82.0, -85.0], dof=6)
    assert ik6["ok"] is True
    assert ik6["dof"] == 6 and len(ik6["joints_rad"]) == 6
    assert ik6["pos_error_mm"] < 1.2 and ik6["rot_error_deg"] < 1.0

    # 2. 7-DOF Null-Space Redundancy: swiveling elbow (psi = +0.55 vs -0.55 rad) moves elbow >40 mm while keeping TCP invariant
    ik7_pos = mdk.solve_se3_ik([0.165, 0.045, 0.035], [4.0, 84.0, -85.0], dof=7, psi_target_rad=0.55)
    ik7_neg = mdk.solve_se3_ik([0.165, 0.045, 0.035], [4.0, 84.0, -85.0], dof=7, psi_target_rad=-0.55)
    assert ik7_pos["ok"] is True and ik7_neg["ok"] is True
    assert len(ik7_pos["joints_rad"]) == 7
    elbow_shift_mm = math.dist(ik7_pos["elbow_xyz_m"], ik7_neg["elbow_xyz_m"]) * 1000.0
    assert elbow_shift_mm > 25.0
    assert ik7_pos["pos_error_mm"] < 1.5 and ik7_neg["pos_error_mm"] < 1.5

    # 3. N-DOF Jitter Suppression & Frame DOF Inference (7-element for 6-DOF, 8-element for 7-DOF)
    chunk7 = mdk.plan_se3_chunk([0.16, 0.04, 0.06], [0.16, 0.04, 0.03], dof=7, steps=20, psi_target_rad=0.35)
    assert chunk7["ok"] is True
    assert ccc.infer_frame_dof(chunk7["frames"][0]) == 7
    damped7 = jj.suppress_tremor(chunk7["frames"], vmax=5.0, fps=30)
    assert len(damped7[0]) == 8
    assert damped7[0] == chunk7["frames"][0] and damped7[-1] == chunk7["frames"][-1]

    # 4. 6-DOF RL Orientation Residual & 6-DOF / 7-DOF Fleet Stage Execution
    crp.update_il_rl_from_run(
        tmp_path,
        {
            "arm_id": "arm_s",
            "pick": {"area": "pinky", "x": 0.0535, "y": 0.1720, "z": 0.0200, "yaw_deg": -85.0, "effective_xyz_m": [0.0535, 0.1720, 0.0200]},
            "place": {"area": "belt", "x": 0.1250, "y": -0.0550, "z": 0.0250, "effective_xyz_m": [0.1250, 0.0550, 0.0250]},
            "result": "placed",
            "task_verified": True,
            "measured_rpy_offset_deg": [2.5, -3.0, 1.5],
        },
    )
    d6 = crp.apply_learned_il_rl_residual(
        tmp_path,
        {"arm_id": "arm_s", "pick": {"area": "pinky", "x": 0.0535, "y": 0.1720, "z": 0.0200, "yaw_deg": -85.0, "effective_xyz_m": [0.0535, 0.1720, 0.0200]}},
    )
    assert d6["pick"]["roll_deg"] == 1.0 and d6["pick"]["pitch_deg"] == 86.8

    pipe = cfp.FleetModelPipeline(tmp_path)
    st6 = pipe.run_fleet_stage(arm_id="arm_s", src_site="pinky", dst_site="belt", dof=6, tilt_rpy_deg=(4.0, 84.0, -85.0))
    st7 = pipe.run_fleet_stage(arm_id="arm_a", src_site="belt", dst_site="pallet-l0", dof=7, elbow_swivel_psi_rad=0.40)
    assert st6["dof"] == 6 and st6["multi_dof_ik"]["ok"] is True and st6["damped_endpoint_exact"] is True
    assert st7["dof"] == 7 and st7["multi_dof_ik"]["ok"] is True and st7["damped_endpoint_exact"] is True


def test_round5_session_incident_upkeep_bridge_and_finger_modularization(tmp_path: Path) -> None:
    """Verify Round 5 extracted modules (`record_session_helpers`, `joint_tune_lock`, `omx_incident_fleet`,
    `cell_upkeep_checks`, `workcell_incident_client`, `cell_finger_container`) and N-DOF upkeep/incident support."""
    import json
    import cell_finger_container as cfc
    import cell_fingers as cf
    import cell_upkeep as cu
    import cell_upkeep_checks as cuc
    import joint_tune as jt
    import joint_tune_lock as jtl
    import omx_incident as oi
    import omx_incident_fleet as oif
    import record_session as rs
    import record_session_helpers as rsh

    assert rs.CARD_SCHEMA == rsh.CARD_SCHEMA
    assert set(jtl.follower_map_for_dof(5)) == {11, 12, 13, 14, 15, 16}
    assert set(jtl.follower_map_for_dof(6)) == {11, 12, 13, 14, 15, 16, 17}
    assert set(jtl.follower_map_for_dof(7)) == {11, 12, 13, 14, 15, 16, 17, 18}
    assert jt.FOLLOWER_BY_DOF[7][18] == (1060, 4)
    assert oi.hold_path is oif.hold_path
    assert cu.check_jaw_open is cuc.check_jaw_open
    assert cf.structural_container_between_fingers is cfc.structural_container_between_fingers

    # 7-DOF trace frame jaw open check (`sent` and `present` length 8, gripper at index -1)
    trace7 = tmp_path / "trace-arm_s-7dof.jsonl"
    trace7.write_text(
        json.dumps({"sent": [0.0] * 7 + [58.0], "present": [0.0] * 7 + [57.6]}) + "\n",
        encoding="utf-8",
    )
    res_open = cuc.check_jaw_open([trace7], {})
    assert res_open["status"] == "ok" and "57.60" in res_open["detail"]

    # 7-DOF home posture folded check in `omx_incident.facts`
    io_dir = tmp_path / "io7"
    io_dir.mkdir()
    home7 = [0.0, -58.0, 0.0, 50.0, 50.0, -5.0, 0.0, 47.0]
    (io_dir / "chunk-status.jsonl").write_text(
        json.dumps({"command": "run park", "ok": True, "state": [0.5, -57.5, 0.4, 50.2, 49.8, -4.8, 0.2, 47.0], "t": 10.0}) + "\n",
        encoding="utf-8",
    )
    f7 = oi.facts({"safe_end": True, "started": 1.0, "chunks": {"io": str(io_dir)}}, home=home7, arm="arm_s")
    assert f7["folded"] is True


def test_round6_single_responsibility_splits_and_ndof_judges(tmp_path: Path) -> None:
    """Verify Round 6 Single-Responsibility Principle (SRP) module splits:
    - `cell_grasp_judges` / `cell_grasp_debate` (including 6-DOF/7-DOF `telemetry_judge`)
    - `omx_autoupdate_host` / `omx_autoupdate`
    - `guarded_native_cli` / `guarded_native`
    - `chunk_runner_commands` / `chunk_runner_run`
    - `vla_handover_stages` / `vla_handover_broker`
    - `cell_fleet_handoff` / `cell_fleet_pipeline`
    - `probe_cell_transfer_grant` / `probe_cell_transfer`."""
    import cell_fleet_handoff as cfh
    import cell_grasp_debate as cgd
    import cell_grasp_judges as cgj
    import chunk_runner_commands as crc
    import chunk_runner_run as crr
    import guarded_native as gn
    import guarded_native_cli as gnc
    import omx_autoupdate as oau
    import omx_autoupdate_host as oah
    import probe_cell_transfer as pct
    import probe_cell_transfer_grant as pctg
    import vla_handover_stages as vhs

    assert cgd.telemetry_judge is cgj.telemetry_judge
    assert cgd.vision_judge is cgj.vision_judge
    assert cgd.compute_consensus_evidence_weight is cgj.compute_consensus_evidence_weight
    assert oau.Host is oah.Host
    assert oau.DEFAULT_PATHS == oah.DEFAULT_PATHS
    assert gn.run_native is gnc.run_native
    assert crr.dispatch_runner_command is crc.dispatch_runner_command
    assert vhb.run_hybrid_stack_stage is vhs.run_hybrid_stack_stage
    assert vhb.run_3tier_hybrid_plan is vhs.run_3tier_hybrid_plan
    assert cfp.execute_task_plan is cfh.execute_task_plan
    assert cfp.run_contract_handoff_stage is cfh.run_contract_handoff_stage
    assert cfp.scan_cell_s_extended_zones is cfh.scan_cell_s_extended_zones
    assert cfp.build_crane_recovery_trajectory is cfh.build_crane_recovery_trajectory
    assert pct.build_probe_grant is pctg.build_probe_grant
    assert pct.evaluate_placement is pctg.evaluate_placement

    # 7-DOF telemetry_judge uses gripper at index -1 (`state[7]`)
    import cell_arm_cal as cac
    import cell_grasp_dynamics as cg_dyn

    assert cac.evaluate_grasp_dynamics is cg_dyn.evaluate_grasp_dynamics
    assert cac.infer_holding is cg_dyn.infer_holding
    params = {"gripper.held_30mm": 55.7, "grasp.shallow_tol_units": 1.2, "grasp.wedged_tol_units": 0.7}
    t7_ok = cgj.telemetry_judge([0.0] * 7 + [55.4], True, params)
    t7_shallow = cgj.telemetry_judge([0.0] * 7 + [52.2], True, params)
    assert t7_ok["verdict"] == "proceed" and t7_ok["class"] == "stable"
    assert t7_shallow["verdict"] == "reinsert" and t7_shallow["class"] == "unstable_shallow"
    assert cg_dyn.infer_holding({"state": [0.0] * 7 + [55.4], "gripper_current_ma": 95.0}) is True


def test_round7_single_responsibility_splits_and_ndof_clamp() -> None:
    """Verify Round 7 Single-Responsibility Principle (SRP) module splits and 5/6/7-DOF action clamping:
    - `cell_directive_compiler` / `cell_control_core`
    - `cell_area_vision_align` / `cell_area_xyz`
    - `two_arm_stages_readonly` / `two_arm_pipeline`
    - `probe_pilot_sim_gz` / `probe_pilot_sim_http`
    - `commissioning_view_assets` / `commissioning_view`
    - `omx_cameras_sync` / `omx_cameras`
    - `cell_calibrate_auto` / `cell_calibrate`
    - `sim_pick_place_teacher_helpers` / `sim_pick_place_teacher`
    - `cell_auto_pick_plan` / `cell_auto_pick`
    - `workcell_observation_sources` / `workcell_observation_bridge`
    - `guarded_native_effort` / `guarded_native`
    - `joint_tune_cli` / `joint_tune`
    - `record_session_cli` / `record_session`
    - `chunk_runner_settle` / `chunk_runner_run`."""
    import cell_area_vision_align as cava
    import cell_auto_pick as cap
    import cell_auto_pick_plan as capp
    import cell_calibrate as cc
    import cell_calibrate_auto as cca
    import cell_directive_compiler as cdc
    import chunk_runner_run as crr
    import chunk_runner_settle as crs
    import commissioning_view as cv
    import commissioning_view_assets as cva
    import guarded_native as gn
    import guarded_native_effort as gne
    import joint_tune as jt
    import joint_tune_cli as jtc
    import omx_cameras as oc
    import omx_cameras_sync as ocs
    import probe_pilot_sim_gz as ppsg
    import probe_pilot_sim_http as ppsh
    import record_session as rs
    import record_session_cli as rsc
    import sim_pick_place_teacher as sppt
    import sim_pick_place_teacher_helpers as sppth
    import two_arm_pipeline as tap
    import two_arm_stages_readonly as tasr
    import workcell_observation_bridge as wob
    import workcell_observation_sources as wos

    assert ccc.build_plan_from_directive is cdc.build_plan_from_directive
    assert ccc.sim_precheck_and_optimize_directive is cdc.sim_precheck_and_optimize_directive
    assert cell_area_xyz.settle_above_pick_jaws is cava.settle_above_pick_jaws
    assert cell_area_xyz.refine_pick_pose_at_hover is cava.refine_pick_pose_at_hover
    assert tap.stage_health is tasr.stage_health
    assert tap.write_receipt is tasr.write_receipt
    assert ppsh.gz_spawner is ppsg.gz_spawner
    assert ppsh.terminal_facts is ppsg.terminal_facts
    assert cv.parse_arm_topics is cva.parse_arm_topics
    assert cv.PAGE == cva.PAGE
    assert oc.sync_manifest is ocs.sync_manifest
    assert oc.apply_decisions is ocs.apply_decisions
    assert cc.self_calibrate is cca.self_calibrate
    assert cc.learn_bias is cca.learn_bias
    assert sppt.teacher_watchdog_evidence is sppth.teacher_watchdog_evidence
    assert sppt.release_clearance_evidence is sppth.release_clearance_evidence
    assert cap.observe is capp.observe
    assert cap.choose is capp.choose
    assert cap.verify_placed is capp.verify_placed
    assert wob.select_sources is wos.select_sources
    assert wob.NativeSource is wos.NativeSource
    assert gn.check_hardware_errors is gne.check_hardware_errors
    assert gn.seed_follower_pose is gne.seed_follower_pose
    assert callable(jt.main) and callable(jtc.main) and jt._jtc is jtc
    assert callable(rs.main) and callable(rsc.main) and rs._rsc is rsc
    assert crr.check_chunk_settled is crs.check_chunk_settled
    assert crr.check_runner_idle is crs.check_runner_idle

    # 5-DOF, 6-DOF, and 7-DOF action vector clamping (`len(action) in (6, 7, 8)`)
    c5 = ccc.clamp_lerobot_norm_action([10.0] * 5 + [-15.0], [0.0] * 5 + [60.0], dt_s=0.5, max_units_per_s=5.0)
    c6 = ccc.clamp_lerobot_norm_action([10.0] * 6 + [-15.0], [0.0] * 6 + [60.0], dt_s=0.5, max_units_per_s=5.0)
    c7 = ccc.clamp_lerobot_norm_action([10.0] * 7 + [-15.0], [0.0] * 7 + [60.0], dt_s=0.5, max_units_per_s=5.0)
    assert len(c5) == 6 and c5[0] == 2.5 and c5[-1] == 57.5
    assert len(c6) == 7 and c6[5] == 2.5 and c6[-1] == 57.5
    assert len(c7) == 8 and c7[6] == 2.5 and c7[-1] == 57.5
    assert cava._jaw_pos([0.0] * 7 + [55.2]) == 55.2


def test_all_omx_control_modules_under_400_lines() -> None:
    """Every single `.py` module in `deploy/robot/omx/` is decomposed into Single-Responsibility units (< 400 lines)."""
    for path in sorted(OMX_DIR.glob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) < 400, f"{path.name} has {len(lines)} lines (>= 400)"


def test_all_omx_ecosystem_modules_under_500_lines() -> None:
    """Every non-test `.py` module across the entire OMX ecosystem (`tools/sim/omx_*.py`, `learning/curation/omx`,
    `learning/envs/isaac`, `middleware/devices/omx`, `integrations/robots/omx`) is <= 500 lines."""
    repo_root = Path(__file__).resolve().parents[1]
    targets = list((repo_root / "tools/sim").glob("omx_*.py"))
    for rel in (
        "learning/curation/omx",
        "learning/envs/isaac",
        "middleware/devices/omx/adapter",
        "middleware/devices/omx/agent",
        "integrations/robots/omx",
    ):
        targets.extend(
            p for p in (repo_root / rel).rglob("*.py")
            if "test" not in p.parts and "tests" not in p.parts
        )
    for path in sorted(set(targets)):
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= 500, f"{path.relative_to(repo_root)} has {len(lines)} lines (> 500)"

