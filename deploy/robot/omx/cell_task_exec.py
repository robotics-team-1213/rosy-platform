"""Execution, TLS, hold-gating, and error diagnostics helpers for `cell_task_worker.py`."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import ssl
import subprocess
import sys
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from cell_act_verdict import FOLD_FRESH_S, FOLD_TOLERANCE, fold_readback, measured_fold, plan_home  # noqa: F401 (moved: the job API needs them without omx_adapter)
from cell_presence import autonomous_policy_enabled, presence_ok, review_required, zone_acceptance
from cell_remeasure import write_context
import cell_site_target
from cell_route_check import pick_site
from cell_task_act import plan_act_policy_task
from cell_task_act_run import execute_act_policy_task
from cell_task_motion import free_pick_request, run_job
from cell_task_transport import WORKER_LEASE_PREFIX, make_keepalive_https_request, peer_ab_session_locked  # noqa: F401

_DEFAULT_URLOPEN = urlopen


def make_ca_urlopen(ca_file: str | Path | None = None):
    """Return a `urlopen`-compatible callable pinned to `ca_file` when provided."""
    if not ca_file:
        return urlopen
    ctx = ssl.create_default_context(cafile=str(Path(ca_file).expanduser()))

    def _open(req, **kwargs):
        kwargs.pop("context", None)
        return urlopen(req, context=ctx, **kwargs)

    _open.raw_urlopen = lambda req, **kw: urlopen(req, **kw)
    return _open


def make_default_request_fn(
    fleet_r_url: str, token: str, *, ca_file: str | None = None,
) -> Callable[[str, str, dict[str, Any] | None], dict[str, Any]]:
    base = fleet_r_url.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Fleet URL requires verified HTTPS")
    ctx = ssl.create_default_context(cafile=ca_file)
    worker = sys.modules.get("cell_task_worker")
    w_open = getattr(worker, "urlopen", _DEFAULT_URLOPEN) if worker is not None else _DEFAULT_URLOPEN
    opener = w_open if w_open is not _DEFAULT_URLOPEN else urlopen
    if opener is _DEFAULT_URLOPEN:
        return make_keepalive_https_request(base, token, ctx, timeout_s=20.0)

    def _req(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = Request(f"{base}{path}", data=data, method=method,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with opener(req, context=ctx, timeout=20) as resp:
            return json.load(resp)

    return _req


def query_safety_listing(request_fn, timeout_s: float) -> tuple[Any, Exception | None]:
    """Bound the caller's wait even when the HTTP request completes later."""
    answer: dict[str, Any] = {}
    finished = threading.Event()

    def query() -> None:
        try:
            answer["value"] = request_fn("GET", "/api/fleet/pipeline/cell-tasks?status=QUEUED", None)
        except Exception as exc:
            answer["error"] = exc
        finally:
            finished.set()

    threading.Thread(target=query, daemon=True).start()
    if not finished.wait(timeout_s):
        return None, TimeoutError("Fleet safety listing timed out")
    return answer.get("value"), answer.get("error")


def resolve_task_arm(task: dict[str, Any]) -> str:
    """Resolve the target OMX arm id for a queued Fleet cell task."""
    arm = str(task.get("arm_id") or "").strip()
    if arm:
        return arm
    if task.get("cell_id") == "cell_s":
        return "arm_s"
    return cell_site_target.default_arm_for_cell_ab(task.get("src_site"), task.get("dst_site"), task.get("tier"))


def check_arm_hold(arm_id: str) -> dict[str, Any]:
    """Check local and synced Fleet incident holds for `arm_id`; fails closed to local hold."""
    import omx_incident

    try:
        st = omx_incident.status(arm_id)
        held = bool(st.get("local_held") or st.get("fleet_held") or st.get("held"))
        return {"held": held, "reason": st.get("local_reason") or st.get("fleet_reason")}
    except Exception:
        lf = omx_incident.hold_file(arm_id)
        return {"held": lf is not None, "reason": "local_hold_present" if lf is not None else None}


