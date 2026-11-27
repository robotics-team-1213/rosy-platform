#!/usr/bin/env python3
"""Arm & Camera Telemetry Sync + Verified Safe-Home Relay for OMX Cell Worker (`cell_camera_telemetry_sync.py`).

Single Responsibility:
  - Gathers camera quality facts from local `commissioning_view` (`:8767`) `state.json`,
  - Gathers `omx_incident` hold status and `chunk-status.jsonl` live arm states (`arm_s`, `arm_a`, `arm_b`),
  - Gathers each arm's pinned shadow model (`act_shadow` in its cell-auto config) and its act-shadow.jsonl summary,
  - Posts the facts to `/api/fleet/pipeline/cell-quality` and relays request-bound safe-home outcomes only over
    verified TLS when `allow_safe_home=True`.

D-136: camera JPEG bytes are never uploaded. Fleet relays no video; the console reads
frames through Vision preview leases only.
"""
from __future__ import annotations

import hashlib, inspect, json, math, os, re, ssl, threading, time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from cell_safe_home_receipts import _bound_home_arms, _home_result_ack, _read_ack_map, _write_ack_map_atomic

DEFAULT_PREP_DIR = Path("/home/robttt/rosy-test/omx-record-prep-20261019")
CAMERA_KEYS: tuple[str, ...] = ("top", "side", "arm_a_wrist", "arm_b_wrist", "arm_s_top", "arm_s_wrist")
ARM_SUFFIXES: dict[str, str] = {"arm_s": "s", "arm_a": "a", "arm_b": "b"}
SHADOW_TAIL, AUTO_EVENT_TAIL, _TAIL_CHUNK_BYTES = 200, 30, 65536
_CACHE_LOCK, _FILE_CACHE, _SSL_CACHE, _MISS = threading.Lock(), {}, {}, object()
BLOCK_REASON = "학습 정책 실물 실행은 사용자 승인 전(D-1024 L3 arm_b 한정, cell_executor 승인 목록 ik_chunk)"


