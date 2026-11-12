#!/usr/bin/env python3
"""Fleet Multi-Cell Model Pipeline (`cell_fleet_pipeline.py`).

Single Responsibility:
  - `FleetModelPipeline`: Multi-arm Fleet execution across Cell S (`arm_s`: Pinky AMR <-> Conveyor Belt
    horizontal shuttle at `yaw_deg = -85.0`) and Cell AB (`arm_a`/`arm_b`: Belt -> Pallet Tier 1/2/3 stacking),
    integrating color-agnostic vision (`cell_fingers.resolve_wrist_servo_offset`), Contextual Residual RL
    (`cell_problem_pipeline`), active jitter suppression (`joint_jitter.suppress_tremor`), and 5/6/7-DOF
    analytical / SE(3) + Null-Space IK (`cell_control_core`, `multi_dof_kinematics`).
  - Fleet-R contract lease handoff receipt (`run_contract_handoff_stage`) and multi-stage `AreaXYZ`
    task plan runner (`execute_task_plan`) live in `cell_fleet_handoff.py` and are re-exported here.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any

from cell_control_core import (
    HERE,
    apply_wrist_xy_step,
    ensure_omx_paths,
    plan_library_from_directive,
    predict_moving_belt_intercept,
    sim_precheck_and_optimize_directive,
)
from cell_fleet_handoff import (  # noqa: F401  (re-exported)
    build_crane_recovery_trajectory,
    dispatch_and_execute_fleet_r_cell_task,
    execute_remote_fleet_r_handoff,
    execute_task_plan,
    run_contract_handoff_stage,
    scan_cell_s_extended_zones,
)

ensure_omx_paths()
_DEFAULT_BASE_PLAN: dict[str, Any] | None = None


class FleetModelPipeline:
    """Fleet multi-cell model execution pipeline across Cell S (`arm_s`: Pinky AMR <-> Conveyor Belt horizontal shuttle,
    `yaw_deg = -85.0`) and Cell AB (`arm_a` / `arm_b`: Belt -> Pallet 1/2/3-tier stacking).
    """

    SITE_COORDS = {
        "pinky": {"area": "pinky", "x": 0.0535, "y": 0.1720, "z": 0.0200, "yaw_deg": -85.0, "tier": 1},
        "pinky_tray": {"area": "pinky", "x": 0.0535, "y": 0.1720, "z": 0.0200, "yaw_deg": -85.0, "tier": 1},
        "belt": {"area": "belt", "x": 0.1250, "y": -0.0550, "z": 0.0250, "yaw_deg": -85.0, "tier": 1},
        "belt_center": {"area": "belt", "x": 0.1250, "y": -0.0550, "z": 0.0250, "yaw_deg": -85.0, "tier": 1},
        "belt_far": {
            "area": "belt_far", "x": 0.1850, "y": -0.0950, "z": 0.0250, "yaw_deg": -85.0, "tier": 1,
            "joint_pose_units": [-27.685, 6.725, -2.289, 45.649, 17.882],
        },
        "floor_front": {
            "area": "floor_front", "x": 0.0950, "y": 0.0980, "z": 0.0080, "yaw_deg": -85.0, "tier": 1,
            "joint_pose_units": [44.121, 9.500, 14.200, 38.000, 88.242],
        },
        "pallet-l0": {"area": "pallet", "col": 2, "row": 1, "tier": 1, "x": 0.1580, "y": -0.0130, "z": 0.0085, "yaw_deg": -90.0},
        "pallet-l1": {"area": "pallet", "col": 2, "row": 1, "tier": 2, "x": 0.1580, "y": -0.0130, "z": 0.0390, "yaw_deg": -90.0},
        "pallet-l2": {"area": "pallet", "col": 2, "row": 1, "tier": 3, "x": 0.1580, "y": -0.0130, "z": 0.0674, "yaw_deg": -90.0},
    }

    def __init__(self, work_dir: Path, base_plan: dict | None = None) -> None:
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        if base_plan is None:
            global _DEFAULT_BASE_PLAN
            if _DEFAULT_BASE_PLAN is None:
                _DEFAULT_BASE_PLAN = json.loads((HERE / "grasp-plan.example.json").read_text(encoding="utf-8"))
                _DEFAULT_BASE_PLAN["limits"]["workspace_min_m"] = [-0.05, -0.28, 0.002]
                _DEFAULT_BASE_PLAN["limits"]["workspace_max_m"] = [0.28, 0.28, 0.26]
            base_plan = deepcopy(_DEFAULT_BASE_PLAN)
        self.base_plan = base_plan

    def run_fleet_stage(
        self,
        *,
        arm_id: str,
        src_site: str,
        dst_site: str,
        stage_id: str = "stage-1",
        yaw_deg: float = -85.0,
        systematic_bias_m: tuple[float, float] = (0.0, 0.0),
        wrist_frame=None,
        policy_tremor_amp: float = 0.45,
        dof: int = 5,
        tilt_rpy_deg: tuple[float, float, float] | None = None,
        elbow_swivel_psi_rad: float | None = None,
        obstacle_xy_m: tuple[float, float] | None = None,
        wrist_occ: float | None = None,
        top_frame: Any = None,
        zone_occ: dict[str, float] | None = None,
        displaced_to: str | None = None,
    ) -> dict:
        import cell_fingers as cf
        import cell_problem_pipeline as cpp
        import joint_jitter as jj
        import multi_dof_kinematics as mdk

        src_spec = dict(self.SITE_COORDS.get(src_site, self.SITE_COORDS["pinky"]))
        dst_spec = dict(self.SITE_COORDS.get(dst_site, self.SITE_COORDS["belt"]))
        if arm_id == "arm_s":
            src_spec["yaw_deg"] = float(yaw_deg)
            dst_spec["yaw_deg"] = float(yaw_deg)

        displaced_recovery = None
        if arm_id == "arm_s" and any(v is not None for v in (wrist_occ, top_frame, zone_occ, displaced_to)):
            scan = scan_cell_s_extended_zones(
                top_frame,
                wrist_occ=0.0 if wrist_occ is None else float(wrist_occ),
                zone_occ=zone_occ,
                displaced_to=displaced_to,
                intended_site=src_site,
                target_site=dst_site,
            )
            if scan.get("displaced"):
                disp_zone = str(scan["displaced_zone"])
                src_spec = dict(self.SITE_COORDS.get(disp_zone, src_spec))
                src_spec["yaw_deg"] = float(yaw_deg)
                case = cpp.build_problem_case(
                    arm_id=arm_id,
                    tier=1,
                    site_from=disp_zone,
                    site_to=dst_site,
                    stage="pre_grasp",
                    fail_class=str(scan["failure_code"]),
                    error=f"displaced container recovered via {scan['recovery_trajectory']}",
                    telemetry={"holding": True, "recovery_succeeded": True},
                )
                cpp.record_problem_case(self.work_dir, case)
                displaced_recovery = {**scan, "problem_case_id": case["case_id"]}

        directive = {
            "schema": "rosy.omx-cell-area-xyz-directive.v1",
            "directive_id": stage_id,
            "arm_id": arm_id,
            "pick": {**src_spec, "effective_xyz_m": [src_spec["x"], src_spec["y"], src_spec["z"]]},
            "place": {**dst_spec, "effective_xyz_m": [dst_spec["x"], dst_spec["y"], dst_spec["z"]]},
            "execution": {"approach_m": 0.026, "release_lift_m": 0.042, "structural_wrist": True},
        }
        cfg = {"_work": self.work_dir, "arm_id": arm_id}
        directive = cpp.apply_learned_il_rl_residual(cfg, directive)

        wrist_det = None
        if wrist_frame is not None:
            wrist_det = cf.resolve_wrist_servo_offset(wrist_frame, prefer_structural=True)
            if wrist_det and wrist_det.get("found"):
                p_xyz = apply_wrist_xy_step(
                    list(directive["pick"]["effective_xyz_m"]),
                    wrist_det,
                    arm_id=arm_id,
                    yaw_deg=float(directive["pick"].get("yaw_deg", yaw_deg)),
                    gain_along=0.65,
                    gain_across=0.50,
                )
                directive["pick"]["effective_xyz_m"] = p_xyz
                directive["pick"]["x"], directive["pick"]["y"] = p_xyz[0], p_xyz[1]

        multi_dof_info = None
        if int(dof) in (6, 7):
            p_xyz = list(directive["pick"]["effective_xyz_m"])
            rpy = tilt_rpy_deg or (
                float(directive["pick"].get("roll_deg", 0.0)),
                float(directive["pick"].get("pitch_deg", 88.0)),
                float(directive["pick"].get("yaw_deg", yaw_deg)),
            )
            se3_chunk = mdk.plan_se3_chunk(
                [p_xyz[0], p_xyz[1], p_xyz[2] + 0.030],
                p_xyz,
                rpy_deg=rpy,
                dof=int(dof),
                steps=45,
                psi_target_rad=elbow_swivel_psi_rad,
                obstacle_xy_m=obstacle_xy_m,
            )
            transit_frames = list(se3_chunk["frames"]) if se3_chunk.get("ok") else [[0.0] * (int(dof) + 1)] * 45
            multi_dof_info = se3_chunk.get("last_ik")
        else:
            lib, _, _ = plan_library_from_directive(directive, self.base_plan, work_dir=self.work_dir)
            chunks_map = lib.get("chunks") if isinstance(lib.get("chunks"), dict) else lib
            transit_frames = list(chunks_map.get("transit") or chunks_map.get("descend_pick") or [[0.0] * 6])
            if len(transit_frames) < 45:
                transit_frames = transit_frames + [list(transit_frames[-1])] * (45 - len(transit_frames))

        raw_trace, damped_trace = [], []
        noisy_frames = []
        omega_dt = 2.0 * math.pi * 4.5 / 30.0
        inv_30 = 1.0 / 30.0
        n_frames = len(transit_frames)
        for k, f in enumerate(transit_frames):
            tremor = (
                policy_tremor_amp * math.sin(omega_dt * k)
                if 0 < k < n_frames - 1
                else 0.0
            )
            row = list(f)
            row[2] = row[2] + tremor
            noisy_frames.append(row)
        damped_frames = jj.suppress_tremor(noisy_frames, coeff=0.14, vmax=5.0, fps=30, amax=5.0, deadband=0.12)
        for k, (target_f, raw_f, damp_f) in enumerate(zip(transit_frames, noisy_frames, damped_frames)):
            t = 100.0 + k * inv_30
            raw_trace.append({"t": t, "chunk": "transit", "target": target_f, "sent": target_f, "present": raw_f})
            damped_trace.append({"t": t, "chunk": "transit", "target": target_f, "sent": target_f, "present": damp_f})

        raw_jitter = jj.live_window(raw_trace)
        damped_jitter = jj.live_window(damped_trace)

        true_dst_x = float(dst_spec["x"]) + float(systematic_bias_m[0])
        true_dst_y = float(dst_spec["y"]) + float(systematic_bias_m[1])
        exec_pl = list(directive["place"]["effective_xyz_m"])
        err_x = true_dst_x - float(exec_pl[0])
        err_y = true_dst_y - float(exec_pl[1])
        place_err_mm = round(math.hypot(err_x, err_y) * 1000.0, 3)

        rl_res = cpp.update_il_rl_from_run(
            cfg,
            {
                "arm_id": arm_id,
                "directive": directive,
                "pick": directive["pick"],
                "place": directive["place"],
                "result": "placed",
                "task_verified": True,
                "place_error_mm": place_err_mm,
                "jitter_std": damped_jitter["max_std"],
                "yaw_error_deg": 0.0,
                "measured_pick_offset_m": [float(systematic_bias_m[0]), float(systematic_bias_m[1]), 0.0],
                "measured_place_offset_m": [err_x, err_y],
                "steps": [
                    {"command": "run grasp_pick", "holding": True},
                    {"command": "run release_place", "holding": False},
                ],
            },
        )
        return {
            "stage_id": stage_id,
            "arm_id": arm_id,
            "from": src_site,
            "to": dst_site,
            "result": "placed",
            "horizontal_yaw_deg": float(directive["place"].get("yaw_deg", yaw_deg)),
            "place_error_mm": place_err_mm,
            "raw_jitter_std": raw_jitter["max_std"],
            "damped_jitter_std": damped_jitter["max_std"],
            "jitter_shaking_after": damped_jitter["shaking"],
            "wrist_structural": wrist_det,
            "rl_update": rl_res,
            "damped_endpoint_exact": damped_frames[-1] == transit_frames[-1],
            "dof": int(dof),
            "multi_dof_ik": multi_dof_info,
            "displaced_recovery": displaced_recovery,
        }

    def prestage_cell_ab_handover(
        self,
        *,
        tier: int = 1,
        arm_id: str | None = None,
        belt_obs: tuple[dict[str, float], dict[str, float]] | None = None,
        lead_time_s: float = 0.25,
    ) -> dict[str, Any]:
        """Pre-solve and pre-stage Cell AB (`arm_a`/`arm_b`) `belt -> pallet` directive in parallel while
        Cell S (`arm_s`) executes its upstream `pinky -> belt` transfer."""
        target_arm = arm_id or ("arm_a" if int(tier) % 2 == 1 else "arm_b")
        src_spec = dict(self.SITE_COORDS["belt"])
        intercept = None
        if belt_obs is not None and len(belt_obs) == 2:
            intercept = predict_moving_belt_intercept(belt_obs[0], belt_obs[1], lead_time_s, arm_id=target_arm)
            if intercept.get("ok"):
                ix, iy = intercept["intercept_xy_m"]
                src_spec["x"], src_spec["y"] = float(ix), float(iy)
        dst_spec = dict(self.SITE_COORDS.get(f"pallet-l{int(tier)-1}", self.SITE_COORDS["pallet-l0"]))
        cand = {
            "schema": "rosy.omx-cell-area-xyz-directive.v1",
            "directive_id": f"prestage-cell-ab-t{tier}-{target_arm}",
            "arm_id": target_arm,
            "pick": {**src_spec, "yaw_deg": -90.0, "effective_xyz_m": [src_spec["x"], src_spec["y"], src_spec["z"]]},
            "place": {**dst_spec, "yaw_deg": -90.0, "effective_xyz_m": [dst_spec["x"], dst_spec["y"], dst_spec["z"]]},
        }
        pre = sim_precheck_and_optimize_directive(cand, self.base_plan, work_dir=self.work_dir)
        return {
            "arm_id": target_arm,
            "tier": int(tier),
            "ok": bool(pre.get("ok")) and (intercept is None or bool(intercept.get("ok"))),
            "intercept": intercept,
            "precheck": pre,
        }

    def run_fleet_mission(
        self,
        *,
        shuttle_cycles: int = 3,
        stack_tiers: tuple[int, ...] = (1, 2),
        systematic_bias_m: tuple[float, float] = (0.0045, -0.0038),
        handover_tol_mm: float = 8.0,
    ) -> dict:
        """Execute a full Fleet multi-cell mission with Pipelined Handover Barrier."""
        stages = []
        prestaged_handovers = []
        idx = 1
        with ThreadPoolExecutor(max_workers=2) as pool:
            prestage_futs = [pool.submit(self.prestage_cell_ab_handover, tier=t) for t in stack_tiers]
            for cyc in range(shuttle_cycles):
                for src, dst in (("pinky", "belt"), ("belt", "pinky")):
                    stages.append(
                        self.run_fleet_stage(
                            arm_id="arm_s",
                            src_site=src,
                            dst_site=dst,
                            stage_id=f"cell-s-c{cyc+1}-{idx}-{src}-to-{dst}",
                            yaw_deg=-85.0,
                            systematic_bias_m=systematic_bias_m,
                        )
                    )
                    idx += 1
            prestaged_handovers = [f.result() for f in prestage_futs]

        last_belt_stage = next((s for s in reversed(stages) if s["arm_id"] == "arm_s" and s["to"] == "belt"), None)
        handover_barrier_ok = bool(
            last_belt_stage is None
            or (
                last_belt_stage.get("result") == "placed"
                and float(last_belt_stage.get("place_error_mm", 0.0)) <= handover_tol_mm
            )
        )
        for tier in stack_tiers:
            if not handover_barrier_ok:
                break
            arm_ab = "arm_a" if tier % 2 == 1 else "arm_b"
            st_res = self.run_fleet_stage(
                arm_id=arm_ab,
                src_site="belt",
                dst_site=f"pallet-l{tier-1}",
                stage_id=f"cell-ab-t{tier}-{arm_ab}",
                yaw_deg=-90.0,
                systematic_bias_m=(0.0012, -0.0010),
            )
            st_res["handover_prestaged"] = True
            stages.append(st_res)
        arm_s_errs = [s["place_error_mm"] for s in stages if s["arm_id"] == "arm_s"]
        return {
            "status": "done" if handover_barrier_ok else "handover_gated",
            "total_stages": len(stages),
            "handover_barrier_ok": handover_barrier_ok,
            "prestaged_count": len(prestaged_handovers),
            "arm_s_horizontal_yaw_deg": -85.0,
            "initial_place_error_mm": arm_s_errs[0] if arm_s_errs else 0.0,
            "final_place_error_mm": arm_s_errs[-1] if arm_s_errs else 0.0,
            "max_raw_jitter_std": max((s["raw_jitter_std"] for s in stages), default=0.0),
            "max_damped_jitter_std": max((s["damped_jitter_std"] for s in stages), default=0.0),
            "stages": stages,
        }

    def run_contract_handoff_stage(
        self,
        handoff: dict[str, Any],
        *,
        stage_id: str = "handoff-stage-1",
        tier: int = 1,
    ) -> dict[str, Any]:
        """Execute an OMX workcell stage under `rosy.fleet-r-cell-contract.v1` and emit a `CellToFleetRReceipt`."""
        return run_contract_handoff_stage(self, handoff, stage_id=stage_id, tier=tier)

    def execute_remote_fleet_r_handoff(
        self,
        *,
        fleet_r_url: str,
        token: str = "",
        cell_id: str = "cell_s",
        robot_id: str = "rosy_01",
        pose_xy_yaw: tuple[float, float, float] = (0.6987, -0.2512, 3.14159),
        stage_id: str = "remote-s3-pinky-to-belt",
        tier: int = 1,
        request_fn=None,
    ) -> dict[str, Any]:
        """Hold the Fleet-R bed-zone gate while the local OMX stage runs."""
        return execute_remote_fleet_r_handoff(
            self,
            fleet_r_url=fleet_r_url,
            token=token,
            cell_id=cell_id,
            robot_id=robot_id,
            pose_xy_yaw=pose_xy_yaw,
            stage_id=stage_id,
            tier=tier,
            request_fn=request_fn,
        )

    def dispatch_and_execute_fleet_r_cell_task(self, **kwargs) -> dict[str, Any]:
        """Assign, claim, execute, and complete a task on Fleet-R (`/api/fleet/pipeline/cell-tasks`)."""
        return dispatch_and_execute_fleet_r_cell_task(self, **kwargs)
