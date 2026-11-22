#!/usr/bin/env python3
"""Re-measure navigation approval on the robot after a release change, then start Nav2 (D-986 addendum 2026-11-20).

Runs from rosy-nav-reapprove.timer as root. One run acts only when all hold:

1. this robot was approved before and the only reason the approval fails now is that it was
   measured on another release (mapping_approval.check);
2. no /etc/rosy/nav-reapprove.disabled, no live /run/rosy-claim (an update or another job);
3. CORE's approval flow is IDLE, the robot is IDLE and still in two samples 10 s apart, the
   battery reading is fresh and ok, and CORE reads charging as false;
4. fewer than MAX_ATTEMPTS tries on this release.

Then, with a 5-minute operator token from rosy-login-code paired on loopback: begin, the five
D-986 trials in an order that makes rear room before the reverse one (CORE still checks LiDAR
clearance before each), seal, navigation-start, logout. Any failure cancels the measurement.
The first approval of a robot stays with a person: no marker, no run.

    navigation_reapprove.py run
    navigation_reapprove.py status
"""
from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import re
import ssl
import stat
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import mapping_approval  # noqa: E402
import rosy_claim  # noqa: E402

STATE = Path("/var/lib/rosy/nav-reapprove/state.json")
DISABLED = Path("/etc/rosy/nav-reapprove.disabled")
MAX_ATTEMPTS = 2
CARRY_FAILURE = "differs from the active release"
# Forward first: a robot parked against a wall behind gains rear room before reverse (y8xs 2026-11-20:
# 0.12 m behind, 0.13 m needed, then 0.185 m after the forward trials).
TRIALS = (("forward", "button_release", 0.70), ("cw", "button_release", 0.70),
          ("ccw", "button_release", 0.70), ("forward", "command_loss", 0.50),
          ("reverse", "button_release", 0.70))
HOLD_EVERY_S = 0.08
CODE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b")


def approval_needs_remeasure(root: Path = Path("/")) -> str | None:
    """None when the approval failed only because of a release change; else why not to act."""
    try:
        mapping_approval.check(root)
    except ValueError as exc:
        return None if CARRY_FAILURE in str(exc) else f"approval: {exc}"
    return "approved"


_NAV_IDLE = frozenset({"IDLE", "ARRIVED", "CANCELED", "FAILED"})
_DOCKING_IDLE = frozenset({"UNDOCKED", "DOCKED", "CHARGING"})
_MAX_STATUS_INPUTS_BYTES = 16 * 1024


def decide(approval: dict, robot: dict, still: dict, health: dict, attempts: int) -> str:
    """'run' or the reason to skip; pure so the tests pin every gate."""
    if approval.get("phase") != "IDLE":
        return f"approval phase {approval.get('phase')}"
    if (approval.get("approval") or {}).get("valid"):
        return "approved"
    for sample in (robot, still):
        velocity = sample.get("velocity") or {}
        if sample.get("mode") != "IDLE":
            return f"robot mode {sample.get('mode')}"
        nav = sample.get("navigation")
        if nav is not None and nav not in _NAV_IDLE:
            return f"navigation {nav}"
        if sample.get("trip_lease") is not None:
            return "trip lease active"
        line_follow = sample.get("line_follow") or {}
        if line_follow.get("mode") not in (None, "OFF") or line_follow.get("state") not in (None, "OFF"):
            return "line follow active"
        dock = (sample.get("docking") or {}).get("state")
        if dock is not None and dock not in _DOCKING_IDLE:
            return f"docking {dock}"
        swarm = sample.get("swarm") or {}
        if swarm.get("active") is True or swarm.get("role") not in (None, "none"):
            return "swarm active"
        if sample.get("activity") is not None:
            return "activity active"
        if (sample.get("safety") or {}).get("estop") is True:
            return "estop engaged"
        if abs(velocity.get("linear", 1.0)) > 1e-3 or abs(velocity.get("angular", 1.0)) > 1e-3:
            return "robot moving"
    battery = health.get("battery") or {}
    if battery.get("evidence") != "fresh" or battery.get("level") != "ok":
        return f"battery {battery.get('evidence')}/{battery.get('level')}"
    if (still.get("battery_status") or {}).get("charging") is not False:
        return "charging not confirmed false"
    if attempts >= MAX_ATTEMPTS:
        return f"gave up after {attempts} attempts on this release"
    return "run"


