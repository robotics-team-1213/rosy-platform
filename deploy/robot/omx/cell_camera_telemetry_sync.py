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

import hashlib
import inspect
import json
import os
from pathlib import Path
import ssl
import time
from typing import Any
from urllib.request import Request, urlopen

DEFAULT_PREP_DIR = Path("/home/robttt/rosy-test/omx-record-prep-20261019")
CAMERA_KEYS: tuple[str, ...] = ("top", "side", "arm_a_wrist", "arm_b_wrist", "arm_s_top", "arm_s_wrist")
ARM_SUFFIXES: dict[str, str] = {"arm_s": "s", "arm_a": "a", "arm_b": "b"}
SHADOW_TAIL = 200
AUTO_EVENT_TAIL = 30
BLOCK_REASON = "학습 정책 실물 실행은 사용자 승인 전(D-1024 L3 arm_b 한정, cell_executor 승인 목록 ik_chunk)"


def _fetch_local_state_json(urlopen_fn: Any = urlopen) -> dict[str, Any]:
    try:
        sreq = Request("http://127.0.0.1:8767/state.json", headers={"Host": "127.0.0.1:8767"})
        with urlopen_fn(sreq, timeout=1.5) as sresp:
            data = json.load(sresp)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _collect_live_arm_states(prep_dir: Path) -> dict[str, Any]:
    arm_states: dict[str, Any] = {}
    for arm_id, suffix in ARM_SUFFIXES.items():
        for io_name in (f"chunk-io-{suffix}", f"chunk-io-{suffix}-r2s"):
            st_file = prep_dir / io_name / "chunk-status.jsonl"
            if st_file.is_file():
                try:
                    lines = [l.strip() for l in st_file.read_text(errors="replace").splitlines()[-25:] if l.strip().startswith("{")]
                    for raw_line in reversed(lines):
                        ev = json.loads(raw_line)
                        st_arr = ev.get("state")
                        if isinstance(st_arr, list) and len(st_arr) >= 6:
                            health = ev.get("health") or {}
                            temps = health.get("temp_c") or []
                            curs = health.get("current_ma") or []
                            arm_states[arm_id] = {
                                "joints_deg": [round(float(x), 1) for x in st_arr[:6]],
                                "folded": bool(ev.get("folded", float(st_arr[1]) <= -50.0 and float(st_arr[2]) >= 45.0)),
                                "temp_c": round(float(max(temps)), 1) if temps else None,
                                "current_ma": round(float(max(curs)), 1) if curs else None,
                                "updated_at": round(st_file.stat().st_mtime, 3),
                                "source": "chunk_status_live",
                            }
                            break
                except Exception:
                    pass
            if arm_id in arm_states:
                break
    return arm_states


def _collect_arm_models(prep_dir: Path) -> dict[str, Any]:
    """Per arm: the pinned shadow model and a summary of its proposals, {} without one. Never an execution grant."""
    models: dict[str, Any] = {arm_id: {} for arm_id in ARM_SUFFIXES}
    for arm_id, suffix in ARM_SUFFIXES.items():
        for path in sorted(prep_dir.glob(f"cell-auto-arm-{suffix}-*.json")):
            try:
                config = json.loads(path.read_text(encoding="utf-8"))
                spec = config.get("act_shadow")
                if not isinstance(spec, dict) or not spec.get("policy_root"):
                    continue
                root = Path(str(spec["policy_root"])).expanduser()
                warp = root / "cam_warp.json"
                entry: dict[str, Any] = {
                    "name": root.name, "policy_revision": spec.get("policy_revision"), "kind": "shadow",
                    "binding": spec.get("kind") or "act_inference", "config": path.name,
                    "warp_sha256": hashlib.sha256(warp.read_bytes()).hexdigest() if warp.is_file() else None,
                    "execution_allowed": False, "block_reason": BLOCK_REASON,
                    "shadow": {"rows": 0, "errors": 0, "last_at": None, "last_ik_outcome": None, "last_error": None},
                }
                log = Path(str(config.get("work_dir") or path.parent)).expanduser() / "act-shadow.jsonl"
                if log.is_file():
                    rows = [json.loads(line) for line in log.read_text(errors="replace").splitlines()[-SHADOW_TAIL:]
                            if line.strip().startswith("{")]
                    rows = [r for r in rows if r.get("policy_id") == spec.get("policy_revision")]
                    errors = [r for r in rows if r.get("error")]
                    last = rows[-1] if rows else {}
                    entry["shadow"] = {
                        "rows": len(rows), "errors": len(errors),
                        "last_at": round(log.stat().st_mtime, 3) if rows else None,
                        "last_ik_outcome": (last.get("ik") or {}).get("outcome"),
                        "last_error": str(errors[-1]["error"])[:120] if errors else None,
                    }
                models[arm_id] = entry
                break
            except Exception:
                continue
    return models


