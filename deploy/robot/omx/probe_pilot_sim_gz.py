#!/usr/bin/env python3
"""Gazebo Container Spawner, Pairing Reader & Telemetry Helpers for Pilot SIM Probe (`probe_pilot_sim_gz.py`).

Single Responsibility:
  - HTTP JSON request helper (`request`), ROS terminal receipt parser (`terminal_facts`), and joint peak speed
    window estimator (`peak_speeds`).
  - Gazebo dynamic cube spawner (`gz_spawner`) and container pairing-code reader (`pairing_code`).
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess as _std_subprocess
import sys
import time as _std_time
import urllib.error
import urllib.request as _std_urllib_request

REPO = Path(__file__).resolve().parents[3]
BASE = "http://127.0.0.1:8088/api/v1/sim/omx"
WORLD = "omx_pilot_workcell"
CUBE = "rosy_probe_cube"


def _parent_attr(name: str, default):
    mod = sys.modules.get("probe_pilot_sim_http")
    if mod is not None and hasattr(mod, name):
        return getattr(mod, name)
    return default


def request(path: str, *, method: str = "GET", token: str = "", body=None, base: str = BASE):
    ureq = _parent_attr("urllib", None)
    urlopen = getattr(getattr(ureq, "request", None), "urlopen", _std_urllib_request.urlopen)
    Request = getattr(getattr(ureq, "request", None), "Request", _std_urllib_request.Request)
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(base + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as response:
            return json.load(response) if response.status != 204 else None
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{path}: HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc


def terminal_facts(goal: dict) -> dict:
    """ROS terminal status / result code as the SIM receipt reports them."""
    if goal["state"] == "SUCCEEDED":
        return {"status": 4, "result_code": 0}
    match = re.fullmatch(r"terminal_status_(-?\d+)_result_(-?\d+|None)", goal.get("reason", ""))
    if match:
        code = match.group(2)
        return {"status": int(match.group(1)), "result_code": None if code == "None" else int(code)}
    return {"status": None, "result_code": None}


def peak_speeds(samples: list[tuple[float, dict]], window_s: float = 0.5) -> dict[str, float]:
    """Largest |dq/dt| per joint between consecutive readbacks in the last ``window_s``."""
    if not samples:
        return {}
    end = samples[-1][0]
    recent = [sample for sample in samples if end - sample[0] <= window_s]
    peaks: dict[str, float] = {}
    for (t0, q0), (t1, q1) in zip(recent, recent[1:]):
        if t1 <= t0:
            continue
        for name in q1:
            if name in q0:
                peaks[name] = max(peaks.get(name, 0.0), abs(q1[name] - q0[name]) / (t1 - t0))
    return {name: round(value, 4) for name, value in peaks.items()}


def gz_spawner(container: str):
    """Spawn/remove a dynamic cube through the Gazebo transport service (inside the container)."""
    prefix = ([] if container == "--inside" else ["docker", "exec", container]) + [
        "bash",
        "-c",
        'source /opt/ros/jazzy/setup.bash; exec "$@"',
        "gz",
    ]

    def gz(service: str, reqtype: str, req: str) -> None:
        sub = _parent_attr("subprocess", _std_subprocess)
        sub.run(
            [
                *prefix,
                "gz",
                "service",
                "-s",
                f"/world/{WORLD}/{service}",
                "--reqtype",
                reqtype,
                "--reptype",
                "gz.msgs.Boolean",
                "--timeout",
                "3000",
                "--req",
                req,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def spawn(size: float, x: float, y: float, z: float, yaw: float) -> None:
        mass = 0.03
        inertia = mass * size * size / 6
        sdf = (
            f"<sdf version='1.9'><model name='{CUBE}'><pose>{x} {y} {z} 0 0 {yaw}</pose><link name='link'>"
            f"<inertial><mass>{mass}</mass><inertia><ixx>{inertia}</ixx><iyy>{inertia}</iyy>"
            f"<izz>{inertia}</izz></inertia></inertial>"
            f"<collision name='c'><geometry><box><size>{size} {size} {size}</size></box></geometry>"
            f"<surface><friction><ode><mu>1.0</mu><mu2>1.0</mu2></ode></friction></surface></collision>"
            f"<visual name='v'><geometry><box><size>{size} {size} {size}</size></box></geometry></visual>"
            f"</link></model></sdf>"
        )
        gz("create", "gz.msgs.EntityFactory", f'sdf: "{sdf}"')

    def remove() -> None:
        gz("remove", "gz.msgs.Entity", f'name: "{CUBE}" type: MODEL')

    return spawn, remove


def pairing_code(container: str, deadline: float) -> str:
    tmod = _parent_attr("time", _std_time)
    sub = _parent_attr("subprocess", _std_subprocess)
    while tmod.monotonic() < deadline:
        if container == "--inside":
            path = Path("/run/rosy-omx-pilot/pairing-code")
            if path.is_file() and path.read_text(encoding="utf-8").strip():
                return path.read_text(encoding="utf-8").strip()
        else:
            result = sub.run(
                ["docker", "exec", container, "cat", "/run/rosy-omx-pilot/pairing-code"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        tmod.sleep(1)
    raise RuntimeError("pairing code did not appear")
