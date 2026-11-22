"""Supervised Cell S ACT policy execution helper for `cell_task_exec.py`.

D-911 §4 supervised commissioning path scoped exclusively to `cell_s` / `arm_s`; fail-closed disabled unless host-local
untracked `act_policy` config sets `"execution_allowed": true`, never falling back to passive `act_shadow` (D-442).
Autonomous/unsupervised L3/G4 policy execution remains governed by D-793 / D-1024 `PolicyApprovals`.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import sys
import time
import uuid
from typing import Any

from cell_policy_timing import finite_stamp, park_ack_ok
from cell_presence import presence_ok, zone_acceptance

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_TASK_ID_RE = re.compile(r"[A-Za-z0-9._:@-]{1,128}")


def _fail(arm_id: str, error: str, *, directive_id: Any = None, extra_stop: dict | None = None) -> dict[str, Any]:
    out = {"arm": arm_id, "error": error, "stop_event": {"command": "stop", "ok": False, "folded": False, **(extra_stop or {})}}
    if directive_id is not None:
        out["stage_result"] = {"directive_id": directive_id, "arm_id": arm_id, "task_verified": False}
    return out


def _hold_on_timeout(
    prep_dir: Path,
    cfg_data: dict[str, Any] | None = None,
    *,
    io_base: Path | None = None,
    confirm_wait_s: float = 0.6,
    poll_s: float = 0.05,
) -> tuple[dict[str, str], dict[str, bool]]:
    acks: dict[str, str] = {}
    latched: dict[str, bool] = {}
    candidates: list[tuple[Path, bool]] = []
    if isinstance(cfg_data, dict) and isinstance(cfg_data.get("io"), str) and cfg_data["io"]:
        io_path = Path(cfg_data["io"]).expanduser()
        if not io_path.is_absolute():
            io_path = (io_base if io_base is not None else prep_dir) / io_path
        candidates.append((io_path / "chunk-cmd", True))
    candidates.extend((
        (prep_dir / "chunk-io-s" / "chunk-cmd", False),
        (prep_dir / "chunk-io-s-r2s" / "chunk-cmd", False),
    ))
    seen: set[Path] = set()
    records: list[tuple[Path, Path, str, float | None, float | None, str | None]] = []
    flags = os.O_WRONLY | getattr(os, "O_NONBLOCK", 0)
    for fifo, is_cfg in candidates:
        try:
            resolved = fifo.resolve()
        except (OSError, RuntimeError) as exc:
            if not is_cfg:
                continue
            if fifo in seen:
                continue
            seen.add(fifo)
            records.append((fifo, fifo, f"error: {type(exc).__name__}", None, None, None))
            continue
        if resolved in seen:
            continue
        try:
            exists = fifo.exists()
        except (OSError, RuntimeError) as exc:
            if not is_cfg:
                continue
            seen.add(resolved)
            records.append((fifo, resolved, f"error: {type(exc).__name__}", None, None, None))
            continue
        if not exists:
            if not is_cfg:
                continue
            seen.add(resolved)
            records.append((fifo, resolved, "error: FileNotFoundError", None, None, None))
            continue
        seen.add(resolved)
        pre_t: float | None = None
        try:
            pre_live = json.loads((fifo.parent / "live.json").read_text(encoding="utf-8"))
            pre_t = finite_stamp(pre_live.get("t")) if isinstance(pre_live, dict) else None
        except (OSError, ValueError, RecursionError):
            pass
        hold_req = uuid.uuid4().hex[:12]
        try:
            fd = os.open(str(fifo), flags)
            try:
                os.write(fd, f"human-hold {hold_req}\n".encode())
                sent_at = time.time()
            finally:
                os.close(fd)
            records.append((fifo, resolved, "human-hold sent", sent_at, pre_t, hold_req))
        except OSError as exc:
            records.append((fifo, resolved, f"error: {type(exc).__name__}", None, None, None))
    counts: dict[str, int] = {}
    for fifo, _res, _ack, _sent, _pre, _req in records:
        counts[fifo.parent.name] = counts.get(fifo.parent.name, 0) + 1
    used_keys: set[str] = set()
    dispatched: list[tuple[Path, str, float, float | None, str]] = []
    for fifo, resolved, ack, sent_at, pre_t, hold_req in records:
        key = fifo.parent.name if counts[fifo.parent.name] == 1 else str(fifo.parent)
        if key in used_keys:
            key = str(resolved.parent)
        used_keys.add(key)
        acks[key] = ack
        if sent_at is not None and hold_req is not None:
            dispatched.append((fifo, key, sent_at, pre_t, hold_req))
        else:
            latched[key] = False
    deadline = time.monotonic() + max(0.0, confirm_wait_s)
    confirmed: set[Path] = set()
    while len(confirmed) < len(dispatched):
        for fifo, _key, sent_at, pre_t, hold_req in dispatched:
            if fifo in confirmed:
                continue
            try:
                live_data = json.loads((fifo.parent / "live.json").read_text(encoding="utf-8"))
                t_val = finite_stamp(live_data.get("t")) if isinstance(live_data, dict) else None
                if (isinstance(live_data, dict) and live_data.get("human_hold_latched") is True
                        and live_data.get("torque_hold_commanded") is True
                        and live_data.get("hold_req") == hold_req
                        and t_val is not None
                        and sent_at + 0.001 <= t_val <= time.time() + 1.0
                        and (pre_t is None or t_val > pre_t)):
                    confirmed.add(fifo)
            except (OSError, ValueError, RecursionError):
                pass
        if len(confirmed) >= len(dispatched) or time.monotonic() >= deadline:
            break
        time.sleep(min(poll_s, max(0.0, deadline - time.monotonic())))
    for fifo, key, _sent_at, _pre, _req in dispatched:
        latched[key] = fifo in confirmed
    return acks, latched


def execute_act_policy_task(
    handoff: dict[str, Any],
    *,
    arm_id: str,
    prep_dir: Path,
    wrapper: Path,
    cfg: Path,
    cat: Path,
    default_roi: tuple[int, int, int, int],
    lease_owner: str,
    tools_root_fn,
    run_fn,
    last_json_fn,
    measured_fold_fn,
    source_clearance_fn,
    fold_readback_fn,
    plan_home_fn,
    write_context_fn,
    timeout_exc,
) -> dict[str, Any]:
    """Execute one supervised Cell S ACT policy task via `cell_policy_drive.py --paced-chunks`."""
    task_id = handoff.get("task_id")
    cell_id = str(handoff.get("cell_id") or "cell_s").strip()
    if cell_id != "cell_s" or arm_id != "arm_s":
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
    omx_dir = Path(__file__).resolve().parent
    cat_path = cat if cat.is_file() else omx_dir / "object-catalog.example.json"
    rev = policy_cfg["policy_revision"].strip()
    cmd = [
        str(wrapper),
        sys.executable,
        str(omx_dir / "cell_policy_drive.py"),
        "--config", str(cfg),
        "--library", str(library),
        "--policy-root", str(Path(policy_cfg["policy_root"].strip()).expanduser()),
        "--policy-revision", rev,
        "--cell-calibration", str(Path(policy_cfg["cell_calibration"].strip()).expanduser()),
        "--model-calibration", str(Path(policy_cfg["model_calibration"].strip()).expanduser()),
        "--max-chunks", str(raw_chunks),
        "--max-obs-age-s", str(max_obs_age_s),
        "--operator", operator,
        "--person-at-switch",
        "--paced-chunks",
        "--catalog", str(cat_path),
        "--roi", *(str(int(v)) for v in roi),
        "--site", src_site,
        "--dest-site", dst,
        "--task-id", tid,
    ]
    try:
        proc = run_fn(cmd, capture_output=True, text=True, timeout=300,
                      env={**os.environ, "TOOLS_ROOT": str(tools_root_fn()), "ROSY_ARM_LEASE_OWNER": lease_owner})
    except timeout_exc:
        acks, latched = _hold_on_timeout(prep_dir, cfg_data, io_base=cfg.parent)
        extra = {"timeout_hold": acks, "timeout_hold_latched": latched} if acks else None
        return _fail(arm_id, "SUBPROCESS_TIMEOUT", directive_id=task_id, extra_stop=extra)
    parsed = last_json_fn(proc.stdout)
    measured_at = time.time()
    raw_park = parsed.get("park") if isinstance(parsed.get("park"), dict) else {}
    park_valid = park_ack_ok(raw_park, require_command=True)
    park_row = {**raw_park, "command": "park"} if park_valid else dict(raw_park)
    fold = fold_readback_fn({"transfer": {"steps": [park_row]}}, plan_home_fn(cfg_data))
    live_fold = measured_fold_fn(arm_id, prep_dir)
    folded = bool(parsed.get("parked") is True and park_valid and fold["folded"] and live_fold["folded"])
    source = parsed.get("source") if isinstance(parsed.get("source"), dict) else {}
    took_one = bool(parsed.get("took_one") is True and source.get("after") == 0)
    zone = parsed.get("zone_verification") if isinstance(parsed.get("zone_verification"), dict) else None
    zone_ok = zone_acceptance(zone, handoff, dst)
    clearance = source_clearance_fn(cfg, cat_path, roi, src_site) if folded else None
    clearance_ok = isinstance(clearance, dict) and clearance.get("objects") == 0
    verified = bool(proc.returncode == 0 and parsed.get("result") in ("released", "chunks_done")
                    and folded and took_one and clearance_ok and zone_ok)
    if verified:
        write_context_fn(cfg, cfg_data, handoff, arm_id, prep_dir, dst, src_site, roi, zone, cat_path=cat_path)
    tier = handoff.get("tier")
    placement = {"verified": verified, "inside": verified, "basis": "act_policy"}
    src_meta = {"source": {**source, "roi": [int(v) for v in roi]}} if source else {}
    if zone is not None:
        verification = {**zone, "verified": bool(zone.get("verified") is True and verified),
                        "placement": placement, "policy_revision": rev, **src_meta}
    else:
        verification = {"verified": False, "basis": f"unverified: act policy {parsed.get('result') or 'failed'}",
                        "placement": placement, "policy_revision": rev, **src_meta}
    stage_result = {
        "handoff_lease_id": handoff.get("handoff_lease_id"),
        "directive_id": task_id,
        "arm_id": arm_id,
        "task_verified": verified,
        "place": {"area": dst_site, **({"tier": tier} if isinstance(tier, int) else {})},
        "verification": verification,
        "raw": parsed,
        **({"source_clearance": clearance} if clearance is not None else {}),
    }
    state_val = fold.get("state") or live_fold.get("state")
    return {
        "arm": arm_id,
        "events_count": 1 if parsed else 0,
        "measured_at": measured_at,
        "stage_result": stage_result,
        "stop_event": {"command": "stop", "ok": folded, "folded": folded, "readback": fold, "live": live_fold,
                       **({"state": state_val} if state_val else {})},
        "commissioning": True,
        **({} if verified else {"error": parsed.get("result") or f"act_exit_{proc.returncode}"}),
    }
