#!/usr/bin/env python3
"""Stdlib-only failure context emitter, atomic store, redactor, and fence checks (D-1072)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

SCHEMA = "rosy.omx-failure-context.v1"
MAX_BYTES = 49_152
MAX_DEPTH = 6
DEFAULT_TTL_S = 30.0
MAX_FAILURE_BUNDLES = 200
MAX_CONTROL_BUNDLES = 50
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_CHAIN_DEPTH = 2
HOME_POSE_TOL_UNITS = 8.0

FALLBACK_VERBS = (
    "reinsert",
    "release_and_rise",
    "align_push",
    "retry_ik_slower",
    "retry_ik_alt_axis",
    "redirect_alt_dest",
    "home_unwedge",
    "propose_ik_fallback_for_policy",
    "escalate_human",
)
MEASURED_VETO_CODES = (
    "OUT_OF_HOME_POSE",
    "TOP_CAMERA_SHIFTED",
    "MISSING_SITE_MAP",
    "ARM_INCIDENT_HELD",
    "LATCHED_HW_ERROR",
    "WINDUP_HIT",
    "CAPS_UNRESTORED",
    "EXTENDED_TORQUE_DROP_FORBIDDEN",
    "HOLDING_HIGH_NO_RELEASE",
    "REPEAT_UNKNOWN_ESCALATION",
    "AMR_BED_REQUIRES_FLEET_R",
    "MISSING_REQUIRED_CAMERA",
    "PENDING_INTENT_PRESENT",
    "PEER_ARM_LOCKED_OR_HELD",
    "FLEET_SAFETY_STOP_OR_ABORTED",
    "NO_MEASURED_OBJECTS",
)

_BUNDLE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_SECRET_KEY_RE = re.compile(r"(?:token|secret|authorization|api_key|password|cookie|private_key)", re.I)
_PRIVATE_IP_RE = re.compile(
    r"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})(?![\d.])"
)
_HOME_UNIX_RE = re.compile(r"/home/[A-Za-z0-9_.-]+")
_HOME_WIN_RE = re.compile(r"[A-Za-z]:\\Users\\[^\\/:*?\"<>|\s]+")
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9_.-]+")
_MIME_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".mp4": "video/mp4", ".jsonl": "application/x-ndjson"}
_LONG_B64_RE = re.compile(r"^[A-Za-z0-9+/=\r\n]{2048,}$")
_HARD_BLOCKERS = {
    "LATCHED_HW_ERROR", "WINDUP_HIT", "CAPS_UNRESTORED", "FLEET_SAFETY_STOP_OR_ABORTED",
    "REPEAT_UNKNOWN_ESCALATION", "PENDING_INTENT_PRESENT", "PEER_ARM_LOCKED_OR_HELD",
}


def default_bundle_root(state_dir: Path | None = None) -> Path:
    base = Path(state_dir) if state_dir is not None else Path(os.environ.get("ROSY_OMX_STATE_DIR") or (Path.home() / "rosy-omx"))
    return base / "failure-bundles"


def canonical_sha256(payload: dict[str, Any], *, omit_keys: tuple[str, ...] = ("context_sha256", "freshness")) -> str:
    filtered = {k: v for k, v in payload.items() if k not in omit_keys} if omit_keys else payload
    raw = json.dumps(filtered, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def redact_context(value: Any) -> Any:
    """Strip private/Tailscale IPs, user home prefixes, bearer strings, and secret keys."""
    if isinstance(value, str):
        s = _PRIVATE_IP_RE.sub("[REDACTED_IP]", value)
        s = _HOME_UNIX_RE.sub("/home/[USER]", s)
        s = _HOME_WIN_RE.sub("[USER_HOME]", s)
        return _BEARER_RE.sub("Bearer [REDACTED]", s)
    if isinstance(value, list):
        return [redact_context(item) for item in value]
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _SECRET_KEY_RE.search(str(k)) else redact_context(v)) for k, v in value.items()}
    return value


def _check_depth_and_no_b64(value: Any, level: int = 0) -> None:
    if level > MAX_DEPTH:
        raise ValueError(f"JSON nested deeper than {MAX_DEPTH}")
    if isinstance(value, str):
        if "data:image/" in value.lower() or _LONG_B64_RE.fullmatch(value):
            raise ValueError("inline base64 image payloads are forbidden")
    elif isinstance(value, dict):
        for v in value.values():
            _check_depth_and_no_b64(v, level + 1)
    elif isinstance(value, list):
        for v in value:
            _check_depth_and_no_b64(v, level + 1)


def _veto(code: str, severity: str, detail: str, path: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "detail": detail[:300], "evidence_path": path[:120]}


def compute_measured_vetoes(
    measurement: dict[str, Any],
    spatial: dict[str, Any],
    visual: dict[str, Any],
    *,
    pending_intent_present: bool = False,
    repeat_unknown_tripped: bool = False,
) -> list[dict[str, str]]:
    """Evaluate all 16 deterministic vetoes from measured bundle sections."""
    vetoes: list[dict[str, str]] = []
    kin = measurement.get("kinematics_and_health") or {}
    if isinstance(kin.get("max_home_err_units"), (int, float)) and kin["max_home_err_units"] > HOME_POSE_TOL_UNITS:
        vetoes.append(_veto("OUT_OF_HOME_POSE", "hard", f"max_home_err_units={kin['max_home_err_units']}", "measurement.kinematics_and_health.max_home_err_units"))
    cal = spatial.get("calibration") or {}
    shift = cal.get("top_shift_px") or {}
    if shift.get("moved") is True or (isinstance(shift.get("max_px"), (int, float)) and isinstance(shift.get("limit_px"), (int, float)) and shift["max_px"] > shift["limit_px"]):
        vetoes.append(_veto("TOP_CAMERA_SHIFTED", "hard", f"top shift max_px={shift.get('max_px')} limit={shift.get('limit_px')}", "spatial.calibration.top_shift_px"))
    if cal.get("missing_map"):
        vetoes.append(_veto("MISSING_SITE_MAP", "hard", f"missing_map={cal['missing_map']}", "spatial.calibration.missing_map"))
    inc = measurement.get("incident") or {}
    if inc.get("local_held") is True or inc.get("fleet_held") is True:
        vetoes.append(_veto("ARM_INCIDENT_HELD", "hard", f"held local={inc.get('local_held')} fleet={inc.get('fleet_held')}", "measurement.incident"))
    if inc.get("latched_motors"):
        vetoes.append(_veto("LATCHED_HW_ERROR", "hard", f"latched_motors={sorted(inc['latched_motors'])}", "measurement.incident.latched_motors"))
    if (inc.get("windup_hits_count") or 0) > 0:
        vetoes.append(_veto("WINDUP_HIT", "hard", f"windup_hits_count={inc['windup_hits_count']}", "measurement.incident.windup_hits_count"))
    if inc.get("caps_restored") is False:
        vetoes.append(_veto("CAPS_UNRESTORED", "hard", "servo caps not restored", "measurement.incident.caps_restored"))
    hf = measurement.get("holding_and_fold") or {}
    live_fold = hf.get("live_fold") or {}
    if live_fold.get("folded") is False and live_fold.get("at_rest_tol_8") is False:
        vetoes.append(_veto("EXTENDED_TORQUE_DROP_FORBIDDEN", "hard", "arm extended; keep torque ON (D-1048)", "measurement.holding_and_fold.live_fold"))
    still = hf.get("still_holding") or {}
    if still.get("measured") is True and still.get("tcp_low_for_release") is False:
        vetoes.append(_veto("HOLDING_HIGH_NO_RELEASE", "hard", "holding object high; release forbidden", "measurement.holding_and_fold.still_holding"))
    if repeat_unknown_tripped or measurement.get("repeat_unknown_tripped") is True:
        vetoes.append(_veto("REPEAT_UNKNOWN_ESCALATION", "hard", "unknown cause repeated twice", "history_and_constraints.repeat_unknown_tripped"))
    sites = spatial.get("sites") or {}
    if sites.get("is_amr_bed") is True:
        vetoes.append(_veto("AMR_BED_REQUIRES_FLEET_R", "hard", "AMR bed site requires Fleet-R claim path", "spatial.sites.is_amr_bed"))
    for cam, entry in sorted((visual.get("camera_manifest") or {}).items()):
        if isinstance(entry, dict) and entry.get("required_for_mode") is True and entry.get("status") != "ok":
            vetoes.append(_veto("MISSING_REQUIRED_CAMERA", "hard", f"{cam} status={entry.get('status')}", f"visual.camera_manifest.{cam}"))
            break
    outcome = measurement.get("outcome") or {}
    if pending_intent_present or measurement.get("pending_intent_present") is True or outcome.get("pending_intent_present") is True:
        vetoes.append(_veto("PENDING_INTENT_PRESENT", "hard", "D-911 pending intent unresolved", "measurement.outcome"))
    occ = spatial.get("workspace_occupancy") or {}
    arms_occ = occ.get("arms") or {}
    peer_blocked = occ.get("peer_ab_session_locked") is True or occ.get("whole_cell_lock_held") is True or any(
        isinstance(a, dict) and (a.get("held") is True or (a.get("session_lock_held") is True and a.get("folded") is False))
        for a in arms_occ.values()
    )
    if peer_blocked:
        vetoes.append(_veto("PEER_ARM_LOCKED_OR_HELD", "hard", "peer arm or whole-cell lock active", "spatial.workspace_occupancy"))
    fs = occ.get("fleet_safety") or {}
    if fs.get("active_estop") is True or fs.get("human_detected") is True or fs.get("cell_aborted") is True:
        vetoes.append(_veto("FLEET_SAFETY_STOP_OR_ABORTED", "hard", "Fleet safety stop or cell ABORTED", "spatial.workspace_occupancy.fleet_safety"))
    perc = spatial.get("perception") or {}
    objs = perc.get("detected_objects")
    if isinstance(objs, list) and len(objs) == 0 and outcome.get("attempt_cause") in ("empty", "no_room", "no_progress"):
        vetoes.append(_veto("NO_MEASURED_OBJECTS", "soft", "zero catalog objects detected in ROI", "spatial.perception.detected_objects"))
    return vetoes


def _menu_item(verb: str, tier: int, stratum: str, surface: str, req_op: bool, req_sw: bool, active_codes: list[str], blockers: set[str]) -> dict[str, Any]:
    blocked_by = [c for c in active_codes if c in blockers]
    return {
        "verb": verb,
        "tier": tier,
        "stratum": stratum,
        "target_surface": surface,
        "requires_human_operator": req_op,
        "requires_person_at_switch": req_sw,
        "preconditions_met": len(blocked_by) == 0,
        "blocked_by": blocked_by,
    }


def build_allowed_fallback_menu(
    executor_mode: str,
    attempt_cause: str,
    vetoes: list[dict[str, Any]],
    *,
    fallback_chain_depth: int = 0,
    max_chain_depth: int = MAX_CHAIN_DEPTH,
    has_declared_alternates: bool = False,
    dest_full_pre_motion: bool = False,
    auto_fold_armed: bool = False,
) -> list[dict[str, Any]]:
    """Build closed fallback options; never emits Tier-2 policy->IK auto-swaps."""
    codes = [v["code"] for v in vetoes]
    if fallback_chain_depth >= max_chain_depth:
        codes.append("CHAIN_DEPTH_EXCEEDED")
    hard = _HARD_BLOCKERS | {"CHAIN_DEPTH_EXCEEDED"}
    motion_block = hard | {"OUT_OF_HOME_POSE", "TOP_CAMERA_SHIFTED", "MISSING_SITE_MAP", "ARM_INCIDENT_HELD", "MISSING_REQUIRED_CAMERA", "EXTENDED_TORQUE_DROP_FORBIDDEN", "HOLDING_HIGH_NO_RELEASE"}
    menu = [_menu_item("escalate_human", 0, "human_only", "human_request", False, False, codes, set())]

    if executor_mode in ("act_paced", "act_timed", "hybrid"):
        menu.append(_menu_item("propose_ik_fallback_for_policy", 1, "tier1_propose", "fleet_pipeline", True, False, codes, motion_block | {"AMR_BED_REQUIRES_FLEET_R"}))
    if dest_full_pre_motion and has_declared_alternates:
        menu.append(_menu_item("redirect_alt_dest", 2, "tier2_auto", "fleet_pipeline", False, False, codes, motion_block - {"EXTENDED_TORQUE_DROP_FORBIDDEN", "HOLDING_HIGH_NO_RELEASE"}))
    if auto_fold_armed:
        menu.append(_menu_item("home_unwedge", 2, "tier2_auto", "cell_job_api", False, False, codes, hard | {"HOLDING_HIGH_NO_RELEASE"}))
    else:
        menu.append(_menu_item("home_unwedge", 3, "human_only", "cell_job_api", True, True, codes, {"LATCHED_HW_ERROR", "WINDUP_HIT", "FLEET_SAFETY_STOP_OR_ABORTED", "PEER_ARM_LOCKED_OR_HELD", "PENDING_INTENT_PRESENT"}))

    if executor_mode in ("ik_auto_pick", "recovery"):
        if attempt_cause in ("lift_stall", "no_progress"):
            menu.append(_menu_item("retry_ik_slower", 1, "tier1_propose", "cell_job_api", True, True, codes, motion_block | {"NO_MEASURED_OBJECTS"}))
        if attempt_cause in ("no_room", "pile", "s3_packed_no_clearance", "s6_unseated_cone", "lift_stall", "misaligned", "unstable_grasp", "no_progress"):
            menu.append(_menu_item("align_push", 1, "tier1_propose", "cell_job_api", True, True, codes, motion_block))
        if attempt_cause in ("empty", "unstable_grasp", "misaligned", "no_progress"):
            menu.append(_menu_item("retry_ik_alt_axis", 1, "tier1_propose", "cell_job_api", True, True, codes, motion_block | {"NO_MEASURED_OBJECTS"}))
    return menu


def build_bundle(
    *,
    kind: str,
    arm_id: str,
    cell_id: str,
    executor_mode: str,
    correlation: dict[str, Any],
    generation: dict[str, Any],
    measurement: dict[str, Any],
    spatial: dict[str, Any],
    visual: dict[str, Any],
    history: dict[str, Any] | None = None,
    bundle_id: str | None = None,
    ttl_s: float = DEFAULT_TTL_S,
    created_at_s: float | None = None,
    monotonic_s: float | None = None,
    fallback_chain_depth: int = 0,
    has_declared_alternates: bool = False,
    dest_full_pre_motion: bool = False,
    auto_fold_armed: bool = False,
    pending_intent_present: bool = False,
) -> dict[str, Any]:
    """Assemble, redact, compute vetoes/menu, size-check, and digest-sign a bundle."""
    now = time.time() if created_at_s is None else float(created_at_s)
    mono = time.monotonic() if monotonic_s is None else float(monotonic_s)
    bid = bundle_id or f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(now))}-{arm_id}-{kind}"
    if not _BUNDLE_ID_RE.fullmatch(bid):
        raise ValueError(f"invalid bundle_id {bid!r}")
    meas_r, spat_r = redact_context(measurement), redact_context(spatial)
    vis_in = redact_context(visual)
    vis_norm = {
        "camera_manifest": vis_in.get("camera_manifest") or {},
        "frames": list(vis_in.get("frames") or []),
        "gaps": list(vis_in.get("gaps") or []),
        "control_ref": vis_in.get("control_ref"),
        "depth_summary": vis_in.get("depth_summary"),
    }
    hist_in = redact_context(history or {})
    repeat_tripped = bool(hist_in.get("repeat_unknown_tripped"))
    vetoes = compute_measured_vetoes(meas_r, spat_r, vis_norm, pending_intent_present=pending_intent_present, repeat_unknown_tripped=repeat_tripped)
    cause = str((meas_r.get("outcome") or {}).get("attempt_cause") or "unknown")
    menu = build_allowed_fallback_menu(
        executor_mode, cause, vetoes, fallback_chain_depth=fallback_chain_depth,
        has_declared_alternates=has_declared_alternates, dest_full_pre_motion=dest_full_pre_motion, auto_fold_armed=auto_fold_armed,
    )
    bundle = {
        "schema": SCHEMA,
        "bundle_id": bid,
        "kind": kind,
        "created_at_s": now,
        "monotonic_s": mono,
        "ttl_s": float(ttl_s),
        "arm_id": arm_id,
        "cell_id": cell_id,
        "executor_mode": executor_mode,
        "correlation": redact_context(correlation),
        "generation": dict(generation),
        "measurement": meas_r,
        "spatial": spat_r,
        "visual": vis_norm,
        "history_and_constraints": {
            "recent_attempts": list(hist_in.get("recent_attempts") or []),
            "recent_decisions": list(hist_in.get("recent_decisions") or []),
            "decisions_digest": str(hist_in.get("decisions_digest") or "")[:600],
            "recent_why": list(hist_in.get("recent_why") or []),
            "repeat_unknown_count": int(hist_in.get("repeat_unknown_count") or 0),
            "repeat_unknown_tripped": repeat_tripped,
            "knowledge_sha": hist_in.get("knowledge_sha"),
            "knowledge": list(hist_in.get("knowledge") or []),
            "choices_record": dict(hist_in.get("choices_record") or {}),
            "compensation": dict(hist_in.get("compensation") or {}),
            "measured_vetoes": vetoes,
            "allowed_fallback_menu": menu,
        },
        "freshness": None,
    }
    _check_depth_and_no_b64(bundle)
    encoded = json.dumps(bundle, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise ValueError(f"bundle exceeds {MAX_BYTES} bytes ({len(encoded)})")
    bundle["context_sha256"] = canonical_sha256(bundle)
    return bundle


def _dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


def _prune(root: Path, *, pinned: set[str], max_failure: int, max_control: int, max_bytes: int) -> None:
    rows: list[tuple[float, str, str, int]] = []
    for sub in root.iterdir():
        if not sub.is_dir() or sub.name.startswith(".") or sub.is_symlink():
            continue
        bf = sub / "bundle.json"
        if not bf.is_file():
            continue
        try:
            meta = json.loads(bf.read_text(encoding="utf-8"))
            rows.append((float(meta.get("created_at_s", 0.0)), sub.name, str(meta.get("kind", "stop")), _dir_size(sub)))
        except (OSError, ValueError):
            continue
    rows.sort()
    fail_rows = [r for r in rows if r[2] != "control"]
    ctrl_rows = [r for r in rows if r[2] == "control"]
    drop: set[str] = set()
    for r in fail_rows[: max(0, len(fail_rows) - max_failure)]:
        if r[1] not in pinned:
            drop.add(r[1])
    for r in ctrl_rows[: max(0, len(ctrl_rows) - max_control)]:
        if r[1] not in pinned:
            drop.add(r[1])
    total = sum(r[3] for r in rows if r[1] not in drop)
    for r in rows:
        if total <= max_bytes:
            break
        if r[1] not in drop and r[1] not in pinned:
            drop.add(r[1])
            total -= r[3]
    for bid in drop:
        shutil.rmtree(root / bid, ignore_errors=True)


def write_bundle(
    root: Path,
    bundle: dict[str, Any],
    assets: dict[str, bytes] | None = None,
    *,
    pinned_bundle_ids: set[str] | tuple[str, ...] = (),
    max_failure_bundles: int = MAX_FAILURE_BUNDLES,
    max_control_bundles: int = MAX_CONTROL_BUNDLES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> Path:
    """Atomically write bundle.json + SHA-verified assets, append index.jsonl, and enforce retention."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    bid = str(bundle["bundle_id"])
    if not _BUNDLE_ID_RE.fullmatch(bid):
        raise ValueError(f"invalid bundle_id {bid!r}")
    tmp = root / f".tmp-{bid}-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    to_write = json.loads(json.dumps(bundle, allow_nan=False))
    try:
        asset_meta: dict[str, tuple[int, str]] = {}
        for name, data in (assets or {}).items():
            if not _SAFE_FILE_RE.fullmatch(name) or Path(name).suffix.lower() not in _MIME_TYPES:
                raise ValueError(f"unsupported asset filename {name!r}")
            (tmp / name).write_bytes(data)
            asset_meta[name] = (len(data), hashlib.sha256(data).hexdigest())
        for frame in to_write["visual"]["frames"]:
            if frame.get("file") in asset_meta:
                frame["bytes"], frame["sha256"] = asset_meta[frame["file"]]
        trace_ref = to_write["measurement"].get("trace_ref")
        if isinstance(trace_ref, dict) and trace_ref.get("file") in asset_meta:
            trace_ref["bytes"], trace_ref["sha256"] = asset_meta[trace_ref["file"]]
        _check_depth_and_no_b64(to_write)
        to_write["context_sha256"] = canonical_sha256(to_write)
        encoded = json.dumps(to_write, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_BYTES:
            raise ValueError(f"bundle exceeds {MAX_BYTES} bytes")
        (tmp / "bundle.json").write_bytes(encoded)
        dest = root / bid
        if dest.exists():
            shutil.rmtree(dest)
        os.replace(tmp, dest)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    row = {
        "bundle_id": bid,
        "created_at_s": to_write["created_at_s"],
        "arm_id": to_write["arm_id"],
        "kind": to_write["kind"],
        "executor_mode": to_write["executor_mode"],
        "attempt_cause": (to_write["measurement"].get("outcome") or {}).get("attempt_cause"),
        "context_sha256": to_write["context_sha256"],
        "cell_state_gen": (to_write["generation"] or {}).get("cell_state_gen"),
    }
    with (root / "index.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
    _prune(root, pinned=set(pinned_bundle_ids), max_failure=max_failure_bundles, max_control=max_control_bundles, max_bytes=max_total_bytes)
    return root / bid


def _bundle_dir(root: Path, bundle_id: str) -> Path:
    if not _BUNDLE_ID_RE.fullmatch(bundle_id):
        raise ValueError("invalid bundle_id")
    base = Path(root).resolve()
    target = Path(root) / bundle_id
    if target.is_symlink() or not target.is_dir() or not target.resolve().is_relative_to(base):
        raise FileNotFoundError(bundle_id)
    return target


def list_bundles(root: Path, *, arm: str | None = None, kind: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    idx = Path(root) / "index.jsonl"
    if not idx.is_file():
        return []
    cap = max(1, min(int(limit), 100))
    items: list[dict[str, Any]] = []
    for line in reversed(idx.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if arm and row.get("arm_id") != arm:
            continue
        if kind and row.get("kind") != kind:
            continue
        if (Path(root) / str(row.get("bundle_id", "")) / "bundle.json").is_file():
            items.append(row)
        if len(items) >= cap:
            break
    return items


def load_bundle(
    root: Path,
    bundle_id: str,
    *,
    current_cell_state_gen: int | None = None,
    now_s: float | None = None,
    active_holds: tuple[str, ...] = (),
) -> dict[str, Any]:
    bdir = _bundle_dir(root, bundle_id)
    bfile = bdir / "bundle.json"
    if bfile.is_symlink() or not bfile.is_file():
        raise FileNotFoundError(bundle_id)
    data = json.loads(bfile.read_text(encoding="utf-8"))
    if data.get("context_sha256") != canonical_sha256(data):
        raise ValueError("bundle context_sha256 integrity mismatch")
    now = time.time() if now_s is None else float(now_s)
    age_s = max(0.0, now - float(data["created_at_s"]))
    bgen = int((data.get("generation") or {}).get("cell_state_gen", 0))
    cgen = bgen if current_cell_state_gen is None else int(current_cell_state_gen)
    reasons: list[str] = []
    if cgen != bgen:
        reasons.append(f"cell_state_gen advanced {bgen}->{cgen}")
    if age_s > float(data.get("ttl_s", DEFAULT_TTL_S)):
        reasons.append(f"bundle expired ({age_s:.1f}s > {data.get('ttl_s', DEFAULT_TTL_S)}s)")
    if data.get("arm_id") in active_holds:
        reasons.append(f"active hold on {data.get('arm_id')}")
    data["freshness"] = {
        "age_s": round(age_s, 3),
        "current_cell_state_gen": cgen,
        "gen_matches": cgen == bgen,
        "still_valid_for_action": len(reasons) == 0,
        "invalidated_reasons": reasons,
    }
    return data


def resolve_asset(root: Path, bundle_id: str, filename: str) -> tuple[Path, str, str]:
    """Return verified (path, mime_type, sha256) for a bundle sidecar asset; fail on traversal/symlink/tamper."""
    if not _SAFE_FILE_RE.fullmatch(filename):
        raise ValueError("invalid asset filename")
    mime = _MIME_TYPES.get(Path(filename).suffix.lower())
    if mime is None:
        raise ValueError("unsupported asset extension")
    bdir = _bundle_dir(root, bundle_id)
    bundle = load_bundle(root, bundle_id)
    declared = {f["file"]: f["sha256"] for f in bundle["visual"]["frames"] if isinstance(f, dict) and "file" in f}
    trace_ref = bundle["measurement"].get("trace_ref")
    if isinstance(trace_ref, dict) and "file" in trace_ref and "sha256" in trace_ref:
        declared[trace_ref["file"]] = trace_ref["sha256"]
    expected_sha = declared.get(filename)
    if expected_sha is None:
        raise FileNotFoundError(filename)
    asset = bdir / filename
    if asset.is_symlink() or not asset.is_file() or not asset.resolve().is_relative_to(bdir.resolve()):
        raise ValueError("unsafe asset path")
    actual_sha = hashlib.sha256(asset.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError("asset sha256 mismatch")
    return asset, mime, actual_sha


def check_fence(
    bundle: dict[str, Any],
    *,
    expected_context_sha256: str,
    expected_cell_state_gen: int,
    current_cell_state_gen: int,
    now_s: float | None = None,
    active_holds: tuple[str, ...] = (),
    max_age_s: float | None = None,
) -> tuple[bool, str | None, list[str]]:
    """Enforce TOCTOU freshness & digest checks; return (True, None, []) or (False, 'STALE_FAILURE_CONTEXT', reasons)."""
    reasons: list[str] = []
    if bundle.get("context_sha256") != expected_context_sha256:
        reasons.append("context_sha256 mismatch")
    bgen = int((bundle.get("generation") or {}).get("cell_state_gen", 0))
    if bgen != int(expected_cell_state_gen) or int(current_cell_state_gen) != bgen:
        reasons.append(f"cell_state_gen drift (bundle={bgen}, expected={expected_cell_state_gen}, current={current_cell_state_gen})")
    now = time.time() if now_s is None else float(now_s)
    age_s = max(0.0, now - float(bundle["created_at_s"]))
    limit = float(bundle.get("ttl_s", DEFAULT_TTL_S)) if max_age_s is None else min(float(max_age_s), float(bundle.get("ttl_s", DEFAULT_TTL_S)))
    if age_s > limit:
        reasons.append(f"stale age {age_s:.1f}s > {limit:.1f}s")
    if bundle.get("arm_id") in active_holds:
        reasons.append(f"active hold on {bundle.get('arm_id')}")
    return (True, None, []) if not reasons else (False, "STALE_FAILURE_CONTEXT", reasons)
