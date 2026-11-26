"""Readiness telemetry, failure-context HTTP routing, frame header proxying, and structured job parsing (D-1072)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from cell_failure_context import canonical_sha256, list_bundles, load_bundle, resolve_asset
from cell_job_guards import _live_folded, read_json_dict

ARMS = ("arm_s", "arm_a", "arm_b")
CELL_ARMS = {"cell_s": ("arm_s",), "cell_ab": ("arm_a", "arm_b")}
READINESS_SCHEMA = "rosy.cell-readiness.v1"
_FORWARD_HEADERS = ("X-Frame-Seq", "X-Source-Stamp", "ETag", "Cache-Control")
_LOG_TAIL_BYTES = 65_536


class CellStateGen:
    """Thread-safe persistent monotonic `cell_state_gen` counter under `<workdir>/cell-job-api/`."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._value = self._load_locked()

    def _load_locked(self) -> int:
        data = read_json_dict(self.path)
        val = (data or {}).get("cell_state_gen")
        return val if isinstance(val, int) and not isinstance(val, bool) and val >= 0 else 0

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"cell_state_gen": self._value, "updated_at": time.time()}) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def current(self) -> int:
        with self._lock:
            disk = self._load_locked()
            if disk > self._value:
                self._value = disk
            return self._value

    def bump(self) -> int:
        with self._lock:
            self._value = max(self._value, self._load_locked()) + 1
            self._save_locked()
            return self._value


def held_job_response(arm: str, reason: str) -> dict:
    from core_common.protocol.arm_incident.home_recovery import HOME_RECOVERY_REASON
    if reason == HOME_RECOVERY_REASON:
        return {"code": 409, "error_code": "HOME_RECOVERY_REQUIRED", "error": reason}
    return {"code": 409, "error_code": "ARM_INCIDENT_HELD", "error": f"{arm} held: {reason}"}


def _stale_latch(arm: str, runner, live, session_held: bool) -> bool:
    import cell_arm_lease
    from cell_job_peer_health import stale_latch_superseded

    lease_dir = getattr(runner, "lease_dir", None)
    lease_path = Path(lease_dir) / f"{arm}.json" if lease_dir else None
    lease = read_json_dict(lease_path) if lease_path else None
    leased = (lease is None and lease_path is not None and lease_path.is_file()) or bool(lease and cell_arm_lease.live(lease))
    health = getattr(runner, "motor_health_dir", None) or (Path.home() / ".local" / "state" / "rosy" / "motor-health")
    from cell_job_api import LIVE_MAX_AGE_S

    return stale_latch_superseded(arm, live, locked=session_held, leased=leased, max_age_s=LIVE_MAX_AGE_S, health_dir=health,
                                  read_json_fn=read_json_dict, calibration_dir=getattr(runner, "calibration_dir", None))


