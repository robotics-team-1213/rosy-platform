"""Execution, TLS, hold-gating, and error diagnostics helpers for `cell_task_worker.py`."""
from __future__ import annotations

import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
from typing import Any
from urllib.error import HTTPError
from urllib.request import urlopen


def make_ca_urlopen(ca_file: str | Path | None = None):
    """Return a `urlopen`-compatible callable pinned to `ca_file` when provided."""
    if not ca_file:
        return urlopen
    ctx = ssl.create_default_context(cafile=str(Path(ca_file).expanduser()))

    def _open(req, **kwargs):
        return urlopen(req, context=ctx, **kwargs)

    return _open


def resolve_task_arm(task: dict[str, Any]) -> str:
    """Resolve the target OMX arm id for a queued Fleet cell task."""
    arm = str(task.get("arm_id") or "").strip()
    if arm:
        return arm
    return "arm_s" if task.get("cell_id") == "cell_s" else "arm_b"


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


def _arm_run_spec(arm_id: str, prep_dir: Path) -> tuple[Path, Path, Path, tuple[int, int, int, int], str]:
    specs = {
        "arm_b": ("with-session-arm-b-par.sh", "cell-arm-b-stack.json", "object-catalog-orange.json", (10, 340, 230, 478), "temp_plate_b"),
        "arm_a": ("with-session-arm-a-par.sh", "cell-arm-a-stack.json", "object-catalog-orange.json", (395, 360, 625, 478), "temp_plate_a"),
        "arm_s": ("with-session-arm-s-live.sh", "cell-auto-arm-s-live.json", "catalog-board-live-1113.json", (90, 150, 560, 450), "pinky"),
    }
    if arm_id not in specs:
        raise ValueError(f"unsupported arm_id for guarded pick: {arm_id!r}")
    wrapper, cfg, cat, roi, default_src = specs[arm_id]
    return prep_dir / wrapper, prep_dir / cfg, prep_dir / cat, roi, default_src


def execute_guarded_cell_task(handoff: dict[str, Any], *, prep_dir: Path) -> dict[str, Any]:
    """Execute one Fleet cell handoff via the arm's session wrapper and `cell_auto_pick.py`."""
    arm_id = resolve_task_arm(handoff)
    hold = check_arm_hold(arm_id)
    if hold.get("held"):
        return {"arm": arm_id, "error": f"ARM_INCIDENT_HELD:{hold.get('reason')}",
                "stop_event": {"command": "stop", "ok": False, "folded": False}}
    wrapper, cfg, cat, default_roi, default_src = _arm_run_spec(arm_id, prep_dir)
    if not wrapper.is_file() or not cfg.is_file():
        return {"arm": arm_id, "error": "CELL_CONFIG_OR_WRAPPER_MISSING",
                "stop_event": {"command": "stop", "ok": False, "folded": False}}
    cfg_data = json.loads(cfg.read_text(encoding="utf-8"))
    src = str(handoff.get("src_site") or default_src)
    dst = str(handoff.get("dst_site") or ("pallet-l0" if arm_id != "arm_s" else "belt"))
    src_site = src.rsplit("-l", 1)[0]
    roi = (cfg_data.get("sites") or {}).get(src_site, {}).get("auto_roi") or default_roi
    omx_dir = Path(__file__).resolve().parent
    cmd = [
        str(wrapper),
        sys.executable,
        str(omx_dir / "cell_auto_pick.py"),
        "--config", str(cfg),
        "--catalog", str(cat if cat.is_file() else omx_dir / "object-catalog.example.json"),
        "--roi", *(str(int(v)) for v in roi),
        "--from", src,
        "--dest", dst,
        "--commissioning",
        "--person-at-switch",
        "--task-id", str(handoff.get("task_id") or ""),
        "--handoff-lease-id", str(handoff.get("handoff_lease_id") or ""),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    parsed: dict[str, Any] = {}
    for line in reversed(proc.stdout.splitlines()):
        s = line.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                parsed = json.loads(s)
                break
            except ValueError:
                pass
    placed = proc.returncode == 0 and parsed.get("result") == "placed"
    tier = handoff.get("tier")
    dst_area = dst.rsplit("-l", 1)[0]
    stage_result = {
        "handoff_lease_id": handoff.get("handoff_lease_id"),
        "directive_id": handoff.get("task_id"),
        "arm_id": arm_id,
        "task_verified": placed,
        "place": {"area": dst_area, **({"tier": tier} if isinstance(tier, int) else {})},
        "verification": {
            "verified": placed,
            "basis": "predefined_side_and_top_target_zones",
            "z_gate": {"verdict": "PASS" if placed else "FAIL"},
        },
        "raw": parsed,
    }
    return {
        "arm": arm_id,
        "events_count": len(parsed.get("attempts") or []),
        "stage_result": stage_result,
        "stop_event": {"command": "stop", "ok": placed, "folded": placed},
        **({} if placed else {"error": parsed.get("result") or f"exit_{proc.returncode}"}),
    }