def _file_sig(path: Path) -> tuple[str, int, int, int] | None:
    try:
        st = path.stat()
        return (str(path), st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _read_tail_lines(path: Path, max_lines: int, chunk_bytes: int = _TAIL_CHUNK_BYTES) -> list[str]:
    """Read up to ``max_lines`` trailing lines without loading multi-megabyte JSONL files."""
    if max_lines <= 0:
        return []
    try:
        with path.open("rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            if size <= 0:
                return []
            span, offset = max(chunk_bytes, 1024), 0
            while True:
                offset = max(0, size - span)
                fh.seek(offset, os.SEEK_SET)
                buf = fh.read(size - offset)
                if offset == 0 or buf.count(b"\n") > max_lines:
                    break
                span *= 2
            if offset > 0:
                nl = buf.find(b"\n")
                buf = b"" if nl < 0 else buf[nl + 1:]
    except OSError:
        return []
    return buf.decode("utf-8", errors="replace").splitlines()[-max_lines:]


def _tail_json_lines(path: Path, max_lines: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in _read_tail_lines(path, max_lines):
        if line.lstrip().startswith("{"):
            try:
                if isinstance(row := json.loads(line), dict):
                    rows.append(row)
            except ValueError:
                continue
    return rows


def _cached(key: tuple[Any, ...], compute: Any, *, store: dict[Any, Any] = _FILE_CACHE, cap: int = 256) -> Any:
    with _CACHE_LOCK:
        if (hit := store.get(key, _MISS)) is not _MISS:
            return hit
    val = compute()
    with _CACHE_LOCK:
        if len(store) > cap:
            store.clear()
        store[key] = val
    return val


def _ssl_context(ca_file: str | Path | None, verified: bool, is_https: bool) -> ssl.SSLContext:
    ca_path = Path(ca_file).expanduser() if ca_file else None
    key = (_file_sig(ca_path) or str(ca_path) if ca_path else None, bool(verified), bool(is_https))
    return _cached(key, lambda: (
        ssl.create_default_context(cafile=str(ca_path)) if ca_path else
        (ssl.create_default_context() if (verified and is_https) else ssl._create_unverified_context())
    ), store=_SSL_CACHE, cap=32)


def _fetch_local_state_json(urlopen_fn: Any = urlopen) -> dict[str, Any]:
    try:
        sreq = Request("http://127.0.0.1:8767/state.json", headers={"Host": "127.0.0.1:8767"})
        with urlopen_fn(sreq, timeout=1.5) as sresp:
            return data if isinstance(data := json.load(sresp), dict) else {}
    except Exception:
        return {}


def _parse_arm_state_tail(st_file: Path, mtime_ns: int) -> dict[str, Any] | None:
    for ev in reversed(_tail_json_lines(st_file, 25)):
        try:
            st_arr = ev.get("state")
            if isinstance(st_arr, list) and len(st_arr) >= 6:
                health = ev.get("health") or {}
                temps, curs = health.get("temp_c") or [], health.get("current_ma") or []
                return {
                    "joints_deg": [round(float(x), 1) for x in st_arr[:6]],
                    "folded": bool(ev.get("folded", float(st_arr[1]) <= -50.0 and float(st_arr[2]) >= 45.0)),
                    "temp_c": round(float(max(temps)), 1) if temps else None,
                    "current_ma": round(float(max(curs)), 1) if curs else None,
                    "updated_at": round(mtime_ns / 1e9, 3), "source": "chunk_status_live",
                }
        except Exception:
            continue
    return None


def _collect_live_arm_states(prep_dir: Path) -> dict[str, Any]:
    arm_states: dict[str, Any] = {}
    for arm_id, suffix in ARM_SUFFIXES.items():
        for io_name in (f"chunk-io-{suffix}", f"chunk-io-{suffix}-r2s"):
            st_file = prep_dir / io_name / "chunk-status.jsonl"
            if (sig := _file_sig(st_file)) is not None:
                if (parsed := _cached(("arm_state", *sig), lambda p=st_file, m=sig[2]: _parse_arm_state_tail(p, m))) is not None:
                    arm_states[arm_id] = {**parsed, "joints_deg": list(parsed["joints_deg"])}
                    break
    return arm_states


def _read_shadow_summary(log: Path, mtime_ns: int, policy_rev: Any) -> dict[str, Any]:
    rows = [r for r in _tail_json_lines(log, SHADOW_TAIL) if r.get("policy_id") == policy_rev]
    errors, last = [r for r in rows if r.get("error")], (rows[-1] if rows else {})
    return {
        "rows": len(rows), "errors": len(errors),
        "last_at": round(mtime_ns / 1e9, 3) if rows else None,
        "last_ik_outcome": (last.get("ik") or {}).get("outcome"),
        "last_error": str(errors[-1]["error"])[:120] if errors else None,
    }


def _collect_arm_models(prep_dir: Path) -> dict[str, Any]:
    """Per arm: the pinned shadow model and a summary of its proposals, {} without one. Never an execution grant."""
    models: dict[str, Any] = {arm_id: {} for arm_id in ARM_SUFFIXES}
    for arm_id, suffix in ARM_SUFFIXES.items():
        candidates = sorted(prep_dir.glob(f"cell-auto-arm-{suffix}-*.json"))
        seen = set(candidates)
        candidates.extend(p for p in sorted(prep_dir.glob(f"cell-arm-{suffix}-*.json")) if p not in seen)
        for path in candidates:
            try:
                if (cfg_sig := _file_sig(path)) is None:
                    continue
                config = _cached(("cfg", *cfg_sig), lambda p=path: json.loads(p.read_text(encoding="utf-8")))
                spec = config.get("act_shadow")
                if not isinstance(spec, dict) or not spec.get("policy_root"):
                    continue
                root, rev = Path(str(spec["policy_root"])).expanduser(), spec.get("policy_revision")
                warp = root / "cam_warp.json"
                warp_sha = (_cached(("warp", *wsig), lambda w=warp: hashlib.sha256(w.read_bytes()).hexdigest())
                            if (wsig := _file_sig(warp)) is not None else None)
                entry: dict[str, Any] = {
                    "name": root.name, "policy_revision": rev, "kind": "shadow",
                    "binding": spec.get("kind") or "act_inference", "config": path.name, "warp_sha256": warp_sha,
                    "execution_allowed": False, "block_reason": BLOCK_REASON,
                    "shadow": {"rows": 0, "errors": 0, "last_at": None, "last_ik_outcome": None, "last_error": None},
                }
                log = Path(str(config.get("work_dir") or path.parent)).expanduser() / "act-shadow.jsonl"
                if (lsig := _file_sig(log)) is not None:
                    rev_key = rev if isinstance(rev, (str, int, float, bool, type(None))) else json.dumps(rev, sort_keys=True)
                    entry["shadow"] = dict(_cached(
                        ("shadow", *lsig, rev_key), lambda l=log, m=lsig[2], r=rev: _read_shadow_summary(l, m, r),
                    ))
                models[arm_id] = entry
                break
            except Exception:
                continue
    return models


def _collect_auto_events(prep_dir: Path) -> list[dict[str, Any]]:
    path = prep_dir / "incidents" / "auto-events.jsonl"
    if (sig := _file_sig(path)) is None:
        return []
    return [dict(r) for r in _cached(("events", *sig), lambda p=path: _tail_json_lines(p, AUTO_EVENT_TAIL))]


def sync_cell_telemetry(fleet_r_url: str, token: str, prep_dir: Path = DEFAULT_PREP_DIR, urlopen_fn: Any = urlopen,
                        *, ca_file: str | Path | None = None, tls_verified: bool | None = None,
                        allow_safe_home: bool = False, launch_auto_fold_fn: Any = None) -> dict[str, Any]:
    """Post telemetry to Fleet and run D-1048 auto-fold stages only over verified HTTPS & active guard mode."""
    base = fleet_r_url.rstrip("/")
    is_https = base.startswith("https://")
    verified = bool(tls_verified) if tls_verified is not None else bool(ca_file)
    ack_file = prep_dir / ".safe-home-acks.json"
    fence_file = prep_dir / ".safety-fence.json"
    try:
        ctx = _ssl_context(ca_file, verified, is_https)
        state_json = _fetch_local_state_json(urlopen_fn)
        ack_map = _read_ack_map(ack_file)
        bound_arms = _bound_home_arms(launch_auto_fold_fn) if allow_safe_home and is_https and verified else []
        for rid, rec in ack_map.items():
            if rec.get("incident_id") and rec.get("outcome") in ("in_flight", "started"):
                # The motion can finish after the Fleet request's admission window expires.
                result = _home_result_ack(prep_dir, rec.get("arm_id"), rid, rec["incident_id"])
                if result:
                    ack_map[rid] = result
        cams_quality: dict[str, Any] = {}
        for cam in CAMERA_KEYS:
            entry = state_json.get(cam) or (state_json.get("cameras") or {}).get(cam)
            if isinstance(entry, dict):
                cams_quality[cam] = {
                    "fresh": bool(entry.get("fresh", True)), "sequence": entry.get("sequence"),
                    "receipt_age_s": entry.get("receipt_age_s"), "quality": entry.get("quality") or {},
                }
        arm_holds: dict[str, Any] = {}
        try:
            import omx_incident  # type: ignore
            for arm_id in ("arm_s", "arm_a", "arm_b"):
                arm_holds[arm_id] = omx_incident.status(arm_id)
        except Exception:
            pass
        payload = {
            "schema": "rosy.pipeline.cell-quality.v1", "cameras": cams_quality, "arm_holds": arm_holds,
            "arm_states": _collect_live_arm_states(prep_dir), "arm_models": _collect_arm_models(prep_dir),
            "auto_events": _collect_auto_events(prep_dir), "incident_bound_home": bool(bound_arms),
            "incident_bound_home_arms": bound_arms,
            **({"safe_home_acks": list(ack_map.values())} if ack_map else {}),
        }
        qreq = Request(f"{base}/api/fleet/pipeline/cell-quality", data=json.dumps(payload).encode("utf-8"),
                       method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urlopen_fn(qreq, context=ctx, timeout=6) as qresp:
            qout = json.load(qresp)
        for arm_id, note in (qout.get("pending_clear_arms") or {}).items():
            try:
                import omx_incident  # type: ignore
                sync_fn = getattr(omx_incident, "sync_hold_from_fleet", None)
                if not (callable(sync_fn) and sync_fn(str(arm_id))):
                    omx_incident.clear(str(arm_id), str(note))
            except Exception:
                pass
        pending_home = qout.get("pending_safe_home_arms") or {}
        if not isinstance(pending_home, dict):
            pending_home = {}
        fence_valid = (
            isinstance(qout, dict)
            and qout.get("schema") == "rosy.pipeline.cell-quality.v1"
            and type(qout.get("human_hold")) is bool
            and type(qout.get("safety_stop_generation")) is int
        )
        if fence_valid:
            _write_ack_map_atomic(fence_file, {
                "stop_generation": qout["safety_stop_generation"],
                "human_hold": qout["human_hold"],
                "updated_at": round(time.time(), 3),
            })
        elif fence_file.exists():
            fence_file.unlink()
        active_req_ids = {str(s.get("request_id")) for s in pending_home.values() if isinstance(s, dict) and s.get("request_id")}
        next_acks = {
            rid: rec for rid, rec in ack_map.items()
            if rid in active_req_ids or rec.get("outcome") in ("in_flight", "started")
        }
        now_t = time.time()
        can_run_safe_home = bool(allow_safe_home and is_https and verified and fence_valid)
        if not fence_valid and isinstance(qout, dict):
            qout["safe_home_blocked_reason"] = "INCOMPLETE_SAFETY_FENCE"
        if pending_home and not can_run_safe_home:
            qout["safe_home_blocked_reason"] = (
                "SEALED_WORKER_MODE" if not allow_safe_home
                else "UNVERIFIED_TLS" if not (is_https and verified)
                else "INCOMPLETE_SAFETY_FENCE"
            )
        elif pending_home:
            for arm_id in sorted(pending_home.keys()):
                spec = pending_home.get(arm_id)
                if not isinstance(spec, dict) or not spec.get("request_id"):
                    continue
                req_id = str(spec["request_id"])
                root = spec.get("root_task_id")
                bound = isinstance(root, str) and root.startswith("home-recovery:")
                incident_id = root.rsplit(":", 1)[-1] if bound else None
                local = arm_holds.get(arm_id) or {}
                if not bound and local.get("fleet_held") is True:
                    from core_common.protocol.arm_incident.home_recovery import HOME_RECOVERY_REASON
                    if local.get("fleet_reason") == HOME_RECOVERY_REASON:
                        next_acks[req_id] = {"arm_id": arm_id, "request_id": req_id, "outcome": "skipped",
                                             "detail": "HOME_RECOVERY_BINDING_REQUIRED"}
                        continue
                if bound or "incident_id" in spec:
                    if (arm_id not in bound_arms or not incident_id or not re.fullmatch("[0-9a-f]{32}", incident_id)
                            or root != f"home-recovery:{arm_id}:{incident_id}"
                            or spec.get("arm_id") != arm_id or spec.get("incident_id", incident_id) != incident_id
                            or spec.get("strategy") != "auto_fold"):
                        next_acks[req_id] = {"arm_id": arm_id, "request_id": req_id, "outcome": "skipped",
                                             "detail": "HOME_RECOVERY_BINDING_INVALID"}
                        continue
                result_ack = _home_result_ack(prep_dir, arm_id, req_id, incident_id)
                if result_ack:
                    next_acks[req_id] = result_ack
                    continue
                if req_id in next_acks or spec.get("started"):
                    continue
                exp = spec.get("expires_at")
                if exp is None:
                    next_acks[req_id] = {"arm_id": str(arm_id), "request_id": req_id,
                                         "outcome": "skipped", "detail": "SAFE_HOME_EXPIRY_MISSING"}
                    continue
                if isinstance(exp, bool) or not isinstance(exp, (int, float)):
                    next_acks[req_id] = {"arm_id": str(arm_id), "request_id": req_id,
                                         "outcome": "skipped", "detail": "SAFE_HOME_EXPIRY_INVALID"}
                    continue
                try:
                    exp_f = float(exp)
                except (TypeError, ValueError, OverflowError):
                    next_acks[req_id] = {"arm_id": str(arm_id), "request_id": req_id,
                                         "outcome": "skipped", "detail": "SAFE_HOME_EXPIRY_INVALID"}
                    continue
                if not math.isfinite(exp_f):
                    next_acks[req_id] = {"arm_id": str(arm_id), "request_id": req_id,
                                         "outcome": "skipped", "detail": "SAFE_HOME_EXPIRY_INVALID"}
                    continue
                if now_t > exp_f:
                    next_acks[req_id] = {"arm_id": str(arm_id), "request_id": req_id,
                                         "outcome": "skipped", "detail": "SAFE_HOME_EXPIRED"}
                    continue
                binding = {"incident_id": incident_id} if bound else {}
                next_acks[req_id] = {"arm_id": str(arm_id), "request_id": req_id, "outcome": "in_flight", **binding}
                _write_ack_map_atomic(ack_file, next_acks)
                strategy = str(spec.get("strategy") or "auto_fold")
                stage = "release_and_lift" if strategy == "release_and_lift" else ("park_only" if strategy == "guarded_slow_park" else "full")
                fold_fn = launch_auto_fold_fn
                if fold_fn is None:
                    import omx_incident_auto  # type: ignore
                    fold_fn = omx_incident_auto.launch_auto_fold
                try:
                    params = inspect.signature(fold_fn).parameters
                    has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
                    if "stage" in params or has_varkw:
                        kw = {k: v for k, v in {
                            "stage": stage, "request_id": req_id, "expires_at": exp,
                            "stop_generation": spec.get("stop_generation"), "safety_fence": str(fence_file),
                            **({"expected_incident_id": incident_id} if bound else {}),
                        }.items() if has_varkw or k in params}
                        res = fold_fn(str(arm_id), **kw)
                    else:
                        res = fold_fn(str(arm_id))
                    started = isinstance(res, dict) and bool(res.get("started"))
                    explicit = res.get("outcome") if isinstance(res, dict) else None
                    next_acks[req_id] = {
                        "arm_id": str(arm_id), "request_id": req_id,
                        "outcome": str(explicit) if explicit else ("started" if started else "skipped"), **binding,
                        **({"detail": str((res or {}).get("why") or (res or {}).get("reason") or "not_started")[:120]} if not started else {}),
                    }
                except Exception as exc:
                    next_acks[req_id] = {
                        "arm_id": str(arm_id), "request_id": req_id, "outcome": "failed", "detail": str(exc)[:120],
                    }
        _write_ack_map_atomic(ack_file, next_acks)
        if bound_arms and fence_valid and qout["human_hold"] is False:
            from cell_bound_home_request import request_current_homes
            try:
                request_current_homes(base, token, ctx, urlopen_fn, bound_arms, arm_holds, pending_home)
            except (OSError, ValueError, KeyError) as exc:
                qout["bound_home_request_error"] = type(exc).__name__
        try:
            from cell_objects_sync import sync_cell_objects
            qout["cell_objects_sync"] = sync_cell_objects(base, token, ctx, urlopen_fn, prep_dir=prep_dir)
        except Exception as exc:
            qout["cell_objects_sync_error"] = type(exc).__name__
        return qout
    except Exception:
        try:
            (prep_dir / ".safety-fence.json").unlink(missing_ok=True)
        except Exception:
            pass
        return {}


def inspect_camera_frame_telemetry(prep_dir: Path = DEFAULT_PREP_DIR, cell_id: str = "cell_s") -> dict[str, Any]:
    snaps = sorted(prep_dir.glob("*/cam-*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
    snap_bytes = snaps[0].stat().st_size if snaps else 0
    intrusion_score = 0.02
    condition = "NORMAL"
    state_json = _fetch_local_state_json()
    if state_json:
        cam_key = "arm_s_top" if cell_id == "cell_s" else "top"
        entry = state_json.get(cam_key) or (state_json.get("cameras") or {}).get(cam_key) or {}
        q = entry.get("quality") or {}
        condition = str(q.get("condition") or "NORMAL")
        dark_frac = float(q.get("dark_fraction") or 0.0)
        clipped_frac = float(q.get("clipped_fraction") or 0.0)
        intrusion_score = round(min(1.0, max(0.02, dark_frac * 1.5 + clipped_frac * 1.2 + (0.4 if condition != "NORMAL" else 0.0))), 3)
    return {"cell_id": cell_id, "intrusion_score": intrusion_score, "condition": condition, "snapshot_bytes": snap_bytes}
