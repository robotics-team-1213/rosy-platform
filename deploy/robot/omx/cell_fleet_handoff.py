#!/usr/bin/env python3
"""Fleet-R Contract Lease Handoff Receipt & Multi-Stage Task Plan Runner (`cell_fleet_handoff.py`).

Single Responsibility:
  - Executes `rosy.fleet-r-cell-contract.v1` handoff lease stages (`run_contract_handoff_stage`),
    verifying AMR wheel brake / bed readiness / zero velocity interlocks and emitting a SHA-256
    `CellToFleetRReceipt`.
  - Executes multi-stage `AreaXYZ` task plans (`execute_task_plan`) with parallel simulation
    pre-flight (`sim_precheck_and_optimize_directive`) and closed-loop Real <-> Sim ledger verification.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from cell_control_core import ensure_omx_paths, sim_precheck_and_optimize_directive
from cell_spec_recovery_fsm import CELL_S_EXTENDED_ZONES, select_recovery_skill

ensure_omx_paths()

EXTENDED_RECOVERY_ZONE_ORDER: tuple[str, ...] = ("belt_far", "floor_front", "pinky_tray", "belt_center")
EMPTY_WRIST_OCC_THRESHOLD: float = 0.14
DISPLACED_ZONE_MIN_OCC: float = 0.015
CRANE_LIFT_SHOULDER_UNITS: float = -27.0
CRANE_LIFT_ELBOW_UNITS: float = 22.0
CRANE_MAX_STEP_CAP: float = 0.032


def _measure_orange_occ_in_roi(top_frame: Any, roi: tuple[int, int, int, int]) -> float:
    if top_frame is None or not hasattr(top_frame, "shape") or len(top_frame.shape) != 3:
        return 0.0
    import cv2
    import numpy as np

    h, w = top_frame.shape[:2]
    x0, y0, x1, y1 = max(0, int(roi[0])), max(0, int(roi[1])), min(w, int(roi[2])), min(h, int(roi[3]))
    crop = top_frame[y0:y1, x0:x1]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    mask = ((hue <= 25) | (hue >= 165)) & (sat >= 90) & (val >= 90)
    return round(float(np.mean(mask)), 4)


def build_crane_recovery_trajectory(
    trajectory_name: str, *, max_step: float = CRANE_MAX_STEP_CAP,
) -> dict[str, Any]:
    """Build a safe crane-lift recovery trajectory (`shoulder_lift -> -27.0`, `elbow_flex -> 22.0` at
    `max_step <= 0.032` before panning so `shoulder_lift` never triggers a lag fault)."""
    name = str(trajectory_name or "recover_from_belt_far_to_pinky").strip()
    step_cap = round(min(float(max_step), CRANE_MAX_STEP_CAP), 4)
    from_zone = "floor_front" if "floor_front" in name else "belt_far"
    to_zone = "belt_center" if "belt_center" in name else "pinky_tray"
    src_pose = list(CELL_S_EXTENDED_ZONES[from_zone]["grasp_pose_units"])
    dst_pose = list(CELL_S_EXTENDED_ZONES[to_zone]["grasp_pose_units"])
    src_pan, src_lift, src_elbow, src_wf, src_wr = (float(v) for v in src_pose)
    dst_pan, dst_lift, dst_elbow, dst_wf, dst_wr = (float(v) for v in dst_pose)

    waypoints = [
        {"phase": "hover_source", "pose_units": [src_pan, CRANE_LIFT_SHOULDER_UNITS, CRANE_LIFT_ELBOW_UNITS, src_wf, src_wr, 60.0], "max_step": step_cap},
        {"phase": "descend_source", "pose_units": [src_pan, src_lift, src_elbow, src_wf, src_wr, 60.0], "max_step": step_cap},
        {"phase": "grasp_source", "pose_units": [src_pan, src_lift, src_elbow, src_wf, src_wr, -30.0], "max_step": step_cap},
        {"phase": "crane_lift_vertical", "pose_units": [src_pan, CRANE_LIFT_SHOULDER_UNITS, CRANE_LIFT_ELBOW_UNITS, 35.0, src_wr, -30.0], "max_step": step_cap, "pan_held_constant": True},
        {"phase": "crane_pan_high", "pose_units": [dst_pan, CRANE_LIFT_SHOULDER_UNITS, CRANE_LIFT_ELBOW_UNITS, dst_wf, dst_wr, -30.0], "max_step": step_cap},
        {"phase": "place_target", "pose_units": [dst_pan, dst_lift, dst_elbow, dst_wf, dst_wr, 60.0], "max_step": step_cap},
        {"phase": "retreat_high", "pose_units": [dst_pan, CRANE_LIFT_SHOULDER_UNITS, CRANE_LIFT_ELBOW_UNITS, dst_wf, dst_wr, 60.0], "max_step": step_cap},
    ]
    return {
        "trajectory_name": name, "from_zone": from_zone, "to_zone": to_zone,
        "grasp_pose_units": src_pose, "target_pose_units": dst_pose,
        "crane_shoulder_lift": CRANE_LIFT_SHOULDER_UNITS, "crane_elbow_flex": CRANE_LIFT_ELBOW_UNITS,
        "max_step": step_cap, "lift_before_pan": True, "waypoints": waypoints,
    }


def scan_cell_s_extended_zones(
    top_frame: Any = None, *, wrist_occ: float = 0.0, zone_occ: dict[str, float] | None = None,
    displaced_to: str | None = None, intended_site: str = "pinky", target_site: str | None = None,
    max_step: float = CRANE_MAX_STEP_CAP,
) -> dict[str, Any]:
    """Detect when the intended pick site (`pinky`/`pinky_tray` or `belt`/`belt_center`) is empty (`wrist_occ < 0.14`),
    scan the extended recovery zones (`belt_far`, `floor_front`, `pinky_tray`, `belt_center`) from the top camera,
    and emit a deterministic failure/recovery classification + crane-lift trajectory."""
    norm_pick = "belt_center" if str(intended_site).strip().lower() in ("belt", "belt_center") else "pinky_tray"
    resolved_target = str(target_site or intended_site or "pinky").strip().lower()
    occ_map: dict[str, float] = {
        z: _measure_orange_occ_in_roi(top_frame, CELL_S_EXTENDED_ZONES[z]["top_roi_px"])
        for z in EXTENDED_RECOVERY_ZONE_ORDER
    }
    if isinstance(zone_occ, dict):
        for k, v in zone_occ.items():
            key = "pinky_tray" if k == "pinky" else ("belt_center" if k == "belt" else str(k))
            if key in occ_map and v is not None:
                occ_map[key] = round(float(v), 4)
    if displaced_to in ("belt_far", "floor_front"):
        occ_map[str(displaced_to)] = max(occ_map.get(str(displaced_to), 0.0), 0.22)

    eff_wrist_occ = round(float(wrist_occ), 4)
    pick_empty = eff_wrist_occ < EMPTY_WRIST_OCC_THRESHOLD
    displaced_zone: str | None = None
    failure_code: str | None = None
    if pick_empty:
        bf_occ, ff_occ = occ_map.get("belt_far", 0.0), occ_map.get("floor_front", 0.0)
        if bf_occ >= DISPLACED_ZONE_MIN_OCC and bf_occ >= ff_occ:
            displaced_zone, failure_code = "belt_far", "S9_DISPLACED_CONTAINER_BELT_FAR"
        elif ff_occ >= DISPLACED_ZONE_MIN_OCC:
            displaced_zone, failure_code = "floor_front", "S10_DISPLACED_CONTAINER_FLOOR_FRONT"

    base_out = {
        "pick_empty": pick_empty, "wrist_occ": eff_wrist_occ, "intended_site": norm_pick,
        "target_site": resolved_target, "zones_scanned": list(EXTENDED_RECOVERY_ZONE_ORDER), "zone_occ": occ_map,
    }
    if failure_code is None:
        return {**base_out, "displaced": False, "displaced_zone": None, "failure_code": None, "recovery_trajectory": None, "trajectory": None}

    skill = select_recovery_skill(failure_code, target_site=resolved_target)
    traj = build_crane_recovery_trajectory(skill["skill"], max_step=max_step)
    return {
        **base_out, "displaced": True, "displaced_zone": displaced_zone, "failure_code": failure_code,
        "recovery_skill": skill, "recovery_trajectory": skill["skill"], "trajectory": traj,
    }


def run_contract_handoff_stage(
    pipeline,
    handoff: dict[str, Any],
    *,
    stage_id: str = "handoff-stage-1",
    tier: int = 1,
) -> dict[str, Any]:
    """Execute an OMX workcell stage under `rosy.fleet-r-cell-contract.v1` and emit a `CellToFleetRReceipt`."""
    lease_id = str(handoff.get("handoff_lease_id") or "lease-0")
    cell_id = str(handoff.get("cell_id") or "cell_s")
    station_place = str(handoff.get("station_place") or ("S3" if cell_id == "cell_s" else "S5"))
    robot_id = str(handoff.get("robot_id") or "pinky_1")
    braked = bool(handoff.get("wheel_brake_locked", True))
    bed_ready = bool(handoff.get("bed_ready", True))
    v_cmd = float(handoff.get("v_cmd_mps", 0.0))

    if not braked or not bed_ready or abs(v_cmd) > 1e-4:
        return {
            "contract_version": "rosy.fleet-r-cell-contract.v1",
            "receipt": {
                "handoff_lease_id": lease_id,
                "cell_id": cell_id,
                "station_place": station_place,
                "robot_id": robot_id,
                "phase": "ABORTED",
                "arm_roles_used": ["arm_s"] if cell_id == "cell_s" else ["arm_a", "arm_b"],
                "amr_motion_inhibited": False,
                "stage_id": stage_id,
                "goal_evidence_digest": None,
                "reason": "AMR_NOT_LOCKED_AT_HANDOFF",
            },
            "stage_result": None,
        }

    if cell_id == "cell_s":
        src_site = str(handoff.get("src_site") or "pinky")
        dst_site = str(handoff.get("dst_site") or "belt")
        stage_kwargs: dict[str, Any] = {
            "arm_id": "arm_s",
            "src_site": src_site,
            "dst_site": dst_site,
            "stage_id": stage_id,
            "yaw_deg": -85.0,
        }
        for opt_key in ("wrist_occ", "top_frame", "zone_occ", "displaced_to"):
            if opt_key in handoff and handoff[opt_key] is not None:
                stage_kwargs[opt_key] = handoff[opt_key]
        try:
            stage_res = pipeline.run_fleet_stage(**stage_kwargs)
        except TypeError:
            stage_res = pipeline.run_fleet_stage(
                arm_id="arm_s", src_site=src_site, dst_site=dst_site, stage_id=stage_id, yaw_deg=-85.0
            )
        arms = ["arm_s"]
    else:
        lvl = max(0, min(2, int(tier) - 1))
        stage_res = pipeline.run_fleet_stage(
            arm_id="arm_a" if lvl % 2 == 0 else "arm_b",
            src_site="belt",
            dst_site=f"pallet-l{lvl}",
            stage_id=stage_id,
            yaw_deg=-90.0,
        )
        arms = ["arm_a", "arm_b"]

    converged = bool(stage_res.get("converged", stage_res.get("place_error_mm", 0.0) <= 5.0))
    digest = hashlib.sha256(
        json.dumps({"lease": lease_id, "stage": stage_id, "converged": converged}, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "contract_version": "rosy.fleet-r-cell-contract.v1",
        "receipt": {
            "handoff_lease_id": lease_id,
            "cell_id": cell_id,
            "station_place": station_place,
            "robot_id": robot_id,
            "phase": "RELEASED" if converged else "ABORTED",
            "arm_roles_used": arms,
            "amr_motion_inhibited": False,
            "stage_id": stage_id,
            "goal_evidence_digest": f"sha256:{digest}" if converged else None,
            "reason": "TRANSFER_CONFIRMED" if converged else "STAGE_NOT_CONVERGED",
        },
        "stage_result": stage_res,
    }


def execute_remote_fleet_r_handoff(
    pipeline,
    *,
    fleet_r_url: str,
    token: str = "",
    cell_id: str = "cell_s",
    robot_id: str = "rosy_01",
    pose_xy_yaw: tuple[float, float, float] = (0.6987, -0.2512, 3.14159),
    stage_id: str = "remote-s3-pinky-to-belt",
    tier: int = 1,
    request_fn: Callable[[str, str, dict[str, Any] | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Hold the Fleet-R bed-zone gate while the local OMX stage runs."""
    if request_fn is None:
        import ssl
        from urllib.request import Request, urlopen

        def request_fn(method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
            data = json.dumps(body).encode("utf-8") if body is not None else None
            request = Request(
                f"{fleet_r_url.rstrip('/')}{path}", data=data, method=method,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            with urlopen(request, context=ssl._create_unverified_context(), timeout=15) as response:
                return json.load(response)

    body = {
        "cell_id": cell_id, "robot_id": robot_id, "robot_kind": "pinky",
        "x": float(pose_xy_yaw[0]), "y": float(pose_xy_yaw[1]), "yaw": float(pose_xy_yaw[2]),
        "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0,
        "phase": "ARM_IN_BED_ZONE", "tier": int(tier),
    }
    claim_resp = request_fn("POST", "/api/fleet/pipeline/cell-handoff", body)
    assert claim_resp["gate"]["amr_motion_inhibited"] is True
    cb_locked = request_fn("GET", "/api/fleet/charge-bays", None)
    status_locked = request_fn("GET", "/api/fleet/pipeline/status", None)
    assert cb_locked["omx_cells"][cell_id]["gate"]["amr_motion_inhibited"] is True
    assert status_locked["omx_cell_layer"]["cells"][cell_id]["gate"]["amr_motion_inhibited"] is True

    omx_res = pipeline.run_contract_handoff_stage(claim_resp["handoff"], stage_id=stage_id, tier=tier)
    receipt = omx_res["receipt"]
    release_resp = request_fn("POST", "/api/fleet/pipeline/cell-handoff", {
        **body, "phase": receipt["phase"], "stage_id": stage_id,
        "goal_evidence_digest": receipt["goal_evidence_digest"], "reason": receipt["reason"],
    })
    assert release_resp["gate"]["amr_motion_inhibited"] is False
    assert release_resp["gate"]["amr_can_depart"] is True
    return {
        "fleet_r_url": fleet_r_url, "claim_gate": claim_resp["gate"],
        "charge_bays_locked": cb_locked.get("omx_cells", {}).get(cell_id, {}).get("gate"),
        "omx_receipt": receipt, "release_gate": release_resp["gate"],
    }



def execute_task_plan(
    stages: list[dict[str, Any]],
    *,
    base_plan: dict[str, Any],
    work_dir: Path,
    act_fn: Callable[[str], dict[str, Any]],
    frame_fn: Callable[[str], Any] | None = None,
    kinematics_root: Path | None = None,
    max_attempts: int = 2,
    parallel_sim: bool = True,
    execute_directive_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute a multi-stage `AreaXYZ` task plan (e.g., Tier 1 -> Tier 2 -> Tier 3) with parallel simulation pre-flight
    and closed-loop Real <-> Sim problem-recovery feedback."""
    import cell_area_xyz
    import cell_problem_pipeline as cpp

    run_dir_fn = execute_directive_fn or cell_area_xyz.execute_directive
    work_dir.mkdir(parents=True, exist_ok=True)
    used_candidates: set[str] = set()
    stage_results: list[dict[str, Any]] = []
    sim_reports: list[dict[str, Any]] = []

    executor = ThreadPoolExecutor(max_workers=2) if parallel_sim else None
    try:
        for stage_idx, stage in enumerate(stages):
            stage_name = str(stage.get("stage_id") or f"stage-{stage_idx + 1}")
            candidates = list(stage.get("candidates") or ([stage["directive"]] if "directive" in stage else []))
            avail = [
                c
                for c in candidates
                if str(c.get("candidate_id") or c.get("directive_id")) not in used_candidates
            ]
            if not avail:
                avail = candidates

            if executor is not None:
                futs = [
                    executor.submit(
                        sim_precheck_and_optimize_directive,
                        cand,
                        base_plan,
                        work_dir=work_dir,
                        kinematics_root=kinematics_root,
                    )
                    for cand in avail
                ]
                prechecked = [f.result() for f in futs]
            else:
                prechecked = [
                    sim_precheck_and_optimize_directive(
                        cand, base_plan, work_dir=work_dir, kinematics_root=kinematics_root
                    )
                    for cand in avail
                ]
            sim_reports.append({"stage_id": stage_name, "prechecked": len(prechecked), "reports": prechecked})

            stage_out = None
            for pre in prechecked:
                cand_dir = pre["directive"]
                cand_id = str(cand_dir.get("candidate_id") or cand_dir.get("directive_id") or "cand")
                ledger_fut = executor.submit(cpp.verify_all_in_simulation, work_dir) if executor is not None else None
                res = run_dir_fn(
                    cand_dir,
                    base_plan=base_plan,
                    work_dir=work_dir,
                    act_fn=act_fn,
                    frame_fn=frame_fn,
                    kinematics_root=kinematics_root,
                    max_attempts=max_attempts,
                )
                if ledger_fut is not None:
                    res["parallel_sim_ledger"] = ledger_fut.result()
                stage_out = res
                if res.get("task_verified") or res.get("result") == "placed":
                    used_candidates.add(cand_id)
                    break
            if stage_out is not None:
                stage_results.append({"stage_id": stage_name, **stage_out})
    finally:
        if executor is not None:
            executor.shutdown(wait=False)

    all_verified = bool(stage_results) and all(bool(s.get("task_verified")) for s in stage_results)
    return {
        "schema": "rosy.omx-area-xyz-task-plan-result.v1",
        "stages_completed": len(stage_results),
        "task_verified": all_verified,
        "used_candidates": sorted(used_candidates),
        "sim_precheck": sim_reports,
        "stages": stage_results,
    }
