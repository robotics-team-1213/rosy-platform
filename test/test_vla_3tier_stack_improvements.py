#!/usr/bin/env python3
"""Unit and Integration Tests for OMX 1/2/3-Tier Stacking, Decision Seats, and SmolVLA Handover:
  1. CellStackGuard aligned with Unified AreaXYZ (`TIER_Z_M = {1: 0.0074, 2: 0.0398, 3: 0.0674}`),
     calculus seating stiffness (`evaluate_stud_seating_derivatives`), `cell_arm_cal.evaluate_grasp_dynamics`,
     and `cell_area_zones.verify_stack_outcome`.
  2. VlaHandoverBroker integrated with `judge_seat.measured` precondition sovereignty,
     `cell_area_xyz.sim_precheck_and_optimize_directive`, `TemporalChunkEnsembler`,
     `compute_stud_release_residual`, D-854 `lerobot_norm_v1` rate clamping, and 3-tier plan execution.
  3. VlaDomainRandomizer in `learning/curation/omx/` with AreaXYZ bounds, Trial 11 cell hazards, and wrist occlusion.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pytest

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
for _p in (
    PLATFORM_ROOT / "middleware" / "devices" / "omx" / "adapter",
    PLATFORM_ROOT / "deploy" / "robot" / "omx",
    PLATFORM_ROOT / "learning" / "curation" / "omx",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from omx_adapter.area_xyz import TIER_Z_M, build_directive  # noqa: E402
from cell_stack_guard import CellStackGuard, StackGateConfig  # noqa: E402
from vla_handover_broker import (  # noqa: E402
    HandoverState,
    TaskDispatch,
    VlaHandoverBroker,
    clamp_lerobot_norm_action,
    compute_stud_release_residual,
)
from vla_domain_randomizer import VlaDomainRandomizer  # noqa: E402


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


class TestCellStackGuard:
    def test_height_window_uses_real_area_xyz_tier_heights(self):
        guard = CellStackGuard(StackGateConfig(tier=3, z_tolerance_m=0.002))
        assert guard.cfg.resolved_nominal_z_m() == TIER_Z_M[3] == 0.0674

        ok, _ = guard.verify_height(0.0678, tier=3)
        assert ok is True

        ok2, _ = guard.verify_height(0.0398, tier=2)
        assert ok2 is True

        ok_fail, msg = guard.verify_height(0.0715, tier=3)
        assert ok_fail is False
        assert "Height mismatch" in msg

    def test_torque_profile_jamming_surge_rate_and_settle(self):
        guard = CellStackGuard(
            StackGateConfig(
                jam_torque_threshold=280.0,
                max_torque_surge_per_step=190.0,
                settle_torque_min=80.0,
                settle_torque_max=220.0,
            )
        )

        normal_profile = [20.0, 50.0, 110.0, 180.0, 150.0, 120.0]
        ok, _ = guard.verify_torque_profile(normal_profile)
        assert ok is True

        jam_profile = [20.0, 70.0, 210.0, 320.0, 300.0]
        ok, msg = guard.verify_torque_profile(jam_profile)
        assert ok is False
        assert "Side jamming detected" in msg

        # Single-step hard rim impact (+210 mA in 1 step, even though peak 240 < 280)
        hard_impact_profile = [25.0, 235.0, 190.0, 140.0]
        ok_imp, msg_imp = guard.verify_torque_profile(hard_impact_profile)
        assert ok_imp is False
        assert "Hard rim impact detected" in msg_imp

        empty_profile = [10.0, 20.0, 25.0, 30.0]
        ok, msg = guard.verify_torque_profile(empty_profile)
        assert ok is False
        assert "Under-seating detected" in msg

    def test_seating_stiffness_derivatives(self):
        guard = CellStackGuard(StackGateConfig(tier=3))
        # Normal 3mm descent into stud lock with preload relaxation (175 -> 130 mA)
        d_good = guard.evaluate_stud_seating_derivatives(
            z_samples_m=[0.0704, 0.0689, 0.0674, 0.0674],
            torque_samples=[30.0, 95.0, 175.0, 130.0],
        )
        assert d_good["ok"] is True
        assert d_good["regime"] == "stud_locked_and_relaxed"
        assert 20.0 <= d_good["k_seat_ma_per_mm"] <= 100.0

        # Rigid rim collision: tiny 0.5mm descent causes 220mA spike (k_seat = 380 mA/mm)
        d_jam = guard.evaluate_stud_seating_derivatives(
            z_samples_m=[0.0720, 0.0715, 0.0715],
            torque_samples=[30.0, 220.0, 215.0],
        )
        assert d_jam["ok"] is False
        assert d_jam["regime"] == "rim_jam_collision"

    def test_full_evaluation_and_calculus_dynamics_and_camera_verify(self):
        guard = CellStackGuard(StackGateConfig(tier=3, z_tolerance_m=0.002))

        r_grasp = {"ok": True, "holding": True, "gripper_current_ma": 162.0, "state": [0, 0, 0, 0, 48.0, 54.4]}
        r_lift = {"ok": True, "holding": True, "gripper_current_ma": 138.0, "state": [0, 0, 0, 0, 48.0, 54.2]}
        holding_ok, dyn = guard.verify_grasp_dynamics_before_place(r_grasp, r_lift=r_lift)
        assert holding_ok is True
        assert dyn["regime"] in ("stable_hold", "elastic_settle")

        z_tracker = [TIER_Z_M[3]]
        is_holding = [True]

        res = guard.evaluate_release(
            current_z_m=0.0676,
            target_z_m=None,
            torque_history=[30.0, 80.0, 160.0, 130.0],
            z_history_m=[0.0705, 0.0690, 0.0676, 0.0676],
            read_grip_holding_fn=lambda: is_holding[0],
            read_z_fn=lambda: z_tracker[0],
            lift_step_fn=lambda dz: z_tracker.__setitem__(0, z_tracker[0] + dz),
            tier=3,
        )
        assert res.passed is True
        assert res.stage_failed is None
        assert res.recovery_action == "proceed"

        before_side = np.full((480, 640, 3), (180, 180, 180), dtype=np.uint8)
        before_side[252:315, 155:220] = (30, 120, 240)
        after_side = np.full((480, 640, 3), (180, 180, 180), dtype=np.uint8)
        after_side[125:190, 230:288] = (30, 120, 240)
        v_out = guard.verify_post_release_cameras(
            before_side=before_side,
            after_side=after_side,
            pick={"col": 1, "tier": 1},
            place={"col": 2, "tier": 3},
        )
        assert v_out["verified"] is True


class TestVlaHandoverBroker:
    def test_lifecycle_prefetch_sim_precheck_and_decision_veto(self, tmp_path: Path):
        broker = VlaHandoverBroker(arm_id="arm_b", max_retries=2)
        assert broker.current_state == HandoverState.IDLE

        t1 = broker.trigger_prefetch(target_slot="pallet-l2", tier=3)
        assert broker.current_state == HandoverState.PREFETCHING
        assert "0.0674m" in t1.message

        directive = broker.build_area_xyz_directive(
            pick={"area": "pallet", "col": 2, "row": 2, "tier": 1, "x": 0.1536, "y": -0.0948, "z": 0.0085, "yaw_deg": 47.3, "apply_bias": False},
            place={"area": "pallet", "col": 2, "row": 1, "tier": 3, "x": 0.1605, "y": -0.0060, "z": 0.0674, "yaw_deg": -90.0, "apply_bias": False},
            directive_id="broker-tier3",
        )
        task = TaskDispatch(
            task_id="TASK-STACK-301",
            container_id="CONT-042",
            target_slot="pallet-l2",
            tier=3,
            vla_prompt="align and stack container on tier 3 studs",
            directive=directive,
        )
        assert task.target_z_m == TIER_Z_M[3] == 0.0674
        t2 = broker.dispatch_task(task, base_plan=SAMPLE_BASE_PLAN, work_dir=tmp_path)
        assert broker.current_state == HandoverState.MACRO_IK_TRANSIT
        assert t2.sim_precheck is not None and t2.sim_precheck["ok"] is True

        veto_tel = broker.signal_ready_reached(
            facts={"chunk": "lift_pick", "holding": True, "grasp_stable": False, "grasp_issue": "wedged at 56.9u"}
        )
        assert broker.current_state == HandoverState.RETRY_TRIGGERED
        assert veto_tel.decision_veto is not None
        assert veto_tel.decision_veto["action"] == "reinsert"

        t3 = broker.signal_ready_reached(
            facts={"chunk": "above_place", "holding": True, "grasp_stable": True}
        )
        assert broker.current_state == HandoverState.VLA_ACTIVE
        assert t3.decision_veto is None

        # Multi-step chunk output blended via TemporalChunkEnsembler + D-854 rate clamping
        current_q = [0.0, -10.0, 15.0, 45.0, 48.0, 54.4]
        act, t4 = broker.step_vla_inference(
            lambda _obs: [[10.0, -10.0, 15.0, 45.0, 48.0, 54.4], [10.5, -10.0, 15.0, 45.0, 48.0, 54.4]],
            {"dummy": 1},
            clamp_norm=True,
            current_state=current_q,
        )
        assert len(act) == 6
        assert act[0] == pytest.approx(5.0 / 30.0, abs=1e-3)
        assert t4.vla_inference_lat_ms >= 0.0

        retry_called = [False]
        broker.signal_seating_attempted(
            gate_eval_fn=lambda: False,
            retry_fn=lambda: retry_called.__setitem__(0, True),
        )
        assert broker.retry_count == 1
        assert retry_called[0] is True
        assert broker.current_state == HandoverState.VLA_ACTIVE

        broker.signal_seating_attempted(gate_eval_fn=lambda: True)
        assert broker.current_state == HandoverState.COMPLETED

    def test_execute_hybrid_stack_stage_end_to_end_with_il_rl_update(self, tmp_path: Path):
        broker = VlaHandoverBroker(arm_id="arm_b", max_retries=2)
        directive = broker.build_area_xyz_directive(
            pick={"area": "pallet", "col": 3, "row": 1, "tier": 2, "x": 0.1988, "y": -0.0030, "z": 0.0398, "yaw_deg": -90.0},
            place={"area": "pallet", "col": 2, "row": 1, "tier": 3, "x": 0.1580, "y": -0.0130, "z": 0.0674, "yaw_deg": -90.0},
            directive_id="e2e-tier3-hybrid",
        )
        task = TaskDispatch(
            task_id="TASK-HYBRID-303",
            container_id="CONT-303",
            target_slot="pallet-l2",
            tier=3,
            vla_prompt="align and seat container on tier 3 studs",
            directive=directive,
        )

        cmds_executed: list[str] = []

        def fake_act(cmd: str) -> dict:
            cmds_executed.append(cmd)
            if cmd == "run grasp_pick":
                return {"ok": True, "holding": True, "gripper_current_ma": 165.0, "state": [0.0, -10.0, 15.0, 45.0, 48.0, 54.4]}
            return {"ok": True, "holding": True, "gripper_current_ma": 135.0, "state": [0.0, -10.0, 15.0, 45.0, 48.0, 54.35]}

        def fake_seating_probe(retry_idx: int):
            if retry_idx == 0:
                return 0.0715, [30.0, 90.0, 295.0, 250.0]
            return 0.0675, [25.0, 75.0, 165.0, 125.0]

        side_calls = [0]

        def fake_frame(role: str):
            img = np.full((480, 640, 3), (180, 180, 180), dtype=np.uint8)
            if role == "side":
                side_calls[0] += 1
                if side_calls[0] <= 1:
                    img[182:250, 295:368] = (30, 120, 240)
                else:
                    img[125:190, 230:288] = (30, 120, 240)
            elif role == "top":
                img[170:260, 380:410] = (30, 120, 240)
            return img

        out = broker.execute_hybrid_stack_stage(
            task,
            base_plan=SAMPLE_BASE_PLAN,
            work_dir=tmp_path,
            act_fn=fake_act,
            vla_step_fn=lambda obs: [0.1, -10.0, 15.0, 45.0, 48.0, 54.4],
            seating_probe_fn=fake_seating_probe,
            frame_fn=fake_frame,
            vla_refinement_steps=2,
            wrist_obs={"along_mm": -1.6, "across_mm": 0.4, "skew_deg": 1.2},
        )
        assert out["ok"] is True
        assert out["state"] == "COMPLETED"
        assert out["retry_count"] == 1
        assert out["vla_steps_executed"] == 4
        assert out["release_residual"]["dx_m"] != 0.0
        assert out["gate_reports"][0]["passed"] is False
        assert out["gate_reports"][0]["stage_failed"] == "STAGE_1_HEIGHT"
        assert out["gate_reports"][1]["passed"] is True
        assert out["verification"]["verified"] is True
        assert out["il_rl_update"]["bucket"] == "pallet_right"
        assert out["il_rl_update"]["reward"] == 2.0
        assert "run release_place" in cmds_executed
        rl_doc = json.loads((tmp_path / "rl-policy.json").read_text(encoding="utf-8"))
        assert "tier_3" in rl_doc.get("place_tiers", {})

    def test_execute_3tier_hybrid_plan_across_tiers_1_2_3(self, tmp_path: Path):
        broker = VlaHandoverBroker(arm_id="arm_b", max_retries=2)
        tasks = [
            TaskDispatch(
                task_id=f"TASK-T{tier}",
                container_id=f"CONT-T{tier}",
                target_slot=f"pallet-l{tier - 1}",
                tier=tier,
                vla_prompt=f"stack on tier {tier}",
                directive=broker.build_area_xyz_directive(
                    pick={"area": "pallet", "col": 1, "row": 1, "tier": 1, "x": 0.1280, "y": -0.0120, "z": 0.0074},
                    place={"area": "pallet", "col": 2, "row": 1, "tier": tier, "x": 0.1580, "y": -0.0130, "z": TIER_Z_M[tier]},
                    directive_id=f"plan-t{tier}",
                ),
            )
            for tier in (1, 2, 3)
        ]

        def fake_act(cmd: str) -> dict:
            return {"ok": True, "holding": True, "gripper_current_ma": 158.0, "state": [0.0, -10.0, 15.0, 45.0, 48.0, 54.4]}

        plan_out = broker.execute_3tier_hybrid_plan(
            tasks,
            base_plan=SAMPLE_BASE_PLAN,
            work_dir=tmp_path,
            act_fn=fake_act,
            vla_step_fn=lambda _obs: [0.05, -10.0, 15.0, 45.0, 48.0, 54.4],
            seating_probe_fn=lambda tier, _retry: (TIER_Z_M[tier], [30.0, 85.0, 165.0, 128.0]),
            frame_fn=None,
        )
        assert plan_out["ok"] is True
        assert plan_out["tiers_completed"] == [1, 2, 3]


class TestVlaDomainRandomizer:
    def test_image_cell_hazards_state_noise_and_area_xyz_pose_randomization(self):
        randomizer = VlaDomainRandomizer()

        img = np.full((3, 64, 64), 0.5, dtype=np.float32)
        aug_img = randomizer.augment_image_tensor(img, is_wrist_cam=True, tier=3, inject_hazards=True)
        assert aug_img.shape == (3, 64, 64)
        assert aug_img.dtype == np.float32
        assert 0.0 <= aug_img.min() and aug_img.max() <= 1.0

        img_u8 = np.full((64, 64, 3), 128, dtype=np.uint8)
        aug_u8 = randomizer.inject_cell_visual_hazards(img_u8)
        assert aug_u8.shape == (64, 64, 3) and aug_u8.dtype == np.uint8

        # Test batch with observation.state and observation.images.wrist
        batch = {
            "observation.images.wrist": img,
            "observation.state": [0.0, -10.0, 15.0, 45.0, 48.0, 54.4],
        }
        proc = randomizer.process_batch(batch, tier=3)
        assert len(proc["observation.state"]) == 6
        assert 0.0 <= proc["observation.state"][5] <= 100.0

        x, y, yaw = 0.1580, -0.0130, -90.0
        ax, ay, az, ayaw = randomizer.augment_pose(x, y, None, yaw, tier=3, area="pallet")
        assert abs(ax - x) <= 0.0155
        assert abs(ay - y) <= 0.0155
        assert abs(az - TIER_Z_M[3]) <= 0.0025
        assert abs(ayaw - yaw) <= 8.5