def classify_poll_error(exc: Exception, token_file: str | Path) -> dict[str, Any]:
    """Return structured poll error payload without leaking token bytes."""
    if isinstance(exc, HTTPError) and exc.code == 401:
        p = Path(token_file).expanduser()
        length = len(p.read_text(encoding="utf-8").strip()) if p.is_file() else 0
        return {
            "event": "poll_auth_error",
            "status": 401,
            "token_file": str(p),
            "token_chars": length,
            "hint": "Fleet rejected bearer token (post-rosy_account cutover expects valid 64-hex service/operator credential)",
            "backoff_s": 30.0,
        }
    return {"event": "poll_error", "error": repr(exc), "backoff_s": None}


# D-1057. Same tolerance as chunk_runner_guards.SETTLE_TOL, which the transfer gate uses to accept a park as home.
ZONE_BASIS = "predefined_side_and_top_target_zones"
TOP_ONLY_BASIS = "top_camera_only_target_zone"  # cell S only (D-1057, user decision 2026-11-20): it has no side camera


def last_json_object(text: str) -> dict[str, Any]:
    """The JSON object that ends the output. cell_auto_pick prints it indented over many lines after free-form log lines,
    so take the earliest `{` from which one object parses through to the end of the text."""
    decoder, start = json.JSONDecoder(), text.find("{")
    while start != -1:
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            value = None
        else:
            if isinstance(value, dict) and not text[end:].strip():
                return value
        start = text.find("{", start + 1)
    return {}


def _last_attempt(parsed: dict[str, Any]) -> dict[str, Any]:
    attempts = parsed.get("attempts")
    last = attempts[-1] if isinstance(attempts, list) and attempts else None
    return last if isinstance(last, dict) else {}


def tools_root() -> Path:
    """The release the worker runs from (its unit sets TOOLS_ROOT): the arm session wrappers and their tools come from it,
    not from the prep folder or the hand-switched omx-tools-current link (2026-11-21: one release for worker and arm)."""
    return Path(os.environ.get("TOOLS_ROOT") or Path(__file__).resolve().parents[3])


def _arm_run_spec(arm_id: str, prep_dir: Path) -> tuple[Path, Path, Path, tuple[int, int, int, int], str]:
    specs = {
        "arm_b": ("with-session-arm-b-par.sh", "cell-arm-b-stack.json", "object-catalog-orange.json", (10, 340, 230, 478), "temp_plate_b"),
        "arm_a": ("with-session-arm-a-par.sh", "cell-arm-a-stack.json", "object-catalog-orange.json", (395, 360, 625, 478), "temp_plate_a"),
        "arm_s": ("with-session-arm-s-live.sh", "cell-auto-arm-s-live.json", "catalog-board-live-1113.json", (90, 150, 560, 450), "pinky"),
    }
    if arm_id not in specs:
        raise ValueError(f"unsupported arm_id for guarded pick: {arm_id!r}")
    wrapper, cfg, cat, roi, default_src = specs[arm_id]
    wrappers = tools_root() / "deploy/robot/omx/session-wrappers"  # the cell configs and catalogs stay prep-folder data
    return wrappers / wrapper, prep_dir / cfg, prep_dir / cat, roi, default_src


ZONE_TOL_M = 0.02  # the vehicle re-parks only past this (its repark lands within ~2 mm on 11-19)


def source_clearance(cfg: Path, cat: Path, roi, site: str) -> dict[str, Any]:
    """One read-only look at the source site after the carry: how many catalog objects are left (Fleet releases the
    vehicle only on 0). Camera only, no arm command; any failure is `objects: None` (Fleet holds)."""
    try:
        import cell_auto_pick_plan
        import cell_pipeline as cp

        config = json.loads(cfg.read_text(encoding="utf-8"))
        calibration = json.loads(Path(config["calibration_path"]).expanduser().read_text(encoding="utf-8"))
        catalog = json.loads(cat.read_text(encoding="utf-8"))
        catalog = catalog.get("objects", catalog) if isinstance(catalog, dict) else catalog
        cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
        frame = cell.frame_receipt("top", max_age_s=2.0)["image"] if callable(getattr(cell, "frame_receipt", None)) else None
        _img, mask, objects, error = cell_auto_pick_plan.observe(cell, config, calibration, site, roi, catalog, image=frame)
        if error:
            return {"objects": None, "error": error, "site": site}
        return {"objects": len(objects), "foreground_px": int((mask > 0).sum()) if mask is not None else None, "site": site,
                "centres_m": [[round(float(v), 4) for v in o["raw_m"][:2]] for o in objects if o.get("raw_m")]}
    except Exception as exc:  # observation is evidence, never a crash of the worker
        return {"objects": None, "error": f"{type(exc).__name__}: {exc}"[:200], "site": site}


