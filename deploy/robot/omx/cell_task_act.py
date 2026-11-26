"""ACT task planning for `cell_task_exec.py`: every check that needs no arm session, then the drive plan or a refusal.

Fleet validates physical task bindings. A supervised handoff alone cannot start a learned policy: the run goes through
`cell_task_act_run`, which pushes the runner a renewed 1 s lease (D-1024 3, `chunk_runner_lease`) and moves nothing
unless the runner armed it (`PHYSICAL_POLICY_LEASE_OWNER_UNAVAILABLE`). Presence stays required here (D-911).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any

from cell_policy_timing import finite_stamp
from cell_presence import presence_ok
import cell_diagnose
import cell_site_target
from cell_policy_goals import GOALS, resolve_goal_site

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_TASK_ID_RE = re.compile(r"[A-Za-z0-9._:@-]{1,128}")


def _fail(
    arm_id: str,
    error: str,
    *,
    directive_id: Any = None,
    extra_stop: dict | None = None,
) -> dict[str, Any]:
    fclass = cell_diagnose.classify_failure(f"policy: {error}")["cause"]
    out = {
        "arm": arm_id,
        "error": error,
        "failure_class": fclass,
        "failure_stratum": "human_only",
        "requires_named_approval": True,
        "motion_issued": False,
        "inference_performed": False,
        "stop_event": {"command": "stop", "ok": False, "folded": False, **(extra_stop or {})},
    }
    if directive_id is not None:
        out["stage_result"] = {
            "directive_id": directive_id,
            "arm_id": arm_id,
            "task_verified": False,
            "failure_class": fclass,
            "failure_stratum": "human_only",
            "requires_named_approval": True,
        }
    return out


def _check_ab_policy(handoff: dict, arm_id: str, prep_dir: Path, cfg: Path,
                     cfg_data: dict, policy_cfg: dict) -> dict:
    """Bind a belt-to-h1 policy request without opening an arm session or command FIFO."""
    import cell_lerobot_shadow as lrs

    task_id = handoff.get("task_id")

    def refused(reason: str) -> dict:
        return _fail(arm_id, reason, directive_id=task_id)

    if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id) or ".." in task_id or task_id.startswith("-"):
        return refused("ACT_POLICY_INVALID_ARGS")
    max_chunks = handoff.get("max_chunks", policy_cfg.get("max_chunks", 4))
    if type(max_chunks) is not int or not 1 <= max_chunks <= 6:
        return refused("ACT_POLICY_INVALID_MAX_CHUNKS")
    expected_io = prep_dir / f"chunk-io-{arm_id[-1]}"
    try:
        actual_io = (cfg.parent / Path(cfg_data["io"]).expanduser()).resolve()
        if cfg_data.get("arm_id") != arm_id or expected_io.is_symlink() or actual_io != expected_io.resolve():
            return refused("ACT_POLICY_ARM_BINDING_MISMATCH")
    except (OSError, RuntimeError, ValueError):
        return refused("ACT_POLICY_ARM_BINDING_MISMATCH")
    src, dst, tier = handoff.get("src_site"), handoff.get("dst_site"), handoff.get("tier")
    if src != "belt" or cell_site_target.validate_cell_ab_handoff(src, dst, tier, arm_id):
        return refused("ACT_POLICY_INVALID_TARGET")
    target = cell_site_target.resolve_cell_ab_site(dst, tier, allow_belt_temp=False)
    if not target or not target["site_id"]:
        return refused("ACT_POLICY_INVALID_TARGET")
    try:
        goal, slot = resolve_goal_site(target["site_id"])
    except (OSError, ValueError):
        return refused("ACT_POLICY_INVALID_TARGET")
    sites = cfg_data.get("sites")
    if not isinstance(sites, dict):
        return refused("SITE_NOT_CALIBRATED")
    source = "belt" if "belt" in sites else "beltend"
    source_cfg = sites.get(source)
    if not isinstance(source_cfg, dict):
        return refused("SITE_NOT_CALIBRATED")
    roi, surface = source_cfg.get("auto_roi"), source_cfg.get("surface_z")
    if (type(surface) not in (float, int) or not math.isfinite(surface)
            or not isinstance(roi, list) or len(roi) != 4 or any(type(v) is not int for v in roi)
            or not (0 <= roi[0] < roi[2] and 0 <= roi[1] < roi[3])
            or cell_site_target.calibration_refusal(sites, source, goal, tier)):
        return refused("SITE_NOT_CALIBRATED")
    revision = policy_cfg["policy_revision"].strip()
    try:
        root = Path(policy_cfg["policy_root"].strip()).expanduser()
        if not root.is_absolute() or not root.is_dir() or root.is_symlink():
            return refused("ACT_POLICY_MODEL_BINDING_MISMATCH")
        if lrs.checkpoint_digest(root).get(lrs.WEIGHTS) != revision:
            return refused("ACT_POLICY_MODEL_BINDING_MISMATCH")
        views, _, size = lrs.read_features(json.loads((root / "config.json").read_text(encoding="utf-8")))
        if size != len(GOALS) or lrs.read_sim_rule(root / lrs.UNITS, cfg_data) is None:
            return refused("ACT_POLICY_MODEL_BINDING_MISMATCH")
        from cell_policy_start_gate import read_state_range

        try:
            read_state_range(root)
        except ValueError:
            return refused("POLICY_STATE_STATS_MISSING")  # the exact Fleet refusal code (HARDWARE_REFUSALS)
        cameras = cfg_data.get("cameras")
        if not isinstance(cameras, dict) or not all(cameras.get(view) for view in views):
            return refused("ACT_POLICY_CAMERA_MISSING")
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError):
        return refused("ACT_POLICY_MODEL_BINDING_MISMATCH")
    raw_lib = str(policy_cfg.get("library") or "").strip()  # never the Cell S library by default: A and B name their own
    try:
        library = (prep_dir / raw_lib).resolve()
        if not raw_lib or not library.is_relative_to(prep_dir.resolve()) or not library.is_file():
            return refused("ACT_POLICY_LIBRARY_MISSING")
    except (OSError, RuntimeError, ValueError):
        return refused("ACT_POLICY_LIBRARY_MISSING")
    request = {"weights_sha256": revision, "goal_site": target["site_id"], "goal_slot": slot, "destination": goal}
    return {"plan": {
        "library": library, "roi": roi, "src_site": source, "dst": target["sim_site"], "dst_site": target["area"],
        "goal_site": target["site_id"], "max_chunks": max_chunks, "tid": task_id, "policy_request": request,
    }}


def plan_act_policy_task(
    handoff: dict[str, Any], *, arm_id: str, prep_dir: Path, wrapper: Path, cfg: Path,
    default_roi: tuple[int, int, int, int],
) -> dict[str, Any]:
    """Check an ACT handoff before any owner or motion command: a refusal dict, or {"plan": ...} for `cell_task_act_run`."""
    task_id = handoff.get("task_id")
    cell_id = str(handoff.get("cell_id") or "cell_s").strip()
    cell_ab = cell_id == "cell_ab" and arm_id in ("arm_a", "arm_b")
    if not cell_ab and (cell_id, arm_id) != ("cell_s", "arm_s"):
        return _fail(arm_id, "ACT_POLICY_UNSUPPORTED_ARM")
    if not presence_ok(handoff):
        return _fail(arm_id, "PRESENCE_REQUIRED_FOR_ACT_POLICY")
    if not wrapper.is_file() or not cfg.is_file():
        return _fail(arm_id, "CELL_CONFIG_OR_WRAPPER_MISSING")
    try:
        cfg_data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _fail(arm_id, "ACT_POLICY_CONFIG_INVALID")
    if not isinstance(cfg_data, dict):
        return _fail(arm_id, "ACT_POLICY_CONFIG_INVALID")
    if cfg_data.get("arm_id", arm_id) != arm_id:
        return _fail(arm_id, "ACT_POLICY_ARM_BINDING_MISMATCH", directive_id=task_id)
    if not isinstance(cfg_data.get("io"), str) or not cfg_data["io"]:
        return _fail(arm_id, "ACT_POLICY_CONFIG_MISSING")
    policy_cfg = cfg_data.get("act_policy")  # never fall back to passive act_shadow (D-442)
    req_keys = ("policy_root", "policy_revision", "cell_calibration", "model_calibration")
    if (not isinstance(policy_cfg, dict) or policy_cfg.get("execution_allowed") is not True
            or any(not isinstance(policy_cfg.get(k), str) or not policy_cfg[k].strip() or policy_cfg[k].strip().startswith("-") for k in req_keys)
            or not _SHA256_RE.fullmatch(policy_cfg["policy_revision"].strip())):
        return _fail(arm_id, "ACT_POLICY_CONFIG_MISSING")
    max_obs_age_s = policy_cfg.get("max_obs_age_s", 2.0)
    obs_age = finite_stamp(max_obs_age_s)
    if obs_age is None or not 0 < obs_age <= 5.0:
        return _fail(arm_id, "ACT_POLICY_CONFIG_MISSING")
    if cell_ab:
        return _check_ab_policy(handoff, arm_id, prep_dir, cfg, cfg_data, policy_cfg)
    raw_lib = str(policy_cfg.get("library") or "chunks-arm-s-inplace-live.json").strip()
    try:
        prep_root = prep_dir.resolve()
        library = (prep_dir / raw_lib).resolve()
        in_prep = library.is_relative_to(prep_root)
    except (OSError, RuntimeError, ValueError):
        in_prep = False
    if not in_prep or not library.is_file():
        return _fail(arm_id, "ACT_POLICY_LIBRARY_MISSING")
    raw_chunks = handoff.get("max_chunks", policy_cfg.get("max_chunks", 4))
    if type(raw_chunks) is not int or not 1 <= raw_chunks <= 6:
        return _fail(arm_id, "ACT_POLICY_INVALID_MAX_CHUNKS")
    operator = str(handoff["presence"]["operator"]).strip()
    tid = str(task_id or "").strip()
    src_site = str(handoff.get("src_site") or "pinky").strip().rsplit("-l", 1)[0]
    dst = str(handoff.get("dst_site") or "belt").strip()
    dst_site = dst.rsplit("-l", 1)[0]
    sites = cfg_data.get("sites") if isinstance(cfg_data.get("sites"), dict) else {}
    if (not tid or tid.startswith("-") or ".." in tid or not _TASK_ID_RE.fullmatch(tid)
            or not operator or operator.startswith("-") or not src_site or src_site.startswith("-")
            or not dst or dst.startswith("-")
            or not isinstance(sites.get(src_site), dict) or not isinstance(sites.get(dst_site), dict)):
        return _fail(arm_id, "ACT_POLICY_INVALID_ARGS", directive_id=task_id)
    roi = sites[src_site].get("auto_roi") or default_roi
    if not isinstance(roi, (list, tuple)) or len(roi) != 4 or any(type(v) is not int for v in roi):
        return _fail(arm_id, "ACT_POLICY_CONFIG_MISSING")
    return {"plan": {
        "library": library, "roi": list(roi), "src_site": src_site, "dst": dst, "dst_site": dst_site,
        "goal_site": None, "max_chunks": raw_chunks, "tid": tid, "policy_request": None,
    }}