def _collect_auto_events(prep_dir: Path) -> list[dict[str, Any]]:
    try:
        lines = (prep_dir / "incidents" / "auto-events.jsonl").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-AUTO_EVENT_TAIL:]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _read_ack_map(ack_file: Path) -> dict[str, dict[str, Any]]:
    if not ack_file.is_file():
        return {}
    raw = json.loads(ack_file.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    return {}


def _write_ack_map_atomic(ack_file: Path, ack_map: dict[str, dict[str, Any]]) -> None:
    if not ack_map:
        if ack_file.exists():
            ack_file.unlink()
        return
    ack_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = ack_file.with_name(f"{ack_file.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(ack_map), encoding="utf-8")
    os.replace(tmp, ack_file)


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
        ctx = ssl.create_default_context(cafile=str(Path(ca_file).expanduser())) if ca_file else (
            ssl.create_default_context() if (verified and is_https) else ssl._create_unverified_context()
        )
        state_json = _fetch_local_state_json(urlopen_fn)
        ack_map = _read_ack_map(ack_file)
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
            "auto_events": _collect_auto_events(prep_dir),
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
                req_res_file = prep_dir / "incidents" / f"auto-fold-req-{req_id}.result.json"
                if not req_res_file.is_file():
                    try:
                        import omx_incident_fleet  # type: ignore
                        alt_res = Path(omx_incident_fleet.INCIDENTS) / f"auto-fold-req-{req_id}.result.json"
                        if alt_res.is_file():
                            req_res_file = alt_res
                    except Exception:
                        pass
                if req_res_file.is_file():
                    try:
                        res_obj = json.loads(req_res_file.read_text(encoding="utf-8"))
                        next_acks[req_id] = {
                            "arm_id": str(arm_id), "request_id": req_id,
                            "outcome": str(res_obj.get("outcome") or "completed"),
                            **({"detail": res_obj.get("detail")} if res_obj.get("detail") else {}),
                        }
                        continue
                    except Exception:
                        pass
                if req_id in next_acks or spec.get("started"):
                    continue
                exp = spec.get("expires_at")
                if isinstance(exp, (int, float)) and not isinstance(exp, bool) and now_t > float(exp):
                    next_acks[req_id] = {"arm_id": str(arm_id), "request_id": req_id,
                                         "outcome": "skipped", "detail": "SAFE_HOME_EXPIRED"}
                    continue
                next_acks[req_id] = {"arm_id": str(arm_id), "request_id": req_id, "outcome": "in_flight"}
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
                        }.items() if has_varkw or k in params}
                        res = fold_fn(str(arm_id), **kw)
                    else:
                        res = fold_fn(str(arm_id))
                    started = isinstance(res, dict) and bool(res.get("started"))
                    explicit = res.get("outcome") if isinstance(res, dict) else None
                    next_acks[req_id] = {
                        "arm_id": str(arm_id), "request_id": req_id,
                        "outcome": str(explicit) if explicit else ("started" if started else "skipped"),
                        **({"detail": str((res or {}).get("why") or (res or {}).get("reason") or "not_started")[:120]} if not started else {}),
                    }
                except Exception as exc:
                    next_acks[req_id] = {
                        "arm_id": str(arm_id), "request_id": req_id, "outcome": "failed", "detail": str(exc)[:120],
                    }
        _write_ack_map_atomic(ack_file, next_acks)
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
