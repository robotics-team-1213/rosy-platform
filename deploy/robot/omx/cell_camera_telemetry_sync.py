#!/usr/bin/env python3
"""Parallel Camera Frame & Arm Telemetry Sync for OMX Cell Worker (`cell_camera_telemetry_sync.py`).

Single Responsibility:
  - Concurrently fetches live camera JPEGs (`top`, `side`, `arm_a_wrist`, `arm_b_wrist`, `arm_s_top`, `arm_s_wrist`)
    and `/state.json` from local `commissioning_view` (`:8767`) with disk fallback,
  - Gathers `omx_incident` hold status and `chunk-status.jsonl` live arm states (`arm_s`, `arm_a`, `arm_b`),
  - Uploads all camera frames and `/api/fleet/pipeline/cell-quality` to Fleet-R in parallel.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import ssl
from typing import Any
from urllib.request import Request, urlopen

DEFAULT_PREP_DIR = Path("/home/robttt/rosy-test/omx-record-prep-20261019")
CAMERA_KEYS: tuple[str, ...] = ("top", "side", "arm_a_wrist", "arm_b_wrist", "arm_s_top", "arm_s_wrist")
ARM_SUFFIXES: dict[str, str] = {"arm_s": "s", "arm_a": "a", "arm_b": "b"}


def _fetch_local_cam_jpeg(cam: str, urlopen_fn: Any = urlopen) -> tuple[str, bytes] | None:
    try:
        req = Request(f"http://127.0.0.1:8767/frame/{cam}.jpg", headers={"Host": "127.0.0.1:8767"})
        with urlopen_fn(req, timeout=1.5) as resp:
            raw = resp.read()
            if len(raw) > 1000:
                return cam, raw
    except Exception:
        pass
    return None


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


def upload_latest_camera_snapshots(fleet_r_url: str, token: str, prep_dir: Path = DEFAULT_PREP_DIR, urlopen_fn: Any = urlopen) -> dict[str, int]:
    """Fetch local camera JPEGs + state.json in parallel, then upload frames + cell-quality to Fleet-R in parallel."""
    ctx = ssl._create_unverified_context()
    base = fleet_r_url.rstrip("/")
    live_frames: dict[str, bytes] = {}
    with ThreadPoolExecutor(max_workers=7) as local_pool:
        state_fut = local_pool.submit(_fetch_local_state_json, urlopen_fn)
        for res in local_pool.map(lambda c: _fetch_local_cam_jpeg(c, urlopen_fn), CAMERA_KEYS):
            if res is not None:
                live_frames[res[0]] = res[1]
        state_json = state_fut.result()

    if not live_frames:
        jpg_paths: list[Path] = list(Path("/tmp").glob("*.jpg"))
        if prep_dir.is_dir():
            for sub in prep_dir.glob("live-*"):
                if sub.is_dir():
                    jpg_paths.extend(sub.glob("*.jpg"))
        candidates = sorted(
            [p for p in jpg_paths if p.is_file() and p.stat().st_size > 1000],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        top_img = next((p for p in candidates if "top" in p.name), candidates[0] if candidates else None)
        wrist_img = next((p for p in candidates if "wrist" in p.name), top_img)
        if top_img is not None:
            live_frames["cell_s"] = top_img.read_bytes()
            live_frames["pinky"] = live_frames["cell_s"]
        if wrist_img is not None:
            live_frames["cell_ab"] = wrist_img.read_bytes()

    if "arm_s_top" in live_frames:
        live_frames["cell_s"] = live_frames["arm_s_top"]
    elif "top" in live_frames:
        live_frames["cell_s"] = live_frames["top"]
    if "top" in live_frames:
        live_frames["cell_ab"] = live_frames["top"]
    if "side" in live_frames:
        live_frames["pinky"] = live_frames["side"]
    elif "arm_s_top" in live_frames:
        live_frames["pinky"] = live_frames["arm_s_top"]

    if not live_frames:
        return {}

    def _upload_one(item: tuple[str, bytes]) -> tuple[str, int] | None:
        view_id, raw = item
        try:
            req = Request(
                f"{base}/api/fleet/pipeline/cell-camera/{view_id}",
                data=raw,
                method="POST",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "image/jpeg"},
            )
            with urlopen_fn(req, context=ctx, timeout=8):
                return view_id, len(raw)
        except Exception:
            return None

    def _sync_quality() -> None:
        try:
            cams_quality: dict[str, Any] = {}
            for cam in CAMERA_KEYS:
                entry = state_json.get(cam) or (state_json.get("cameras") or {}).get(cam)
                if isinstance(entry, dict):
                    cams_quality[cam] = {
                        "fresh": bool(entry.get("fresh", True)),
                        "sequence": entry.get("sequence"),
                        "receipt_age_s": entry.get("receipt_age_s"),
                        "quality": entry.get("quality") or {},
                    }
            arm_holds: dict[str, Any] = {}
            try:
                import omx_incident  # type: ignore
                for arm_id in ("arm_s", "arm_a", "arm_b"):
                    arm_holds[arm_id] = omx_incident.status(arm_id)
            except Exception:
                pass
            arm_states = _collect_live_arm_states(prep_dir)
            qreq = Request(
                f"{base}/api/fleet/pipeline/cell-quality",
                data=json.dumps({"schema": "rosy.pipeline.cell-quality.v1", "cameras": cams_quality, "arm_holds": arm_holds, "arm_states": arm_states}).encode("utf-8"),
                method="POST",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            with urlopen_fn(qreq, context=ctx, timeout=6) as qresp:
                qout = json.load(qresp)
            for arm_id, note in (qout.get("pending_clear_arms") or {}).items():
                try:
                    import omx_incident  # type: ignore
                    omx_incident.clear(str(arm_id), str(note))
                except Exception:
                    pass
        except Exception:
            pass

    uploaded: dict[str, int] = {}
    items = list(live_frames.items())
    with ThreadPoolExecutor(max_workers=min(10, len(items) + 1)) as pool:
        q_fut = pool.submit(_sync_quality)
        for res in pool.map(_upload_one, items):
            if res is not None:
                uploaded[res[0]] = res[1]
        q_fut.result()
    return uploaded


def inspect_camera_frame_telemetry(prep_dir: Path = DEFAULT_PREP_DIR, cell_id: str = "cell_s") -> dict[str, Any]:
    """Compute camera frame telemetry (size, photometric intrusion_score) from :8767/state.json or latest snapshot."""
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