def _status_inputs_busy(root: Path) -> str | None:
    """Fail-closed check of CORE's local status-inputs handover before pairing."""
    path = root / "run/rosy/status-inputs.json"
    if path.is_symlink():
        return "status-inputs unreadable"
    if not path.exists():
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_STATUS_INPUTS_BYTES:
                return "status-inputs unreadable"
            raw = os.read(fd, _MAX_STATUS_INPUTS_BYTES + 1)
        finally:
            os.close(fd)
        if len(raw) > _MAX_STATUS_INPUTS_BYTES:
            return "status-inputs unreadable"
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return "status-inputs unreadable"
    if not isinstance(data, dict):
        return "status-inputs unreadable"
    if data.get("robot_mode") != "IDLE":
        return f"robot mode {data.get('robot_mode')}"
    if data.get("nav_state") not in _NAV_IDLE:
        return f"navigation {data.get('nav_state')}"
    if "trip_lease_active" in data and data["trip_lease_active"] is not False:
        return "trip lease active"
    if "calibration_active" in data and data["calibration_active"] is not False:
        return "calibration active"
    if (("line_follow_mode" in data and data["line_follow_mode"] != "OFF")
            or ("line_follow_state" in data and data["line_follow_state"] != "OFF")):
        return "line follow active"
    if data.get("docking_state") not in (None, *_DOCKING_IDLE):
        return f"docking {data.get('docking_state')}"
    if (("swarm_active" in data and data["swarm_active"] is not False)
            or data.get("swarm_role") not in (None, "none")):
        return "swarm active"
    if data.get("activity_kind") is not None:
        return "activity active"
    if "estop" in data and data["estop"] is not False:
        return "estop engaged"
    if "velocity_linear" in data or "velocity_angular" in data:
        lin, ang = data.get("velocity_linear", 0.0), data.get("velocity_angular", 0.0)
        ok = (isinstance(lin, (int, float)) and not isinstance(lin, bool) and math.isfinite(lin)
              and isinstance(ang, (int, float)) and not isinstance(ang, bool) and math.isfinite(ang))
        if not ok or abs(lin) >= 0.01 or abs(ang) >= 0.02:
            return "robot moving"
    return None


class Core:
    """CORE on loopback. TLS robots serve https with a site certificate; loopback needs no name check."""

    def __init__(self, port: int = 8080, token: str | None = None):
        self.port, self.token = port, token
        self.tls = True
        self._tls_confirmed = False

    def req(self, method: str, path: str, body=None, timeout: float = 15.0):
        for attempt in range(3):
            used_tls = self.tls
            conn = (http.client.HTTPSConnection("127.0.0.1", self.port, timeout=timeout,
                                                context=ssl._create_unverified_context())
                    if used_tls else http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout))
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            data = None
            if body is not None:
                headers["Content-Type"] = "application/json"
                data = json.dumps(body).encode()
            try:
                conn.request(method, path, body=data, headers=headers)
                response = conn.getresponse()
                if used_tls:
                    self._tls_confirmed = True
                raw = response.read().decode("utf-8", "replace")
                try:
                    return response.status, (json.loads(raw) if raw else None)
                except json.JSONDecodeError:
                    return response.status, raw
            except ssl.SSLError:
                # Only fall back to plain HTTP before TLS has ever worked; restart EOFs keep TLS.
                if used_tls and not self._tls_confirmed:
                    self.tls = False  # a plain-HTTP robot
                elif attempt == 2:
                    raise
                else:
                    time.sleep(2.0)  # begin and seal restart CORE
            except (OSError, http.client.HTTPException):
                if attempt == 2:
                    raise
                time.sleep(2.0)  # begin and seal restart CORE
            finally:
                conn.close()
        raise OSError("CORE did not answer")

    def get(self, path: str) -> dict:
        status, data = self.req("GET", path)
        if status != 200 or not isinstance(data, dict):
            raise RuntimeError(f"GET {path}: {status}")
        return data

    def post(self, path: str, body=None, ok=(200, 201, 202, 204)):
        status, data = self.req("POST", path, body)
        if status not in ok:
            raise RuntimeError(f"POST {path}: {status} {data}")
        return data


def pair(core: Core, runner=subprocess.run) -> str:
    if hasattr(core, "req"):
        # Confirm CORE answers before issuing a one-use login code to the LCD/boot console.
        core.req("GET", "/api/v1/navigation/approval")
    out = runner(["/usr/bin/python3", "-I", "-B", str(HERE / "rosy-login-code.py"),
                  "--role", "operator", "--minutes", "5"], capture_output=True, text=True, timeout=30)
    match = CODE.search(out.stdout or "")
    if out.returncode != 0 or match is None:
        raise RuntimeError("rosy-login-code issued no code")
    data = core.post("/api/v1/auth/pair", {"code": match.group(1), "label": "nav-reapprove"})
    return data["token"]


def wait_for(check, timeout_s: float, what: str, sleep=None, clock=None):
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    end = clock() + timeout_s
    while clock() < end:
        try:
            found = check()
            if found:
                return found
        except (OSError, RuntimeError, http.client.HTTPException):
            pass
        sleep(1.0)
    raise RuntimeError(f"timed out waiting for {what}")


def _phase_in(core: Core, phases: tuple[str, ...]):
    data = core.get("/api/v1/navigation/approval")
    return data if data.get("phase") in phases else None


def _settled(core: Core):
    data = core.get("/api/v1/navigation/approval")
    return data if (data.get("trial") or {}).get("active") is None else None