def zone_fix(target, centres, tol_m: float = ZONE_TOL_M) -> dict | None:
    """The move (arm frame) that brings the object nearest the cell's dock target onto it, when it is off by > tol_m:
    the vehicle re-parks instead of the arm reaching for a box where it was never meant to be (2026-11-19 user)."""
    if not (isinstance(target, (list, tuple)) and len(target) == 2) or not centres:
        return None
    near = min(centres, key=lambda c: math.hypot(c[0] - target[0], c[1] - target[1]))
    need = [round(target[0] - near[0], 4), round(target[1] - near[1], 4)]
    if math.hypot(*need) <= tol_m:
        return None
    return {"object_arm_xy_m": list(near), "target_arm_xy_m": list(target), "need_arm_dxdy_m": need, "tol_m": tol_m}


def execute_guarded_cell_task(handoff: dict[str, Any], *, prep_dir: Path) -> dict[str, Any]:
    """Execute one Fleet cell handoff using the guarded pick executor or the read-only ACT preflight."""
    arm_id = resolve_task_arm(handoff)
    hold = check_arm_hold(arm_id)
    if hold.get("held"):
        return {"arm": arm_id, "error": f"ARM_INCIDENT_HELD:{hold.get('reason')}",
                "stop_event": {"command": "stop", "ok": False, "folded": False}}
    motion = handoff.get("motion")
    if motion is not None and not (isinstance(motion, dict) and motion.get("kind") == "free_pick" and handoff.get("cell_id") == "cell_ab"):
        return {"arm": arm_id, "error": "CELL_MOTION_NOT_EXECUTABLE",  # a push is propose-only: its completion check and approval rule are not decided
                "stop_event": {"command": "stop", "ok": False, "folded": False}}
    wrapper, cfg, cat, default_roi, default_src = _arm_run_spec(arm_id, prep_dir)
    if handoff.get("execution_mode") == "act_policy":
        if handoff.get("displaced_to") not in (None, ""):
            return {"arm": arm_id, "error": "UNCALIBRATED_DISPLACED_SITE",
                    "stop_event": {"command": "stop", "ok": False, "folded": False}}
        planned = plan_act_policy_task(handoff, arm_id=arm_id, prep_dir=prep_dir, wrapper=wrapper, cfg=cfg, default_roi=default_roi)
        return planned if "plan" not in planned else execute_act_policy_task(
            handoff, planned["plan"], arm_id=arm_id, wrapper=wrapper, cfg=cfg, cat=cat, prep_dir=prep_dir,
            lease_owner=f"{WORKER_LEASE_PREFIX}{os.getpid()}", tools_root_fn=tools_root, run_fn=subprocess.run,
            last_json_fn=last_json_object, measured_fold_fn=measured_fold, fold_readback_fn=fold_readback, plan_home_fn=plan_home,
            write_context_fn=write_context, timeout_exc=subprocess.TimeoutExpired, source_clearance_fn=source_clearance)
    if not wrapper.is_file() or not cfg.is_file():
        return {"arm": arm_id, "error": "CELL_CONFIG_OR_WRAPPER_MISSING",
                "stop_event": {"command": "stop", "ok": False, "folded": False}}
    cfg_data = json.loads(cfg.read_text(encoding="utf-8"))
    cfg_sites = cfg_data.get("sites") or {}
    raw_src = str(handoff.get("src_site") or default_src).strip()
    raw_dst = str(handoff.get("dst_site") or ("pallet-l0" if arm_id != "arm_s" else "belt")).strip()
    cell_id = str(handoff.get("cell_id") or "").strip()
    displaced = handoff.get("displaced_to")
    if displaced not in (None, ""):
        if not isinstance(displaced, str) or displaced.strip() not in ("belt_far", "floor_front"):
            return {"arm": arm_id, "error": "UNCALIBRATED_DISPLACED_SITE",
                    "stop_event": {"command": "stop", "ok": False, "folded": False}}
        disp = displaced.strip()
        if cell_id not in ("", "cell_s") or disp not in cfg_sites:
            return {"arm": arm_id, "error": "UNCALIBRATED_DISPLACED_SITE",
                    "stop_event": {"command": "stop", "ok": False, "folded": False}}
        raw_src = disp
    htier = handoff.get("tier")
    src_res = cell_site_target.resolve_cell_ab_site(raw_src, None, allow_belt_temp=True, allow_pallet_src=True) if cell_id != "cell_s" else None
    dst_res = cell_site_target.resolve_cell_ab_site(raw_dst, htier, allow_belt_temp=False) if cell_id != "cell_s" else None
    src = src_res["sim_site"] if src_res else ("stand" if raw_src in cell_site_target.STAND_ALIASES else raw_src)
    dst = dst_res["sim_site"] if dst_res else ("stand" if raw_dst in cell_site_target.STAND_ALIASES else raw_dst)
    if src == "belt" and "belt" not in cfg_sites and "beltend" in cfg_sites:
        src = "beltend"
    arm_err = cell_site_target.arm_refusal(raw_src, raw_dst, arm_id) if cell_id != "cell_s" else None
    if arm_err:
        return {"arm": arm_id, "error": arm_err, "stop_event": {"command": "stop", "ok": False, "folded": False}}
    cal_err = cell_site_target.calibration_refusal(cfg_sites, src, dst, htier) if cell_id != "cell_s" else None
    if cal_err:
        return {"arm": arm_id, "error": cal_err, "stop_event": {"command": "stop", "ok": False, "folded": False}}
    src_site, roi = pick_site(cfg_data, src, dst, default_roi)
    if roi is None:
        return {"arm": arm_id, "error": "ROUTE_DEPTH_INPUTS_MISSING", "stop_event": {"command": "stop", "ok": False, "folded": False}}
    src_roi = roi
    omx_dir = Path(__file__).resolve().parent
    target = (cfg_data.get("sites") or {}).get(src_site, {}).get("dock_target_arm_xy_m")
    if target is not None:  # camera only, before any arm command: off the dock target -> the vehicle re-parks
        seen = source_clearance(cfg, cat if cat.is_file() else omx_dir / "object-catalog.example.json", roi, src_site)
        fix = zone_fix(target, seen.get("centres_m") or [])
        if fix is not None:
            return {"arm": arm_id, "error": "ZONE_FIX_REQUESTED",
                    "stage_result": {"directive_id": handoff.get("task_id"), "arm_id": arm_id, "task_verified": False,
                                     "zone_fix": fix},
                    "stop_event": {"command": "stop", "ok": False, "folded": False}}
    cat_path = cat if cat.is_file() else omx_dir / "object-catalog.example.json"
    cmd = [
        str(wrapper),
        sys.executable,
        str(omx_dir / "cell_auto_pick.py"),
        "--config", str(cfg),
        "--catalog", str(cat_path),
        "--roi", *(str(int(v)) for v in roi),
        "--from", src,
        "--dest", dst,
        *(["--commissioning", "--person-at-switch"] if presence_ok(handoff) else ["--stop-proof"] if autonomous_policy_enabled(handoff) else []),
        "--task-id", str(handoff.get("task_id") or ""),
        "--handoff-lease-id", str(handoff.get("handoff_lease_id") or ""),
    ]
    import cell_target_binding
    cmd += cell_target_binding.handoff_cli_args(handoff)
    hint = (handoff.get("tier_hint") or {}).get("layers_below")
    if isinstance(hint, int) and not isinstance(hint, bool) and hint > 0:
        cmd += ["--layers-below", str(hint)]
    try:
        if motion is not None:  # free-position pick: the cell job API decides and moves, not a subprocess of ours
            proc, refusal = run_job(handoff, *free_pick_request(motion, arm_id=arm_id, config=cfg.name, catalog=cat_path.name, roi=roi, src=src, dst=dst))
            if refusal:
                return {"arm": arm_id, "error": refusal, "stage_result": {"directive_id": handoff.get("task_id"), "arm_id": arm_id, "task_verified": False},
                        "stop_event": {"command": "stop", "ok": False, "folded": False}}
        else:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                  env={**os.environ, "TOOLS_ROOT": str(tools_root()),
                                       "ROSY_ARM_LEASE_OWNER": f"{WORKER_LEASE_PREFIX}{os.getpid()}"})  # the wrapper's tools-env reads it
    except subprocess.TimeoutExpired:
        return {"arm": arm_id, "error": "SUBPROCESS_TIMEOUT",
                "stage_result": {"directive_id": handoff.get("task_id"), "arm_id": arm_id, "task_verified": False},
                "stop_event": {"command": "stop", "ok": False, "folded": False}}
    parsed = last_json_object(proc.stdout)
    # The wall clock at the end of the run bounds when the readbacks below existed (the runner's own clock is monotonic).
    measured_at = time.time()
    attempt = _last_attempt(parsed)
    placement = attempt.get("verify") if isinstance(attempt.get("verify"), dict) else {}
    placed = (proc.returncode == 0 and parsed.get("result") == "placed"
              and placement.get("verified") is True and placement.get("inside") is True)
    fold = fold_readback(attempt, plan_home(cfg_data))
    # main's telemetry reader: the arm's last runner state must also say folded and be fresh (2026-11-19 panel)
    live_fold = measured_fold(arm_id, prep_dir)
    clearance = source_clearance(cfg, cat_path, roi, src_site) if placed else None
    if isinstance(clearance, dict) and src_site != "pinky" and "site" not in clearance:
        clearance = {**clearance, "site": src_site}
    # D-1057: cell_auto_pick records top-frame placement (`verify`) and measures zone_verification for Fleet tasks;
    # without zone_verification from the attempt row, task_verified stays False and Fleet refuses completion.
    zone = attempt.get("zone_verification") if isinstance(attempt.get("zone_verification"), dict) else None
    if placed:
        write_context(cfg, cfg_data, handoff, arm_id, prep_dir, dst, src_site, src_roi, zone, cat_path=cat_path)
        from cell_objects_sync import bump_state_gen_after_pick
        bump_state_gen_after_pick(prep_dir, arm_id=arm_id, placed=True, task_id=str(handoff.get("task_id") or ""))
    zone_ok = zone_acceptance(zone, handoff, dst)  # the measured slot and tier must be the task's own
    tier = handoff.get("tier")
    if dst_res and not dst_res["is_legacy_pallet"]:
        place_payload = {
            "area": dst_res["area"], "site": dst_res["sim_site"], "site_id": dst_res["site_id"],
            "col": dst_res["col"], "row": dst_res["row"], "tier": tier if isinstance(tier, int) else dst_res["tier"],
        }
    else:
        dst_area = "belt" if dst == "belt_center" else dst.rsplit("-l", 1)[0]
        place_payload = {"area": dst_area, **({"tier": tier} if isinstance(tier, int) else {})}
    verification = ({**zone, "placement": placement} if zone is not None else
                    {"verified": False, "basis": placement.get("basis") or "unverified: no placement record",
                     "placement": placement,
                     "z_gate": {"verdict": "UNKNOWN", "reason": "no zone measurement from cell_auto_pick"}})
    folded = bool(placed and fold["folded"] and live_fold["folded"])
    stage_result = {
        "handoff_lease_id": handoff.get("handoff_lease_id"),
        "directive_id": handoff.get("task_id"),
        "arm_id": arm_id,
        "task_verified": placed and zone_ok,
        "place": place_payload,
        "verification": verification,
        "raw": parsed,
        **({"reach_fix": parsed["reach_fix"]} if parsed.get("reach_fix") else {}),
        **({"source_clearance": clearance} if clearance is not None else {}),
    }
    return {
        "arm": arm_id,
        "events_count": len(parsed.get("attempts") or []),
        "measured_at": measured_at,
        "stage_result": stage_result,
        "stop_event": {"command": "stop", "ok": folded, "folded": folded, "readback": fold, "live": live_fold,
                       **({"state": fold["state"]} if fold["state"] else {})},  # Fleet reads stop_event.state as joints
        "commissioning": presence_ok(handoff),
        **({"review_required": True} if review_required(parsed) else {}),
        **({"error": parsed.get("result") or f"exit_{proc.returncode}"} if not placed else
           {} if folded else {"error": "FOLD_READBACK_MISSING"}),
    }
