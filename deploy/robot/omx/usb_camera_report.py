"""D-963: tell Fleet which plugged USB cameras have no role, and keep the role its operator decided.

The observation bridge calls `cycle` every ~20 s. Read-only on the camera registry: the only file written is the
decisions file ({key: role}) that `omx_cameras.py bind --apply` reads, so the registry keeps one writer. A key is a
hash of the camera's persistent name; no device path leaves this PC.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import omx_cameras  # noqa: E402
import omx_devices  # noqa: E402
from core_common.protocol.workcell_observations import UsbCameraReport  # noqa: E402

ROLE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}")
USB_ID = re.compile(r"[0-9a-f]{4}:[0-9a-f]{4}")


def build_report(workcell_id, registry, facts, names, present=os.path.exists) -> UsbCameraReport:
    roles = lambda found: [r for r in found if isinstance(r, str) and ROLE.fullmatch(r)][:32]  # noqa: E731
    rows = [r for r in omx_cameras.propose(registry, facts, names, present)
            if not r["follow"] and USB_ID.fullmatch(r["usb_id"])]  # a `follow` camera is moved by bind itself
    return UsbCameraReport(workcell_id=workcell_id, roles=roles(c["role"] for c in registry["cameras"]), candidates=[
        {"key": omx_cameras.device_key(r["device"]), "usb_id": r["usb_id"], "roles": roles(r["roles"]),
         "suggest": (roles([r.get("suggest")]) or [None])[0], "hub_arm": (roles([r.get("hub_arm")]) or [None])[0]}
        for r in rows[:16]])


def store_decisions(decisions, path: Path) -> None:
    """Replace the decisions file with Fleet's current answer (atomic; unchanged content is not rewritten)."""
    wanted = {d.key: d.role for d in decisions.decisions}
    try:
        if json.loads(path.read_text(encoding="utf-8")) == wanted:
            return
    except (OSError, ValueError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(wanted), encoding="utf-8")
    os.replace(tmp, path)


def cycle(post, workcell_id, *, registry_path=omx_cameras.REGISTRY, decisions_path=omx_cameras.DECISIONS,
          facts=omx_devices.video_facts, names=omx_cameras._names) -> None:
    """One report: `post(report)` returns Fleet's UsbCameraDecisions. No registry yet means nothing to report."""
    if registry_path.exists():
        store_decisions(post(build_report(workcell_id, omx_cameras.load(registry_path), facts(), names())),
                        decisions_path)
