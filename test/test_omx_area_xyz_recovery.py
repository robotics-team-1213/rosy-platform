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


def test_situation_aware_object_realignment_pipeline_and_rail_safe_retract(tmp_path):
    import numpy as np
    import cell_realignment_pipeline as crp

    # 1. 2D wrist camera pose & principal-axis yaw estimation
    wrist_img = np.full((480, 640, 3), (40, 215, 235), dtype=np.uint8)
    wrist_img[155:235, 385:505] = (20, 95, 240)  # Eccentric right (+wx -> -dx_mm)
    pose_ecc = crp.estimate_wrist_object_pose_2d(wrist_img)
    assert pose_ecc["detected"] is True
    assert pose_ecc["corridor_centered"] is False
    assert pose_ecc["dx_mm"] < -10.0

    wrist_centered = np.full((480, 640, 3), (40, 215, 235), dtype=np.uint8)
    wrist_centered[165:245, 265:385] = (20, 95, 240)
    pose_ctr = crp.estimate_wrist_object_pose_2d(wrist_centered)
    assert pose_ctr["detected"] is True
    assert pose_ctr["corridor_centered"] is True
    assert abs(pose_ctr["dx_mm"]) <= 1.0

    # 2. Rail-safe (elbow-first) and belt-safe (constant wrist_flex) retract waypoints
    rail_wps = crp.compile_rail_and_belt_safe_standby_waypoints([-26.89, 17.9, -6.13, 54.33, 17.46, 49.16])
    assert rail_wps[0]["phase"] == "elbow_first_rail_clear"
    assert rail_wps[0]["pose"][1] == pytest.approx(17.9)
    assert rail_wps[0]["pose"][2] <= -18.0

    belt_wps = crp.compile_rail_and_belt_safe_standby_waypoints([-22.98, -11.55, 37.73, 44.27, 22.1, 59.32])
    assert belt_wps[0]["phase"] == "belt_lift_off_constant_wrist"
    assert belt_wps[0]["pose"][3] == pytest.approx(44.27)
    assert belt_wps[0]["pose"][1] <= -22.0
    assert belt_wps[0]["pose"][2] <= 14.0

    # 3. Closed-loop 7-situation object re-alignment pipeline + online IWR feedback
    report = crp.run_closed_loop_realignment_pipeline(tmp_path)
    assert report["total_situations"] == 7
    assert report["all_passed"] is True
    assert len(report["results"]) == 7
    assert (tmp_path / "realignment-pipeline-report.json").exists()
