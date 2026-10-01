"""Gazebo-side helpers for probe_cell_transfer.py (Rosy Cell C3, simulation only)."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
from pathlib import Path


def refuse_second_owner() -> None:
    mine = {os.getpid(), os.getppid()}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) in mine:
            continue
        try:
            argv = (proc / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        cmd = b" ".join(argv).decode(errors="ignore")
        if b"python" in argv[0] and ("pilot_sim_server" in cmd or "probe_cell_transfer" in cmd):
            raise RuntimeError(f"another arm owner process is running (pid {proc.name}): {cmd[:80]}")


def model_pose(name: str, attempts: int = 5) -> dict:
    # `gz model -p` sometimes prints nothing under load (its service request times out); retry.
    for _ in range(attempts):
        out = subprocess.run(["gz", "model", "-m", name, "-p"], capture_output=True, text=True,
                             timeout=60).stdout
        triples = [g.split() for g in re.findall(r"\[([^\]]+)\]", out)]
        triples = [[float(v) for v in t] for t in triples if len(t) == 3]
        if len(triples) >= 2:
            break
        time.sleep(1.0)
    else:
        raise RuntimeError(f"gz model pose for {name} not found after {attempts} attempts")
    (x, y, z), (roll, pitch, yaw) = triples[-2], triples[-1]
    return {"x": x, "y": y, "z": z, "roll": roll, "pitch": pitch, "yaw": yaw}


def sim_aid(action: str) -> dict:
    """Command the world's labelled DetachableJoint SIM AID and wait for its state echo.

    A one-shot `gz topic -p` was lost before discovery (run12: the block stayed attached
    through homing), so publish through gz-transport after the subscriber connects.
    """
    from gz.msgs10.empty_pb2 import Empty
    from gz.msgs10.stringmsg_pb2 import StringMsg
    from gz.transport13 import Node as GzNode

    node = GzNode()
    states: list[str] = []
    node.subscribe(StringMsg, "/c3_sim_aid/state", lambda msg: states.append(msg.data))
    publisher = node.advertise(f"/c3_sim_aid/{action}", Empty)
    deadline = time.monotonic() + 15.0
    while not publisher.has_connections() and time.monotonic() < deadline:
        time.sleep(0.1)
    sent = time.time()
    want = "attached" if action == "attach" else "detached"
    # Repeat until the plugin echoes the state: one publish was lost even when connected (run15).
    while want not in states and time.monotonic() < deadline:
        publisher.publish(Empty())
        time.sleep(0.5)
    return {"command": action, "sent_wall": sent, "connected": publisher.has_connections(),
            "state_echo": states[-1] if states else None, "confirmed": want in states}


def sha256_lf(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
