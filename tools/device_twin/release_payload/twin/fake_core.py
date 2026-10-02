#!/usr/bin/env python3
"""Device-twin stand-in for the CORE node (D-410 twin only; never shipped).

Runs as rosy-core from WorkingDirectory=/opt/rosy/current, like the real CORE:

- serves GET /api/v1 (wait-core-ready.py) and GET /api/v1/openapi.json whose
  info.version names the release this process was started from;
- writes /run/rosy/status-inputs.json (schema 2, the same keys as
  core_api_web/api/v1/host.py) every 10 s;
- reads /run/twin/core-control.json {"mode": ...} before every write:
  idle | moving | manual | battery | stale (stops writing) | estop;
- twin/variant in the release picks a bad build: "never-ready" never listens,
  "crash-after-ready" listens and then exits 1 after 20 s.
"""

from __future__ import annotations

import datetime as dt
import http.server
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

RELEASE_DIR = Path.cwd()
RELEASE_ID = (RELEASE_DIR / "install" / ".rosy-release").read_text(encoding="utf-8").strip()
VARIANT_FILE = RELEASE_DIR / "twin" / "variant"
VARIANT = VARIANT_FILE.read_text(encoding="utf-8").strip() if VARIANT_FILE.is_file() else "good"
PORT = int(os.environ.get("ROSY_API_PORT", "8080"))
STATUS = Path("/run/rosy/status-inputs.json")
CONTROL = Path("/run/twin/core-control.json")
WRITE_EVERY_S = 10.0
CRASH_AFTER_S = 20.0


def _mode() -> str:
    try:
        return str(json.loads(CONTROL.read_text(encoding="utf-8")).get("mode", "idle"))
    except (OSError, ValueError, AttributeError):
        return "idle"


def status_inputs(mode: str) -> dict:
    data = {
        "schema": 2, "written_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "battery_warning_percent": 20.0, "devices": [],
        "robot_mode": "IDLE", "nav_state": "IDLE", "swarm_role": None,
        "velocity_linear": 0.0, "velocity_angular": 0.0,
        "battery_percent": 87.0, "battery_charging": False,
        "docking_state": "UNDOCKED", "line_follow_mode": "OFF", "line_follow_state": "OFF",
        "swarm_active": False, "estop": False, "activity_kind": None,
        "twin": {"release_id": RELEASE_ID, "pid": os.getpid(), "mode": mode},
    }
    if mode == "moving":
        data.update(robot_mode="NAVIGATING", nav_state="ACTIVE", velocity_linear=0.12, velocity_angular=0.05)
    elif mode == "manual":
        data.update(robot_mode="MANUAL", velocity_linear=0.08)
    elif mode == "battery":
        data.update(battery_percent=22.0, battery_charging=False)
    elif mode == "estop":
        data.update(estop=True)
    return data


def _write(data: dict) -> None:
    temporary = STATUS.with_name(f".{STATUS.name}.tmp")
    temporary.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, STATUS)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # journald stays quiet
        pass

    def _json(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/api/v1":
            self._json(200, {"ok": True, "release_id": RELEASE_ID, "pid": os.getpid()})
        elif self.path == "/api/v1/openapi.json":
            self._json(200, {"openapi": "3.1.0", "info": {"title": "ROSY CORE (device twin)",
                                                          "version": f"twin-{RELEASE_ID}"}})
        else:
            self._json(404, {"error": "not found"})


def main() -> int:
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    print(f"twin CORE {RELEASE_ID} variant={VARIANT} pid={os.getpid()} cwd={os.getcwd()}", flush=True)
    if VARIANT != "never-ready":
        server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    started = time.monotonic()
    while not stop.is_set():
        mode = _mode()
        if mode != "stale":
            try:
                _write(status_inputs(mode))
            except OSError as exc:
                print(f"status-inputs write failed: {exc}", file=sys.stderr, flush=True)
        if VARIANT == "crash-after-ready" and time.monotonic() - started >= CRASH_AFTER_S:
            print("twin CORE crash-after-ready: exiting 1", file=sys.stderr, flush=True)
            return 1
        stop.wait(WRITE_EVERY_S if VARIANT != "crash-after-ready" else 2.0)
    print("twin CORE stopping", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