def _arm_summary(arm: str, runner, now: float, *, session_lock_held_fn, inc_reason: str | None, active_job: str | None, cell_fleet: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    suffix = arm.split("_")[-1]
    live = read_json_dict(runner.workdir / f"chunk-io-{suffix}" / "live.json")
    dirty = read_json_dict(runner.workdir / f"cell-state-dirty-{arm}.json") is not None
    session_held = bool(session_lock_held_fn(arm, runner.lock_dir))
    age_s = None
    if isinstance(live, dict) and isinstance(live.get("t"), (int, float)) and not isinstance(live.get("t"), bool):
        age_s = round(max(0.0, now - float(live["t"])), 3)
    fault = live.get("fault") if isinstance(live, dict) else None
    hold_latched = bool(live.get("human_hold_latched")) if isinstance(live, dict) else False
    folded = _live_folded(live) if isinstance(live, dict) else None  # guards judge peers coarsely until they pass the arm's library
    stale_latch = hold_latched and _stale_latch(arm, runner, live, session_held)
    superseded = {"fault": str(fault)[:160] if fault else None, "latched_t": live.get("t")} if stale_latch else None
    if stale_latch:  # the runner that latched is gone and the arm reads torque-off, folded, jaws shut: report what is there now
        fault, hold_latched, folded = None, False, True
    cid = "cell_s" if arm == "arm_s" else "cell_ab"
    info = {
        "session_lock_held": session_held,
        "incident_held": bool(inc_reason),
        "incident_reason": str(inc_reason)[:160] if inc_reason else None,
        "folded": folded if isinstance(folded, bool) else None,
        "fold_basis": "coarse",
        "human_hold_latched": hold_latched,
        "stale_latch_superseded": superseded,  # the left-behind latch, kept visible: its fault text and time
        "fault": str(fault)[:160] if fault else None,
        "live_state_age_s": age_s,
        "dirty": dirty,
        "active_job_id": active_job,
        "fleet_safety": {
            "cell_id": cid,
            "online": bool(cell_fleet.get("online")),
            "blocked": bool(cell_fleet.get("blocked")),
            "reason": cell_fleet.get("reason"),
        },
    }
    blocks: list[str] = []
    if inc_reason:
        from core_common.protocol.arm_incident.home_recovery import HOME_RECOVERY_REASON
        blocks.append(f"{arm}:incident_held")  # existing motion fences consume this refusal
        if inc_reason == HOME_RECOVERY_REASON:
            blocks.append(f"{arm}:home_recovery_required")
    if fault:
        blocks.append(f"{arm}:fault")
    if hold_latched:
        blocks.append(f"{arm}:human_hold_latched")
    if session_held:
        blocks.append(f"session_lock:{arm}")
    return info, blocks


def build_readiness(
    runner,
    *,
    whole_cell_lock_fn,
    session_lock_fn,
    depth_lock_fn,
    holds_by_arm: dict[str, str | None] | None = None,
    cell: str | None = None,
) -> dict[str, Any]:
    """Assemble strict `rosy.cell-readiness.v1` payload matching `CellReadiness`."""
    if cell is not None and cell not in CELL_ARMS:
        raise ValueError(f"unknown cell {cell!r}")
    target_cells = (cell,) if cell is not None else tuple(CELL_ARMS)
    target_arms = tuple(a for cid in target_cells for a in CELL_ARMS[cid])
    now = time.time()
    gen = runner.state_gen()
    whole_locked = bool(whole_cell_lock_fn(runner.lock_dir))
    depth_locked = bool(depth_lock_fn(runner.lock_dir))
    holds = holds_by_arm if holds_by_arm is not None else {arm: runner._check_incident(arm) for arm in target_arms}
    with runner.lock:
        runs_snap = [
            (jid, tuple(r.get("arms") or (() if not r.get("arm") else (r["arm"],))))
            for jid, r in runner.runs.items()
            if r["proc"].poll() is None
        ]
    active_by_arm = {arm: next((jid for jid, r_arms in runs_snap if arm in r_arms), None) for arm in target_arms}
    fleet_by_cell = {
        cid: (runner._check_fleet_safety("arm_s" if cid == "cell_s" else "arm_a") or {})
        for cid in target_cells
    }
    base_refusals: list[str] = []
    if whole_locked:
        base_refusals.append("whole_cell_lock_held")
    if depth_locked:
        base_refusals.append("depth_lock_held")
    arms: dict[str, dict[str, Any]] = {}
    arm_blocks_by_arm: dict[str, list[str]] = {}
    for arm in target_arms:
        cid = "cell_s" if arm == "arm_s" else "cell_ab"
        info, arm_blocks = _arm_summary(
            arm, runner, now, session_lock_held_fn=session_lock_fn,
            inc_reason=holds.get(arm), active_job=active_by_arm[arm], cell_fleet=fleet_by_cell[cid],
        )
        arms[arm] = info
        arm_blocks_by_arm[arm] = arm_blocks

    cells: dict[str, dict[str, Any]] = {}
    for cid in target_cells:
        c_arms = CELL_ARMS[cid]
        fst = fleet_by_cell[cid]
        c_fleet_blocked = bool(fst.get("blocked"))
        c_refusals = list(base_refusals)
        if c_fleet_blocked:
            c_refusals.append(f"fleet_safety:{cid}:{str(fst.get('reason') or 'blocked')[:85]}")
        for arm in c_arms:
            c_refusals.extend(arm_blocks_by_arm[arm])
        c_all_blocked = all(arms[a]["incident_held"] or arms[a]["fault"] or arms[a]["human_hold_latched"] for a in c_arms)
        c_tiers = (
            [0] if (whole_locked or c_fleet_blocked or c_all_blocked)
            else ([0, 1] if (c_refusals or any(arms[a]["dirty"] for a in c_arms)) else [0, 1, 2])
        )
        cells[cid] = {
            "arms": list(c_arms),
            "fleet_safety": {"cell_id": cid, "online": bool(fst.get("online")), "blocked": c_fleet_blocked, "reason": fst.get("reason")},
            "blocking_refusals": [r[:120] for r in c_refusals[:20]],
            "allowed_tiers_now": c_tiers,
        }

    if cell is not None:
        refusals = list(cells[cell]["blocking_refusals"])
        tiers = list(cells[cell]["allowed_tiers_now"])
    else:
        refusals = list(base_refusals)
        for cid in target_cells:
            if fleet_by_cell[cid].get("blocked"):
                refusals.append(f"fleet_safety:{cid}:{str(fleet_by_cell[cid].get('reason') or 'blocked')[:85]}")
        for arm in target_arms:
            refusals.extend(arm_blocks_by_arm[arm])
        any_fleet_blocked = any(bool(fleet_by_cell[cid].get("blocked")) for cid in target_cells)
        all_blocked = all(arms[a]["incident_held"] or arms[a]["fault"] or arms[a]["human_hold_latched"] for a in target_arms)
        tiers = (
            [0] if (whole_locked or any_fleet_blocked or all_blocked)
            else ([0, 1] if (refusals or any(arms[a]["dirty"] for a in target_arms)) else [0, 1, 2])
        )
    core = {
        "schema": READINESS_SCHEMA,
        "observed_at": round(now, 3),
        "max_age_s": 5.0,
        "cell_state_gen": gen,
        "arms": arms,
        "cells": cells,
        "blocking_refusals": [r[:120] for r in refusals[:20]],
        "allowed_tiers_now": tiers,
    }
    return {**core, "readiness_digest": canonical_sha256(core, omit_keys=())}


def read_tail_bytes(path: Path, max_bytes: int) -> bytes:
    if max_bytes <= 0:
        return b""
    with path.open("rb") as handle:
        count = min(handle.seek(0, os.SEEK_END), max_bytes)
        handle.seek(-count, os.SEEK_CUR)
        return handle.read(count)


def parse_structured_result(log_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Extract the final JSON object emitted in a job log even past the 4000-byte log tail."""
    try:
        if not log_path.is_file():
            return None, None
        raw = read_tail_bytes(log_path, _LOG_TAIL_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return None, None
    decoder = json.JSONDecoder()
    starts = [m.start() for m in re.finditer(r"(?m)^\{", raw)]
    for pos in reversed(starts):
        try:
            obj, end = decoder.raw_decode(raw[pos:])
        except ValueError:
            continue
        if isinstance(obj, dict) and not raw[pos + end :].strip():
            bid = obj.get("failure_bundle_id")
            return obj, (bid if isinstance(bid, str) else None)
    for pos in reversed(starts):
        try:
            obj, _ = decoder.raw_decode(raw[pos:])
        except ValueError:
            continue
        if isinstance(obj, dict):
            bid = obj.get("failure_bundle_id")
            return obj, (bid if isinstance(bid, str) else None)
    return None, None


def proxy_frame(viewer_url: str, view: str, *, urlopen_fn=urllib.request.urlopen, timeout: float = 5.0) -> tuple[int, Any, str, dict[str, str]]:
    """Fetch `/frame/<view>.jpg` from `:8767` and preserve sequence/stamp/ETag headers."""
    try:
        with urlopen_fn(f"{viewer_url}/frame/{view}.jpg", timeout=timeout) as resp:
            hdrs = {k: str(v) for k in _FORWARD_HEADERS if (v := resp.headers.get(k)) is not None}
            return 200, resp.read(), "image/jpeg", hdrs
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": f"viewer returned HTTP {exc.code}"}, "application/json", {}
    except OSError as exc:
        return 502, {"error": f"viewer unreachable: {exc}"}, "application/json", {}


def handle_get_route(raw_target: str, runner, *, whole_cell_lock_fn, session_lock_fn, depth_lock_fn) -> tuple[int, Any, str, dict[str, str]] | None:
    """Serve `/readiness`, `/failures`, `/failures/latest`, `/failures/{id}`, and `/failures/{id}/assets/{file}`."""
    if raw_target.startswith("/failures") and (".." in raw_target or "%2e" in raw_target.lower() or "\\" in raw_target):
        return 400, {"error": "invalid failure path"}, "application/json", {}
    parsed = urllib.parse.urlsplit(raw_target)
    path = parsed.path
    qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
    gen = runner.state_gen()
    base_hdrs = {"X-Cell-State-Gen": str(gen)}

    if path == "/readiness":
        raw_cells = urllib.parse.parse_qs(parsed.query, keep_blank_values=True).get("cell")
        if raw_cells is not None and (len(raw_cells) != 1 or raw_cells[0] not in CELL_ARMS):
            return 400, {"error": "invalid cell query parameter"}, "application/json", base_hdrs
        cell_param = raw_cells[0] if raw_cells is not None else None
        rel_arms = CELL_ARMS[cell_param] if cell_param is not None else ARMS
        holds_by_arm = {arm: runner._check_incident(arm) for arm in rel_arms}
        body = build_readiness(runner, whole_cell_lock_fn=whole_cell_lock_fn, session_lock_fn=session_lock_fn, depth_lock_fn=depth_lock_fn, holds_by_arm=holds_by_arm, cell=cell_param)
        return 200, body, "application/json", base_hdrs
    if path == "/failures":
        arm = (qs.get("arm") or [None])[0]
        kind = (qs.get("kind") or [None])[0]
        try:
            limit = int((qs.get("limit") or ["20"])[0])
        except ValueError:
            return 400, {"error": "invalid limit query parameter"}, "application/json", base_hdrs
        rows = list_bundles(runner.bundle_root, arm=arm, kind=kind, limit=limit)
        return 200, {"bundles": rows, "cell_state_gen": gen}, "application/json", base_hdrs
    if path == "/failures/latest":
        arm = (qs.get("arm") or [None])[0]
        kind = (qs.get("kind") or [None])[0]
        rows = list_bundles(runner.bundle_root, arm=arm, kind=kind, limit=1)
        if not rows:
            return 404, {"error": "no matching failure bundle"}, "application/json", base_hdrs
        active_holds = tuple(a for a in ARMS if runner._check_incident(a))
        try:
            bundle = load_bundle(runner.bundle_root, rows[0]["bundle_id"], current_cell_state_gen=gen, active_holds=active_holds)
            return 200, bundle, "application/json", {**base_hdrs, "ETag": f'"{bundle["context_sha256"]}"'}
        except FileNotFoundError:
            return 404, {"error": "failure bundle not found"}, "application/json", base_hdrs
        except ValueError as exc:
            return 400, {"error": str(exc)}, "application/json", base_hdrs
    if m := re.fullmatch(r"/failures/([^/]+)", path):
        active_holds = tuple(a for a in ARMS if runner._check_incident(a))
        try:
            bundle = load_bundle(runner.bundle_root, m.group(1), current_cell_state_gen=gen, active_holds=active_holds)
            return 200, bundle, "application/json", {**base_hdrs, "ETag": f'"{bundle["context_sha256"]}"'}
        except FileNotFoundError:
            return 404, {"error": f"bundle {m.group(1)} not found"}, "application/json", base_hdrs
        except ValueError as exc:
            return 400, {"error": str(exc)}, "application/json", base_hdrs
    if m := re.fullmatch(r"/failures/([^/]+)/assets/([^/]+)", path):
        try:
            asset_path, mime, sha = resolve_asset(runner.bundle_root, m.group(1), m.group(2))
            return 200, asset_path.read_bytes(), mime, {**base_hdrs, "ETag": f'"{sha}"'}
        except FileNotFoundError:
            return 404, {"error": "failure asset not found"}, "application/json", base_hdrs
        except ValueError as exc:
            return 400, {"error": str(exc)}, "application/json", base_hdrs
    return None
