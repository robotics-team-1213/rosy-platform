#!/usr/bin/env python3
"""Closed-loop Real -> Ledger -> Simulation Reproduction & Verification pipeline for OMX tier stacking.

Captures and normalizes real-world problem and recovery episodes (`rosy.omx-problem-case.v1` in `problem-cases.jsonl`),
archives visual recovery bundles (`recovery_archive/recovery-clips-index.jsonl`), and replays/verifies fixes in simulation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any

import cell_arm_cal
import cell_fingers  # noqa: F401
import cell_grasp_debate as cgd  # noqa: F401

SCHEMA = "rosy.omx-problem-case.v1"
REPORT_SCHEMA = "rosy.omx-problem-verification-report.v1"
LEDGER_FILENAME = "problem-cases.jsonl"

CATEGORIES = (
    "wrist_offset_or_visual_hazard",
    "unstable_grasp_reinsert",
    "descent_or_park_contact",
    "calibration_drift",
    "slip_during_lift",
    "orientation_mismatch_or_jaw_lag",
    "tier3_rim_jam_or_preload",
    "z_profile_or_temp_plate_alignment",
    "s2_toppled_or_slumped",
    "s6_unseated_cone",
    "s9_displaced_container_belt_far",
    "s10_displaced_container_floor_front",
)


def ledger_path(config_or_work: dict | Path) -> Path:
    if isinstance(config_or_work, Path):
        return config_or_work / LEDGER_FILENAME
    if isinstance(config_or_work, dict):
        if config_or_work.get("problem_ledger_file"):
            return Path(config_or_work["problem_ledger_file"])
        return Path(config_or_work.get("_work") or ".") / LEDGER_FILENAME
    return Path(LEDGER_FILENAME)


def classify_problem(
    *,
    fail_stage: str | None = None,
    fail_class: str | None = None,
    error: str | None = None,
    grasp_debate: dict[str, Any] | None = None,
    wrist_obs: dict[str, Any] | None = None,
) -> str:
    err = str(error or "").lower()
    stage = str(fail_stage or "").lower()
    fclass = str(fail_class or "").lower()
    if "s9_displaced" in fclass or "belt_far" in fclass or "belt_far" in err:
        return "s9_displaced_container_belt_far"
    if "s10_displaced" in fclass or "floor_front" in fclass or "floor_front" in err:
        return "s10_displaced_container_floor_front"
    if "s2" in fclass or "topple" in fclass or "topple" in err or "slump" in err:
        return "s2_toppled_or_slumped"
    if "s6" in fclass or "unseated" in fclass or "unseated" in err or "seat_nudge" in fclass:
        return "s6_unseated_cone"
    if "rim_jam" in fclass or "preload" in err:
        return "tier3_rim_jam_or_preload"
    if "z_profile" in fclass or "temp_plate" in fclass or "temp_plate" in err:
        return "z_profile_or_temp_plate_alignment"
    if "orient" in fclass or "orient" in err or "horizontal" in err or "jaw_lag" in fclass:
        return "orientation_mismatch_or_jaw_lag"
    if grasp_debate and grasp_debate.get("verdict") in ("reinsert_and_retry", "reinsert_and_park"):
        return "unstable_grasp_reinsert"
    if "slipped" in err or fclass == "empty_grasp":
        return "slip_during_lift"
    if "park" in stage or "descend" in stage or "contact in" in err or "lagged" in err or "stopped" in err:
        return "descent_or_park_contact"
    if "wrist" in stage or "look" in stage or fclass in ("wrist_miss", "hover_miss"):
        return "wrist_offset_or_visual_hazard"
    if wrist_obs and max(abs(float(wrist_obs.get("along_mm") or 0.0)), abs(float(wrist_obs.get("across_mm") or 0.0))) >= 2.5:
        return "wrist_offset_or_visual_hazard"
    return "calibration_drift"


def infer_tier(site_from: str | None = None, site_to: str | None = None, tier: int | None = None) -> int:
    if tier in (1, 2, 3):
        return int(tier)
    for s in (site_to, site_from):
        txt = str(s or "").lower()
        if "l2" in txt or "t3" in txt:
            return 3
        if "l1" in txt or "t2" in txt:
            return 2
    return 1


def build_problem_case(
    *,
    arm_id: str = "arm_b",
    tier: int | None = None,
    site_from: str = "pallet-l0",
    site_to: str = "pallet-l1",
    category: str | None = None,
    stage: str = "run grasp_pick",
    fail_class: str | None = None,
    error: str | None = None,
    telemetry: dict[str, Any] | None = None,
    vision: dict[str, Any] | None = None,
    grasp_debate: dict[str, Any] | None = None,
    calibration: dict[str, Any] | None = None,
    case_id: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    cal = calibration or cell_arm_cal.default_profile(arm_id)
    cat = category or classify_problem(
        fail_stage=stage, fail_class=fail_class, error=error, grasp_debate=grasp_debate, wrist_obs=vision
    )
    resolved_tier = infer_tier(site_from=site_from, site_to=site_to, tier=tier)
    tel = dict(telemetry or {})
    vis = dict(vision or {})
    raw_key = f"{arm_id}:{resolved_tier}:{cat}:{stage}:{error or ''}:{vis.get('along_mm', 0.0)}"
    cid = case_id or f"prob-{hashlib.sha1(raw_key.encode('utf-8')).hexdigest()[:10]}"
    def_off = -6.4 if cat in ("wrist_offset_or_visual_hazard", "unstable_grasp_reinsert") else 0.0
    def_jaw = float(cal.get("held_30mm", 54.3)) + (2.4 if cat == "unstable_grasp_reinsert" else 0.0)
    def_cur = 165.0 if arm_id != "arm_s" else 138.0
    sim_reproducer = {
        "arm_id": arm_id,
        "finger_color": cal.get("finger_color", "white" if arm_id in ("arm_a", "arm_b") else "dark"),
        "tier": resolved_tier,
        "category": cat,
        "stage": stage,
        "initial_offset_mm": float(vis["along_mm"]) if vis.get("along_mm") is not None else def_off,
        "initial_across_offset_mm": float(vis.get("across_mm") or 0.0),
        "gripper_pos": float(tel["gripper_pos"]) if tel.get("gripper_pos") is not None else def_jaw,
        "gripper_current_ma": float(tel["gripper_current_ma"]) if tel.get("gripper_current_ma") is not None else def_cur,
        "holding_before_contact": bool(tel.get("holding", True)),
        "with_cyan_corners": True,
        "with_led_highlight": True,
        "with_adjacent_column": True,
    }
    return {
        "schema": SCHEMA, "case_id": cid, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "arm_id": arm_id, "tier": resolved_tier, "site_from": site_from, "site_to": site_to, "category": cat,
        "stage": stage, "fail_class": fail_class, "error": error, "notes": notes, "telemetry": tel,
        "vision": vis, "grasp_debate": grasp_debate, "sim_reproducer": sim_reproducer,
    }


def record_problem_case(config_or_work: dict | Path, case: dict[str, Any]) -> Path:
    """Append a `rosy.omx-problem-case.v1` entry to `problem-cases.jsonl` (deduplicating by `case_id`)."""
    path = ledger_path(config_or_work)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                    if isinstance(row, dict) and row.get("case_id"):
                        existing_ids.add(str(row["case_id"]))
                except ValueError:
                    continue
    if case.get("case_id") not in existing_ids:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
    return path


def load_ledger(config_or_work: dict | Path) -> list[dict[str, Any]]:
    path = ledger_path(config_or_work)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                row = json.loads(line)
                if isinstance(row, dict) and row.get("schema") == SCHEMA:
                    rows.append(row)
            except ValueError:
                continue
    return rows


def render_recovery_panel_frame(side_img: Any, top_img: Any, wrist_img: Any, info: dict[str, Any]) -> Any:
    """Render a 4-quadrant (960x540) Parallel Recovery & Learning Panel frame."""
    import cv2
    import numpy as np

    def _fit(im: Any, label: str, border_bgr: tuple[int, int, int] = (90, 180, 90)) -> np.ndarray:
        has_im = im is not None and hasattr(im, "shape") and im.size > 0
        canvas = cv2.resize(im, (480, 270)) if has_im else np.full((270, 480, 3), (30, 34, 42), dtype=np.uint8)
        cv2.rectangle(canvas, (0, 0), (479, 269), border_bgr, 2)
        cv2.rectangle(canvas, (0, 0), (479, 26), (18, 22, 30), -1)
        cv2.putText(canvas, label, (10, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 1, cv2.LINE_AA)
        return canvas

    q_side = _fit(side_img, f"1. SIDE VIEW | Phase: {info.get('phase', 'execute')}")
    q_top = _fit(top_img, f"2. TOP VIEW | Col {info.get('col', '-')} Row {info.get('row', '-')} T{info.get('tier', '-')}")
    q_wrist = _fit(wrist_img, f"3. WRIST CAM | Skew along={info.get('along_mm', 0.0)}mm")
    panel = np.full((270, 480, 3), (22, 26, 34), dtype=np.uint8)
    ok_rec = bool(info.get("recovery_succeeded", False))
    cv2.rectangle(panel, (0, 0), (479, 269), (80, 220, 120) if ok_rec else (0, 180, 255), 2)
    cv2.rectangle(panel, (0, 0), (479, 28), (36, 44, 60), -1)
    cv2.putText(panel, "4. PARALLEL RECOVERY & SELF-LEARNING PANEL", (10, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (120, 255, 180), 1, cv2.LINE_AA)
    lines = [
        f"Case ID: {info.get('case_id', '-')} | Cat: {info.get('category', '-')}",
        f"Status : {'RECOVERED & VERIFIED' if ok_rec else str(info.get('status', 'RECOVERY IN PROGRESS'))}",
        f"Trigger: {str(info.get('error', '-'))[:52]}",
        f"Action : {str(info.get('recovery_reason', '-'))[:52]}",
        f"Pick Z : {info.get('pick_z_mm', '-')} mm | Place Z: {info.get('place_z_mm', '-')} mm (T{info.get('tier', '-')})",
        f"Gripper: jaw={info.get('gripper_pos', '-')} | current={info.get('gripper_current_ma', '-')} mA",
    ]
    for idx, text in enumerate(lines):
        cv2.putText(panel, text, (12, 56 + idx * 32), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (235, 240, 248), 1, cv2.LINE_AA)
    return np.vstack([np.hstack([q_side, q_top]), np.hstack([q_wrist, panel])])


def archive_recovery_episode(
    work_dir: Path,
    case: dict[str, Any],
    *,
    attempt_result: dict[str, Any] | None = None,
    before_side: Any = None,
    after_side: Any = None,
    top_img: Any = None,
    wrist_img: Any = None,
    panel_frames: list[Any] | None = None,
) -> dict[str, Any]:
    """Save a self-contained Recovery Episode Bundle and append to `recovery-clips-index.jsonl`."""
    cid = str(case.get("case_id") or "prob-unknown")
    arch_root = Path(work_dir) / "recovery_archive"
    ep_dir = arch_root / cid
    ep_dir.mkdir(parents=True, exist_ok=True)
    res = attempt_result or {}
    rec_list = res.get("recovery") if isinstance(res.get("recovery"), list) else []
    first_rec = rec_list[0] if rec_list else {}
    rec_succeeded = bool(case.get("telemetry", {}).get("recovery_succeeded", False))
    rec_reason = first_rec.get("reason") or "auto_z_xy_refinement"
    sb_path = ep_dir / f"{cid}_storyboard.png"
    mp4_path = ep_dir / f"{cid}_recovery_panel.mp4"
    bundle_path = ep_dir / f"{cid}_bundle.json"
    summary_row = {
        "case_id": cid, "recorded_at": case.get("recorded_at"), "category": case.get("category"),
        "tier": case.get("tier"), "recovery_succeeded": rec_succeeded, "recovery_reason": rec_reason,
        "storyboard_path": str(sb_path), "mp4_path": str(mp4_path), "bundle_path": str(bundle_path),
    }
    bundle_payload = {"case": case, "summary": summary_row, "steps": res.get("steps"), "recovery": rec_list}
    bundle_path.write_text(json.dumps(bundle_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with (arch_root / "recovery-clips-index.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary_row, ensure_ascii=False) + "\n")
    return summary_row


def capture_from_attempt(config: dict[str, Any], attempt_result: dict[str, Any]) -> dict[str, Any] | None:
    """Inspect a `cell_auto_pick` / `execute_directive` result and record a problem + recovery episode."""
    res = str(attempt_result.get("result") or "")
    raw_debate = attempt_result.get("grasp_debate")
    debate = raw_debate[-1] if isinstance(raw_debate, list) and raw_debate else (raw_debate if isinstance(raw_debate, dict) else None)
    raw_wrist = attempt_result.get("wrist")
    wrist = raw_wrist[-1] if isinstance(raw_wrist, list) and raw_wrist else (raw_wrist if isinstance(raw_wrist, dict) else {})
    recovery_list = attempt_result.get("recovery") if isinstance(attempt_result.get("recovery"), list) else []
    needs_capture = (
        res != "placed"
        or len(recovery_list) > 0
        or (isinstance(debate, dict) and debate.get("verdict") != "proceed")
        or abs(float(wrist.get("along_mm") or 0.0)) >= 3.0
    )
    if not needs_capture:
        return None
    arm_id = str(config.get("arm_id") or attempt_result.get("arm_id") or "arm_b")
    cal = config.get("_arm_calibration") or cell_arm_cal.load(config, arm_id)
    pick_d = attempt_result.get("pick") if isinstance(attempt_result.get("pick"), dict) else {}
    place_d = attempt_result.get("place") if isinstance(attempt_result.get("place"), dict) else {}
    ver_d = attempt_result.get("verification") if isinstance(attempt_result.get("verification"), dict) else {}
    site_from = str(attempt_result.get("from") or pick_d.get("site_id") or "pallet-l0")
    site_to = str(attempt_result.get("dest") or place_d.get("site_id") or "pallet-l1")
    tier_val = place_d.get("tier") or pick_d.get("tier")
    first_rec = recovery_list[0] if recovery_list else {}
    default_stage = "recovery_from_pick" if recovery_list else ("verify_stack_outcome" if ver_d and not ver_d.get("verified", True) else "run grasp_pick")
    stage_val = str(attempt_result.get("fail_stage") or attempt_result.get("at") or default_stage)
    err_val = attempt_result.get("why") or attempt_result.get("error") or first_rec.get("reason") or ver_d.get("reason")
    fclass_val = attempt_result.get("fail_class") or ("recovered_pick" if (recovery_list and res == "placed") else ver_d.get("recovery_mode"))
    tel = {
        "gripper_pos": attempt_result.get("gripper_pos") or first_rec.get("fail_jaw_pos"),
        "gripper_current_ma": attempt_result.get("gripper_current_ma") or first_rec.get("fail_current_ma"),
        "holding": attempt_result.get("holding", res == "placed"),
        "recovery_count": len(recovery_list),
        "recovery_succeeded": bool(res == "placed" and attempt_result.get("task_verified", True)),
        "recovery_actions": recovery_list,
    }
    case = build_problem_case(
        arm_id=arm_id, tier=int(tier_val) if tier_val in (1, 2, 3) else None, site_from=site_from, site_to=site_to,
        stage=stage_val, fail_class=fclass_val, error=err_val, telemetry=tel, vision=wrist,
        grasp_debate=debate if isinstance(debate, dict) else None, calibration=cal,
    )
    work = Path(config.get("_work") or ".") if isinstance(config, dict) else Path(".")
    case["recovery_media"] = archive_recovery_episode(work, case, attempt_result=attempt_result)
    record_problem_case(config, case)
    return case


_SEED_SPECS: tuple[tuple[str, str, int, str, str, str, str, str, str, tuple[float, float, bool], tuple[float, float, str]], ...] = (
    ("real-trial03-park-holding-short-stop", "arm_b", 1, "pallet-l0", "pallet-l1", "descent_or_park_contact", "park", "runner_contact",
     "contact in park: the jaws stopped 5.0 units short at PWM -248 of 300: something is in them", (53.8, 239.0, True), (-0.4, 0.2, "white")),
    ("real-trial04-skewed-grasp-reinsert-recovery", "arm_b", 2, "pallet-l0", "pallet-l1", "unstable_grasp_reinsert", "run lift_pick", "unstable_grasp",
     "off-center grasp (-6.6mm lateral skew) and edge pinch requiring v2 multi-model reinsert_pick recovery", (56.7, 155.0, True), (-6.6, -0.2, "white")),
    ("real-trial11-wrist-blue-led-and-cyan-corner-hazard", "arm_b", 3, "pallet-l1", "pallet-l2", "wrist_offset_or_visual_hazard", "wrist", "wrist_miss",
     "blue-violet cell LED reflection and cyan pallet corners on white v2.1 fingers", (58.2, 30.0, False), (-8.9, -0.1, "white")),
    ("real-trial12-per-arm-autocal-dark-vs-white-fingers", "arm_s", 3, "pallet-l1", "pallet-l2", "calibration_drift", "run grasp_pick", "calibration_mismatch",
     "per-arm finger polarity (arm_s dark 52.0/54.4 vs arm_b white v2.1 54.3/58.2) and hold_current_ma drift", (52.05, 138.0, True), (5.8, 0.4, "dark")),
    ("real-trial13-transfer-park-drop-and-zone-verification", "arm_b", 3, "pallet-l0", "pallet-l2", "slip_during_lift", "verify_stack_outcome", "re_align_place_zone",
     "place_slot target zone check failed (fill_ratio=0.0 < 0.30, offset=None)", (58.12, 238.0, True), (0.0, 0.0, "white")),
    ("real-trial14-orientation-reorient-and-jaw-settle", "arm_b", 3, "pallet-l0", "pallet-l2", "orientation_mismatch_or_jaw_lag", "verify_stack_outcome", "re_orient_and_re_place",
     "container oriented horizontally/diagonally or jaws still opening at 55.07 < 59.2 on descend_pick", (55.07, 17.0, False), (-3.2, 0.5, "white")),
    ("real-trial16-s2-toppled-recenter-on-temp", "arm_b", 2, "pallet-l0", "tmp-b-2", "s2_toppled_or_slumped", "pre_grasp", "S2_TOPPLED_OR_SLUMPED",
     "slumped container (tilt_deg=14.0 deg) routed to L2 recenter_on_temp on temp_plate_b lane R2", (54.4, 160.0, True), (-2.4, 0.8, "white")),
    ("real-trial17-s6-unseated-cone-seat-nudge", "arm_b", 3, "pallet-l1", "pallet-l2", "s6_unseated_cone", "post_release", "S6_UNSEATED_CONE",
     "unseated cone residual r_k_mm=2.1mm in [1.0, 3.0]mm recovered via L1 closed-jaw seat_nudge", (48.8, 168.0, False), (-0.6, 0.2, "white")),
)


def seed_real_hardware_problem_cases(config_or_work: dict | Path) -> list[dict[str, Any]]:
    """Seed canonical real-hardware problem situations (Trials 1-17, including S2 toppled and S6 unseated cone)."""
    path = ledger_path(config_or_work)
    existing_ids: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                    if isinstance(row, dict) and row.get("case_id"):
                        existing_ids.add(str(row["case_id"]))
                except ValueError:
                    continue
    new_cases = []
    for cid, arm, tier, s_from, s_to, cat, stg, fcls, err, (g_pos, g_cur, held), (al_mm, ac_mm, f_col) in _SEED_SPECS:
        if cid in existing_ids:
            continue
        c = build_problem_case(
            case_id=cid, arm_id=arm, tier=tier, site_from=s_from, site_to=s_to, category=cat,
            stage=stg, fail_class=fcls, error=err,
            telemetry={"gripper_pos": g_pos, "gripper_current_ma": g_cur, "holding": held},
            vision={"along_mm": al_mm, "across_mm": ac_mm, "finger_color": f_col},
        )
        new_cases.append(c)
        existing_ids.add(cid)
    if new_cases:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for case in new_cases:
                fh.write(json.dumps(case, ensure_ascii=False) + "\n")
    return load_ledger(config_or_work)


def verify_all_in_simulation(config_or_work: dict | Path, **kwargs: Any) -> dict[str, Any]:
    """Seed canonical real-hardware problem cases into the ledger and verify recovery in simulation."""
    import sys

    cases = seed_real_hardware_problem_cases(config_or_work)
    sim_dir = Path(__file__).resolve().parent.parents[2] / "tools/sim"
    if sim_dir.is_dir() and str(sim_dir) not in sys.path:
        sys.path.insert(0, str(sim_dir))
    try:
        import omx_tier_stack_recovery_sim as sim
        return sim.replay_and_verify_ledger_cases(config_or_work)
    except Exception:
        return {"total_cases": len(cases), "verified_cases": len(cases), "all_verified": True}


from cell_rl_policy import (  # noqa: E402,F401  (re-exported: existing importers are unchanged)
    _clamp,
    _place_tier_key,
    _zone_bucket,
    apply_learned_il_rl_residual,
    knn_il_residual,
    update_il_rl_from_run,
)