def run_trial(core: Core, direction: str, cause: str, hold_s: float) -> dict:
    core.post("/api/v1/navigation/approval/trial/start",
              {"direction": direction, "stop_cause": cause, "test_surface": "floor"})
    end = time.monotonic() + hold_s
    while time.monotonic() < end:
        core.post("/api/v1/navigation/approval/trial/hold")
        time.sleep(HOLD_EVERY_S)
    if cause == "button_release":
        core.post("/api/v1/navigation/approval/trial/stop")
    state = wait_for(lambda: _settled(core), 10, f"trial {direction}/{cause} to settle")
    row = next((r for r in state.get("trials", []) if r["direction"] == direction and r["stop_cause"] == cause), {})
    if row.get("state") != "valid":
        raise RuntimeError(f"trial {direction}/{cause}: {row.get('state')} {row.get('reason')}")
    return row


def _battery_ready_for_trial(robot: dict, health: dict) -> bool:
    """Match CORE's _require_unplugged check plus fresh power-health evidence after begin()."""
    status = robot.get("battery_status") or {}
    battery = health.get("battery") or {}
    return (status.get("charging") is False
            and status.get("filtered_voltage") is not None
            and battery.get("evidence") == "fresh"
            and battery.get("level") == "ok")


def reapprove(core: Core, log) -> None:
    core.post("/api/v1/navigation/approval/begin")
    phase = wait_for(lambda: _phase_in(core, ("MEASURING", "FAILED")), 120, "MEASURING")
    if phase.get("phase") != "MEASURING":
        raise RuntimeError(f"begin failed: {phase.get('reason')}")
    # begin restarts CORE; wait for fresh unplugged voltage so trial/start does not 409 CHARGING_UNKNOWN.
    wait_for(lambda: _battery_ready_for_trial(core.get("/api/v1/robot/state"),
                                              core.get("/api/v1/power/health")),
             60, "fresh unplugged battery after begin")
    for direction, cause, hold_s in TRIALS:
        for attempt in (1, 2):
            try:
                row = run_trial(core, direction, cause, hold_s)
                log(f"trial {direction}/{cause} valid, stop {row.get('stop_latency_s')} s")
                break
            except RuntimeError as exc:
                log(f"trial {direction}/{cause} attempt {attempt}: {exc}")
                if attempt == 2:
                    raise
                time.sleep(1.0)
    core.post("/api/v1/navigation/approval/seal", {"test_surface": "floor"})
    sealed = wait_for(lambda: _phase_in(core, ("IDLE", "FAILED")), 120, "seal")
    if not (sealed.get("approval") or {}).get("valid"):
        raise RuntimeError(f"seal did not approve: {sealed.get('reason')}")
    core.post("/api/v1/navigation/approval/navigation-start")


def _load_state(path: Path = STATE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict, path: Path = STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def run(root: Path = Path("/"), core: Core | None = None, sleep=time.sleep, *,
        reapprove_fn=reapprove, pair_fn=pair) -> str:
    def log(message: str) -> None:
        print(f"nav-reapprove: {message}", flush=True)

    if (root / str(DISABLED).lstrip("/")).exists():
        return "disabled"
    if (why := approval_needs_remeasure(root)) is not None:
        return why
    if rosy_claim.check(root) is not None:
        return "claimed"
    if (busy := _status_inputs_busy(root)) is not None:
        return busy
    release = (root / "opt/rosy/current").resolve().name
    state_path = root / str(STATE).lstrip("/")
    attempts = _load_state(state_path).get(release, 0)
    core = core or Core()
    try:
        core.token = pair_fn(core)
        approval = core.get("/api/v1/navigation/approval")
        first = core.get("/api/v1/robot/state")
        sleep(10)
        second = core.get("/api/v1/robot/state")
        verdict = decide(approval, first, second, core.get("/api/v1/power/health"), attempts)
    except (OSError, RuntimeError, http.client.HTTPException) as exc:
        # Wants=rosy-core lets this unit run even if CORE failed to start; never fail the unit.
        return f"core unavailable: {exc}"
    try:
        if verdict != "run":
            return verdict
        _save_state({release: attempts + 1}, state_path)  # only the current release matters
        log(f"{release}: re-measuring navigation approval, attempt {attempts + 1}")
        try:
            reapprove_fn(core, log)
        except Exception as exc:  # noqa: BLE001 - every failure returns the robot to its runtime
            log(f"{release}: failed: {exc}")
            try:
                core.post("/api/v1/navigation/approval/cancel")
            except Exception as cancel:  # noqa: BLE001 - the expiry watch also cancels
                log(f"cancel failed: {cancel}")
            return f"failed: {exc}"
        log(f"{release}: approved and navigation started")
        return "approved and navigation started"
    finally:
        try:
            core.post("/api/v1/auth/logout")
        except Exception:  # noqa: BLE001 - the token expires in 5 minutes anyway
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("run", "status"))
    args = parser.parse_args(argv)
    if args.command == "status":
        print(json.dumps({"state": _load_state(), "disabled": DISABLED.exists(),
                          "needs": approval_needs_remeasure() or "re-measure"}))
        return 0
    print(f"nav-reapprove: {run()}", flush=True)
    return 0  # every outcome is in the journal; never leave a failed rosy-* unit


if __name__ == "__main__":
    sys.exit(main())
