"""Real-to-Sim / Sim-to-Real closed-loop pipeline service for the Cell workspace (D-947, D-1012).

Absorbs the 7-step OMX Real-to-Sim <-> Sim-to-Real loop into the Fleet Cell backend:
  1. Reads committed cell snapshots (`deploy/robot/omx/sim/cell_snapshots/*.json`), CAD inventory
     (`learning/envs/isaac/cell_model_inventory.yaml` + `SOURCE.json`), and physics candidates
     (`learning/envs/isaac/cell_physics.yaml`).
  2. Evaluates snapshot diffs (`temp_plates`, `ship`, `belt`, `arm_bases`, `ship_fixation` v16-modular),
     affected simulation stages (`rehandle`, `outbound`, `matrix-a`, `matrix-b`, `stack`), and sim2real gap IDs.
  3. Builds the D-1012 2-stage pipeline (`Stage 1: MuJoCo` -> `Stage 2: Isaac Sim` `rosy.omx-isaac-handoff.v1`
     + separate `Gazebo` ROS 2 execution contract track).
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import sys

from fleet.server.cell_real2sim_helpers import (
    ENV_INVENTORY,
    ENV_PHYSICS,
    ENV_SYSID_DIR,
    ROOT,
    _cad_inventory,
    _inventory_path,
    _loop_steps,
    _physics_candidates,
    _physics_path,
    _sysid_dir,
    _sysid_fits,
    _sysid_summary,
)

for extra in (ROOT / "tools/sim", ROOT / "deploy/robot/omx"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import omx_real2sim as r2s  # noqa: E402
import omx_sysid_helpers as sysid  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402

SCHEMA = "rosy.cell-real2sim-pipeline.v1"
RUN_SCHEMA = "rosy.cell-real2sim-run.v1"
ENV_SNAPSHOTS = "ROSY_CELL_SNAPSHOTS_DIR"
ENV_RUNS_FILE = "ROSY_CELL_PIPELINE_RUNS"

__all__ = [
    "ENV_INVENTORY",
    "ENV_PHYSICS",
    "ENV_RUNS_FILE",
    "ENV_SNAPSHOTS",
    "ENV_SYSID_DIR",
    "ROOT",
    "RUN_SCHEMA",
    "SCHEMA",
    "_cad_inventory",
    "_inventory_path",
    "_load_snapshot_file",
    "_loop_steps",
    "_physics_candidates",
    "_physics_path",
    "_runs_path",
    "_snapshots_dir",
    "_summarize_snapshot",
    "_sysid_dir",
    "_sysid_fits",
    "_sysid_summary",
    "list_pipeline_runs",
    "promote_physics_candidate",
    "queue_pipeline_run",
    "view",
]


def _snapshots_dir() -> Path:
    custom = os.environ.get(ENV_SNAPSHOTS)
    return Path(custom) if custom else ROOT / "deploy/robot/omx/sim/cell_snapshots"


def _runs_path(default_path: Path | None = None) -> Path:
    custom = os.environ.get(ENV_RUNS_FILE)
    if custom:
        return Path(custom)
    if default_path is not None:
        return default_path
    return ROOT / "Rosy/artifacts/cell-real2sim-runs.json"


def _load_snapshot_file(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != r2s.SCHEMA or not isinstance(data.get("items"), dict):
        raise ValueError(f"not a {r2s.SCHEMA} snapshot: {path.name}")
    return data


def _summarize_snapshot(snap_id: str, data: dict, layout: sites.Layout) -> dict:
    items = data.get("items") or {}
    tp = items.get("temp_plates") or {}
    plates = tp.get("plates") or {}
    cam_check = tp.get("camera_check") or {}
    worst = cam_check.get("worst_mm") or [0.0, 0.0]
    ship = items.get("ship") or {}
    belt = items.get("belt") or {}
    fix = r2s.measure_ship_fixation(ship, belt, layout)
    return {
        "id": snap_id,
        "taken_at": data.get("taken_at"),
        "camera_motion": data.get("camera_motion") or {"checked": False},
        "camera_check": {
            "pads": cam_check.get("pads", 0),
            "worst_mm": worst,
            "within_3mm": bool(worst and max(float(v) for v in worst) <= 3.0),
        },
        "temp_plates": {
            "plates": {k: len(v) for k, v in plates.items() if isinstance(v, list)},
            "seen": tp.get("seen") or {},
            "shape": tp.get("shape"),
        },
        "ship": ship,
        "belt": belt,
        "arm_bases": items.get("arm_bases") or {},
        "ship_fixation": fix,
    }


def list_pipeline_runs(runs_path: Path | None = None) -> list[dict]:
    path = _runs_path(runs_path)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def queue_pipeline_run(body: dict, *, actor_id: str = "operator", runs_path: Path | None = None) -> dict:
    evaluated = view(
        body.get("snapshot_id"), body.get("prev_id"), custom_snapshot=body.get("snapshot"),
        berth_kit=str(body.get("berth_kit") or "v16-modular"),
        ship_spacer_dy_mm=float(body.get("ship_spacer_dy_mm", 39.0)),
        ship_stern_hook_mm=float(body.get("ship_stern_hook_mm", 0.0)),
        compensate_zero=bool(body.get("compensate_zero", True)),
        cam_jitter=bool(body.get("cam_jitter", True)),
        physics=str(body.get("physics") or "twin-kp-20261109"), runs_path=runs_path,
    )
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    existing = list_pipeline_runs(runs_path)
    snap_id = evaluated["active"]["id"]
    run_id = f"r2s-{snap_id}-{len(existing) + 1:03d}"
    mujoco_stage = next((s for s in evaluated["stages"] if s["stage"] == "mujoco"), {})
    isaac_stage = next((s for s in evaluated["stages"] if s["stage"] == "isaac"), {})
    rel_snap = f"deploy/robot/omx/sim/cell_snapshots/{snap_id}.json"
    cli_cmd = (
        f"python3 tools/sim/omx_real2sim.py pipeline {rel_snap}"
        + (f" --prev deploy/robot/omx/sim/cell_snapshots/{evaluated['previous']['id']}.json" if evaluated.get("previous") else "")
        + f" --berth-kit {evaluated['cad_inventory']['berth_kit'] if body.get('berth_kit') is None else body.get('berth_kit')}"
        + f" --ship-spacer-dy-mm {float(body.get('ship_spacer_dy_mm', 39.0)):g}"
        + f" --ship-stern-hook-mm {float(body.get('ship_stern_hook_mm', 0.0)):g}"
        + f" --physics {body.get('physics') or 'twin-kp-20261109'}"
    )
    record = {
        "schema": RUN_SCHEMA, "run_id": run_id, "created_at": now, "created_by": actor_id, "status": "QUEUED",
        "snapshot_id": snap_id, "prev_id": (evaluated.get("previous") or {}).get("id"),
        "berth_kit": str(body.get("berth_kit") or "v16-modular"),
        "physics": str(body.get("physics") or "twin-kp-20261109"),
        "rerun_stages": evaluated["diff"]["rerun"], "gaps": evaluated["diff"]["gaps"],
        "stage1_commands": mujoco_stage.get("commands", {}),
        "isaac_handoff": isaac_stage.get("isaac_handoff", {}), "cli_command": cli_cmd,
    }
    updated = [record, *existing][:50]
    target = _runs_path(runs_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"run": record, "runs": updated}


def promote_physics_candidate(
    fit_id: str,
    candidate_name: str,
    *,
    actor_id: str = "operator",
    custom_fit: dict | None = None,
) -> dict:
    name = (candidate_name or "").strip()
    if not name:
        raise ValueError("candidate_name is required")
    fits = _sysid_fits()
    if custom_fit is not None:
        fit = custom_fit
        ev = f"custom:{fit_id or name}"
    else:
        if fit_id not in fits:
            raise KeyError(f"sysid fit not found: {fit_id}")
        fit = fits[fit_id]
        ev = f"docs/validation/omx-sysid-2026-11-09/{fit_id}.json"
    try:
        why = sysid.promote(fit, name, evidence=ev, path=_physics_path())
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc
    return {
        "promoted": name,
        "fit_id": fit_id,
        "verdict": why,
        "promoted_by": actor_id,
        "physics_candidates": _physics_candidates(),
        "sysid_summary": _sysid_summary(),
    }


def view(
    snapshot_id: str | None = None,
    prev_id: str | None = None,
    *,
    custom_snapshot: dict | None = None,
    berth_kit: str = "v16-modular",
    ship_spacer_dy_mm: float = 39.0,
    ship_stern_hook_mm: float = 0.0,
    compensate_zero: bool = True,
    cam_jitter: bool = True,
    physics: str = "twin-kp-20261109",
    runs_path: Path | None = None,
) -> dict:
    snap_dir = _snapshots_dir()
    files = sorted(snap_dir.glob("*.json")) if snap_dir.is_dir() else []
    if not files and custom_snapshot is None:
        raise OSError("실물-시뮬 스냅샷 디렉터리에 스냅샷 파일이 없습니다.")
    by_id = {f.stem: f for f in files}
    layout = sites.Layout(
        arm_bases="plate-centre",
        berth_kit=berth_kit,
        temp_bridge="v7",
        ship_spacer_dy_mm=float(ship_spacer_dy_mm),
        ship_stern_hook_mm=float(ship_stern_hook_mm),
    )
    listing = []
    for stem, fpath in sorted(by_id.items(), reverse=True):
        raw = _load_snapshot_file(fpath)
        listing.append({
            "id": stem,
            "taken_at": raw.get("taken_at"),
            "camera_moved": bool((raw.get("camera_motion") or {}).get("moved")),
            "ship_model": ((raw.get("items") or {}).get("ship") or {}).get("model", "r08"),
            "berth_kit": berth_kit,
        })
    if custom_snapshot is not None:
        if not isinstance(custom_snapshot, dict) or custom_snapshot.get("schema") != r2s.SCHEMA:
            raise ValueError(f"not a {r2s.SCHEMA} snapshot")
        active_id = snapshot_id or "custom"
        active_raw = custom_snapshot
    else:
        active_id = snapshot_id or (listing[0]["id"] if listing else "")
        if active_id not in by_id:
            raise KeyError(f"snapshot not found: {active_id}")
        active_raw = _load_snapshot_file(by_id[active_id])

    if prev_id:
        if prev_id not in by_id:
            raise KeyError(f"previous snapshot not found: {prev_id}")
        prev_raw = _load_snapshot_file(by_id[prev_id])
    else:
        older = [s["id"] for s in listing if s["id"] != active_id]
        prev_id = older[0] if older else None
        prev_raw = _load_snapshot_file(by_id[prev_id]) if prev_id else None

    active_raw = dict(active_raw, items=dict(active_raw.get("items") or {}))
    active_raw["items"]["ship_fixation"] = r2s.measure_ship_fixation(
        active_raw["items"].get("ship"), active_raw["items"].get("belt"), layout
    )
    if prev_raw is not None:
        prev_raw = dict(prev_raw, items=dict(prev_raw.get("items") or {}))
        prev_raw["items"]["ship_fixation"] = r2s.measure_ship_fixation(
            prev_raw["items"].get("ship"), prev_raw["items"].get("belt"), layout
        )
        changed, rerun = r2s.diff(prev_raw, active_raw)
    else:
        changed, rerun = {}, sorted(r2s.STAGES)

    diff_info = {
        "changed": changed,
        "rerun": rerun or ["stack"],
        "gaps": sorted({r2s.GAPS[i] for i in changed if i in r2s.GAPS}),
    }
    active_summary = _summarize_snapshot(active_id, active_raw, layout)
    cad = _cad_inventory()
    physics_cands = _physics_candidates()
    sysid_info = _sysid_summary()
    runs = list_pipeline_runs(runs_path)
    rel_snap = f"deploy/robot/omx/sim/cell_snapshots/{active_id}.json"
    extra_choices = [
        f"berth_kit={berth_kit}",
        f"ship_spacer_dy_mm={float(ship_spacer_dy_mm)}",
        f"ship_stern_hook_mm={float(ship_stern_hook_mm)}",
        f"physics={physics}",
    ]
    handoff = {
        "schema": "rosy.omx-isaac-handoff.v1",
        "snapshot": rel_snap,
        "release_case": "nominal-palletizing-v21-ship-r08-berth-v16",
        "berth_kit": berth_kit,
        "temp_bridge": "v7",
        "physics": physics,
        "compensate_zero": bool(compensate_zero),
        "cam_jitter": bool(cam_jitter),
        "ship_fixation": active_summary["ship_fixation"],
    }
    stages = [
        {
            "stage": "mujoco",
            "stage_order": 1,
            "track": "learning_and_physics",
            "role": "stage1_geometry_vision_and_act_policy",
            "rerun": diff_info["rerun"],
            "flags": [
                *(["--cam-jitter"] if cam_jitter else []),
                *(["--compensate-zero"] if compensate_zero else []),
            ],
            "commands": {n: r2s.stage_body(n, rel_snap, extra_choices) for n in diff_info["rerun"]},
        },
        {
            "stage": "isaac",
            "stage_order": 2,
            "track": "learning_and_physics",
            "role": "stage2_physx_contact_pad_slip_and_seating",
            "release_case": handoff["release_case"],
            "isaac_handoff": handoff,
        },
        {
            "stage": "gazebo",
            "stage_order": None,
            "track": "ros2_execution_contract",
            "role": "ros2_interface_conformance",
            "command": "tools/sim/omx_backend_conformance.py",
        },
    ]
    return {
        "schema": SCHEMA,
        "snapshots": listing,
        "active": active_summary,
        "previous": {"id": prev_id, "taken_at": prev_raw.get("taken_at")} if prev_raw else None,
        "diff": diff_info,
        "cad_inventory": cad,
        "physics_candidates": physics_cands,
        "sysid_summary": sysid_info,
        "runs": runs,
        "stages": stages,
        "loop_steps": _loop_steps(active_summary, diff_info, cad, physics_cands, sysid_info),
    }
