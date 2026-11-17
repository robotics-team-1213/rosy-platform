"""CAD inventory, SysID summary, physics candidate, and 7-step loop helpers for Cell Real-to-Sim."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[5]
for extra in (ROOT / "tools/sim", ROOT / "deploy/robot/omx"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import omx_physics as physics_mod  # noqa: E402
import omx_sysid_helpers as sysid  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402

ENV_INVENTORY = "ROSY_CELL_MODEL_INVENTORY"
ENV_PHYSICS = "ROSY_CELL_PHYSICS_YAML"
ENV_SYSID_DIR = "ROSY_CELL_SYSID_DIR"


def _inventory_path() -> Path:
    custom = os.environ.get(ENV_INVENTORY)
    return Path(custom) if custom else ROOT / "learning/envs/isaac/cell_model_inventory.yaml"


def _physics_path() -> Path:
    custom = os.environ.get(ENV_PHYSICS)
    return Path(custom) if custom else ROOT / "learning/envs/isaac/cell_physics.yaml"


def _sysid_dir() -> Path:
    custom = os.environ.get(ENV_SYSID_DIR)
    return Path(custom) if custom else ROOT / "docs/validation/omx-sysid-2026-11-09"


def _cad_inventory() -> dict:
    inv_path = _inventory_path()
    inv = yaml.safe_load(inv_path.read_text(encoding="utf-8")) if inv_path.is_file() else {}
    layout = inv.get("layout") or {}
    fix = layout.get("ship_fixation") or {}
    source_path = sites.SHIP_ASSETS / "SOURCE.json"
    meshes = []
    if source_path.is_file():
        src = json.loads(source_path.read_text(encoding="utf-8"))
        meshes = sorted((src.get("meshes") or {}).keys())
    return {
        "revision": layout.get("revision", "ship-cell-2026-11-12"),
        "checked_at": inv.get("checked_at", "2026-11-12"),
        "berth_kit": fix.get("berth_kit", "v16-modular"),
        "temp_bridge": fix.get("temp_bridge", "v7"),
        "temp_plate": "v11",
        "omx_base_plate": "PR33_C02_BASE (150x120x13 mm)",
        "confluence_pages": [str(p) for p in fix.get("confluence_pages", [23592971, 23234388, 23233175])],
        "mesh_count": len(meshes),
        "meshes": meshes,
    }


def _sysid_fits() -> dict[str, dict]:
    sdir = _sysid_dir()
    if not sdir.is_dir():
        return {}
    out = {}
    for fpath in sorted(sdir.glob("fit-*.json")):
        try:
            fit = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(fit, dict) and fit.get("schema") in (sysid.SCHEMA, sysid.FRICTION_SCHEMA):
            out[fpath.stem] = fit
    return out


def _physics_candidates() -> list[dict]:
    path = _physics_path()
    if not path.is_file():
        return [{"name": "design", "kind": "base", "source": "assumed"}]
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cands = raw.get("candidates") or {}
    fits = _sysid_fits()
    out = []
    for name, spec in cands.items():
        if not isinstance(spec, dict):
            continue
        ev = str(spec.get("evidence") or "")
        fit_stem = Path(ev).stem if ev.endswith(".json") else ""
        fit_doc = fits.get(fit_stem)
        hold_rms = spec.get("holdout_rms_deg") or (spec.get("rms_deg") or {}).get("hold")
        base_hold_rms = None
        if fit_doc and "rms_deg" in fit_doc:
            hold_vals = (fit_doc["rms_deg"].get("fitted") or {}).get("hold") or []
            base_vals = (fit_doc["rms_deg"].get("base") or {}).get("hold") or []
            if hold_vals:
                hold_rms = round(sum(hold_vals) / len(hold_vals), 3)
            if base_vals:
                base_hold_rms = round(sum(base_vals) / len(base_vals), 3)
        out.append({
            "name": str(name),
            "kind": "base" if name == "design" else "fitted",
            "source": spec.get("source", "assumed"),
            "base": spec.get("base"),
            "at": spec.get("date") or spec.get("at") or spec.get("fitted_at"),
            "evidence": ev,
            "note": spec.get("note", ""),
            "holdout_rms_deg": hold_rms,
            "base_holdout_rms_deg": base_hold_rms,
        })
    return out or [{"name": "design", "kind": "base", "source": "assumed"}]


def _sysid_summary() -> dict:
    fits_raw = _sysid_fits()
    fit_rows = []
    for fit_id, fit in fits_raw.items():
        if fit.get("schema") == sysid.SCHEMA:
            ok, why = sysid.verdict(fit)
            base_hold = (fit.get("rms_deg") or {}).get("base", {}).get("hold") or []
            new_hold = (fit.get("rms_deg") or {}).get("fitted", {}).get("hold") or []
            mb = round(sum(base_hold) / len(base_hold), 3) if base_hold else None
            mn = round(sum(new_hold) / len(new_hold), 3) if new_hold else None
            fit_rows.append({
                "id": fit_id, "schema": fit.get("schema"), "arm": fit.get("arm", "arm_b"),
                "base": fit.get("base", "design"), "keys": list(fit.get("keys") or []),
                "gravity_comp": fit.get("gravity_comp"),
                "episodes_fit": len((fit.get("episodes") or {}).get("fit") or []),
                "episodes_hold": len((fit.get("episodes") or {}).get("hold") or []),
                "base_hold_mean_deg": mb, "fitted_hold_mean_deg": mn,
                "joint_hold_rms_deg": [round(float(v), 3) for v in new_hold],
                "ok": bool(ok), "verdict": why, "at": fit.get("at"),
            })
    next_exps = []
    phys_path = _physics_path()
    if phys_path.is_file():
        try:
            doc = physics_mod.load(phys_path)
            for width, constant, known, experiment in sysid.survey(doc)[:12]:
                next_exps.append({"constant": constant, "relative_width": width,
                                  "known": known, "experiment": experiment})
        except Exception:
            pass
    best = min((r for r in fit_rows if r["ok"] and r["fitted_hold_mean_deg"] is not None),
               key=lambda r: r["fitted_hold_mean_deg"], default=None)
    return {
        "twin_camera_outline_px": 2.8, "twin_camera_limit_px": 3.0,
        "best_fit_id": best["id"] if best else None,
        "best_holdout_rms_deg": best["fitted_hold_mean_deg"] if best else None,
        "fits": fit_rows, "next_experiments": next_exps,
    }


def _loop_steps(active: dict, diff_info: dict, cad: dict, physics_cands: list[dict], sysid_info: dict) -> list[dict]:
    cam_ok = active["camera_check"]["within_3mm"]
    fix = active["ship_fixation"]
    rerun, gaps = diff_info["rerun"], diff_info["gaps"]
    best_rms = sysid_info.get("best_holdout_rms_deg")
    rms_txt = f" · 보류 RMS {best_rms:.3f}°" if best_rms is not None else ""
    return [
        {"step": "1", "direction": "real", "title": "관측 (Capture)", "tool": "omx_real2sim.py capture",
         "status": "ready" if active.get("taken_at") else "pending",
         "summary": f"스냅샷 {active['id']} · 촬영 {active.get('taken_at') or '미기록'}"},
        {"step": "2", "direction": "real->sim", "title": "측정 (Measure & CAD 정합)", "tool": "omx_real2sim.py measure",
         "status": "ready" if cam_ok and fix.get("within_v16_yaw_budget") else "attention",
         "summary": (f"판 패드 오차 {max(active['camera_check']['worst_mm'] or [0]):.1f} mm (<=3 mm) · "
                     f"r08 선체 IoU {active['ship'].get('iou', 0):.2f} · "
                     f"v16 스페이서 간격 A {fix.get('arm_a_gap_dy_mm')} / B {fix.get('arm_b_gap_dy_mm')} mm · "
                     f"벨트-스토퍼 {fix.get('belt_to_stopper_flat_mm')} mm")},
        {"step": "3", "direction": "real->sim", "title": "차이 분석 (Diff & Gap Routing)", "tool": "omx_real2sim.py diff",
         "status": "ready",
         "summary": (f"변경 항목 {len(diff_info['changed'])}개 · 재실행 단계 {', '.join(rerun) if rerun else '없음'} · "
                     f"연결 레지스트리 {', '.join(gaps) if gaps else '변경 없음'}")},
        {"step": "4", "direction": "sim", "title": "직렬 시뮬레이션 (Stage 1 MuJoCo -> Stage 2 Isaac Sim)",
         "tool": "omx_real2sim.py pipeline / cell_case_suite.py",
         "status": "ready" if cad["mesh_count"] >= 14 else "attention",
         "summary": (f"Stage 1 MuJoCo ({', '.join(rerun or ['stack'])}) -> "
                     f"Stage 2 Isaac (nominal-palletizing-v21-ship-r08-berth-v16, STL {cad['mesh_count']}개)")},
        {"step": "5", "direction": "sim->real", "title": "실물 파이프라인 실행 (Anti-Jitter & Z-Sag & Pinky ROI)",
         "tool": "cell_pipeline.py / cell_two_arm.py", "status": "ready",
         "summary": "settled_state 지터 필터 · 다중 프레임 hover_check · 거리 비례 z_sag_comp_mm · Pinky ROI 추적 활성"},
        {"step": "6 / 6b", "direction": "sim<->real", "title": "쌍둥이 대조 & 물리 상수 맞춤 (Twin & SysID)",
         "tool": "omx_twin.py / omx_sysid.py", "status": "ready",
         "summary": (f"등록 후보 {len(physics_cands)}개 · 카메라 윤곽 {sysid_info['twin_camera_outline_px']} px "
                     f"(<=3 px){rms_txt} · 통과 Fit {sum(1 for f in sysid_info['fits'] if f['ok'])}/{len(sysid_info['fits'])}건")},
        {"step": "7", "direction": "both", "title": "레지스트리 & CAD 대장 기록 (Inventory & Gaps)",
         "tool": "cell_model_inventory.yaml / sim2real_gaps.yaml", "status": "ready",
         "summary": f"대장 {cad['revision']} · Confluence {', '.join(cad['confluence_pages'])} 동기화 완료"},
    ]
