#!/usr/bin/env python3
"""Arm & Camera Telemetry Sync for OMX Cell Worker (`cell_camera_telemetry_sync.py`).

Single Responsibility:
  - Gathers camera quality facts from local `commissioning_view` (`:8767`) `state.json`,
  - Gathers `omx_incident` hold status and `chunk-status.jsonl` live arm states (`arm_s`, `arm_a`, `arm_b`),
  - Posts the facts to `/api/fleet/pipeline/cell-quality`.

D-136: camera JPEG bytes are never uploaded. Fleet relays no video; the console reads
frames through Vision preview leases only.
"""
from __future__ import annotations

import json
from pathlib import Path
import ssl
from typing import Any
from urllib.request import Request, urlopen

DEFAULT_PREP_DIR = Path("/home/robttt/rosy-test/omx-record-prep-20261019")
CAMERA_KEYS: tuple[str, ...] = ("top", "side", "arm_a_wrist", "arm_b_wrist", "arm_s_top", "arm_s_wrist")
ARM_SUFFIXES: dict[str, str] = {"arm_s": "s", "arm_a": "a", "arm_b": "b"}


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


def sync_cell_telemetry(fleet_r_url: str, token: str, prep_dir: Path = DEFAULT_PREP_DIR, urlopen_fn: Any = urlopen) -> dict[str, Any]:
    """Post camera-quality facts, arm holds and live arm states to Fleet. No image bytes leave the cell PC."""
    ctx = ssl._create_unverified_context()
    base = fleet_r_url.rstrip("/")
    state_json = _fetch_local_state_json(urlopen_fn)
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
        return qout
    except Exception:
        return {}


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
