"""One command for the high-accuracy calibration protocol (D-47 addendum 2026-10-01).

    run_calibration.py --robots 8kcn=<robot-ip>,9dfk=<robot-ip> [--codes 8kcn=ABCD-EFGH,...]
                       [--max-angular 8kcn=0.1] [--lidar-yaw-deg D] [--session-api] [--dry-run]
    run_calibration.py --offline SESSION_DIR [SESSION_DIR ...]      (no robot is touched)

Per robot, in parallel (one thread each):
  1. pair with a login code (POST /api/v1/auth/pair), MANUAL mode;
  2. optionally start the CORE calibration session (--session-api; absent API tolerated);
  3. start the bench recorder on the robot over SSH (~/rosy_rec.sh start <reason>,
     D-356 session format with scan, odom, joint_states, cmd_vel, camera);
  4. drive PROTOCOL through CORE teleop at 10 Hz, clipped to the robot's limits,
     with a LiDAR clearance guard on the shared URDF body (D-424, core_common.robot_body):
     a pivot needs every base_footprint return outside rotation radius + 0.02 m
     (Pinky 0.103); a straight needs room for its distance + the D-422 stop gap
     g(v) in its strip (Pinky ~0.085 m LiDAR-equivalent at 0.03 m/s) and is
     shortened to the room there is, or waits and is skipped, instead of aborting
     the run; a return inside the body outline is the robot itself, every other
     finite return (also below range_min) is an obstacle; a scan whose
     received_at has not changed for 0.5 s (PC monotonic clock) or no scan
     aborts; every abort sends zero;
  5. stop the recorder, pull the session (scp) to data/perception/raw/;
  6. analyse (analyze_session.py): wheel radius/separation, per-wheel scale,
     gains per speed, LiDAR yaw from motion, rotation sign (odom vs LiDAR vs
     camera flow), camera pitch/roll/height; write a candidate + report and a
     candidate record per kind into the PC store mirror data/calibration/;
  7. repeat the protocol (at most MAX_REPEATS more times) while the repeat rule fails.

A candidate is never applied or accepted here: tools/calibration/store_cli.py
accept is the operator's step. The LiDAR mount yaw is never assumed: the
clearance guard uses --lidar-yaw-deg, else the robot's accepted lidar_mount
record in the PC store, else robot.yaml with a warning (the URDF nominal 180 deg
since D-397; motion and camera say ~181-182 deg on 8kcn and 9dfk).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "contracts" / "foundation"))
sys.path.insert(0, str(REPO / "learning" / "training" / "perception" / "dataset"))

from core_common.robot_body import PINKY_PRO  # noqa: E402

RAW = REPO / "data" / "perception" / "raw"
STORE = REPO / "data" / "calibration"
RATE_HZ = 10.0
# D-424: clearance comes from the shared URDF body; a pivot keeps the D-422 body margin.
BODY = PINKY_PRO
PIVOT_MARGIN_M = BODY.margin_m
SHORTEST_STRAIGHT_M = 0.05        # a shorter straight measures nothing useful: wait, then skip it
CLEARANCE_WAIT_S = 3.0
# D-424 follow-up: a running pivot ends on an evidence gap (no return, an unseen base sector,
# an unknown band) only after this many consecutive 10 Hz ticks; a near return ends it at once.
# 4 scans at 10 Hz, the same as the mission's rotate_coverage_debounce_ticks 8 (20 Hz ticks):
# longest gap run in 43,625 real C1 scans was 3.
PIVOT_GAP_DEBOUNCE_TICKS = 4            # how long a blocked step waits (sending zero) before it is skipped
SCAN_STALE_S = 0.5
MAX_REPEATS = 2
# Repeat rule: per-straight wheel-radius estimates and per-pivot turn gains of one run.
REPEAT_RADIUS_SPREAD = 0.010      # 1.0 % of r between straights
REPEAT_TURN_SPREAD = 0.005        # 0.5 % of dth/(phi_r - phi_l) between full pivots
SSH_KEY = Path(os.environ.get("LOCALAPPDATA", "~")) / "Rosy" / "ssh" / "rosy-operator-ed25519"
KNOWN_HOSTS = Path(os.environ.get("LOCALAPPDATA", "~")) / "Rosy" / "known_hosts"


@dataclass(frozen=True)
class Step:
    name: str
    linear: float = 0.0      # m/s
    angular: float = 0.0     # rad/s
    seconds: float = 0.0     # 0 linear and angular = rest


def protocol(max_linear=0.03, max_angular=0.1, straight_m=0.24):
    """The fixed protocol v1 (spec and error budget: D-47 addendum 2026-10-01).

    rest 8 s (static scene, stationary camera views) | 4 x (+L, rest, -L, rest)
    at 0.03 m/s | full pivots +360 and -360 deg at min(0.2, limit) | gain steps
    +-90 deg at 0.1/0.2/0.3 rad/s up to the limit | +-L at 0.06 m/s when allowed
    | rest 5 s. Commands above the robot's limit are not sent (CORE would clip
    them and the actual/commanded gain would measure the clip, not the drive)."""
    v = min(0.03, max_linear)
    w = min(0.2, max_angular)
    steps = [Step("rest-start", seconds=8.0)]
    for k in range(4):
        steps += [Step(f"straight+{k}", linear=v, seconds=straight_m / v), Step("rest", seconds=2.0),
                  Step(f"straight-{k}", linear=-v, seconds=straight_m / v), Step("rest", seconds=2.0)]
    for sign in (1, -1):
        steps += [Step(f"pivot{'+' if sign > 0 else '-'}360", angular=sign * w, seconds=2 * math.pi / w),
                  Step("rest", seconds=3.0)]
    for rate in (0.1, 0.2, 0.3):
        if rate <= max_angular + 1e-9:
            for sign in (1, -1):
                steps += [Step(f"gain{sign * rate:+.1f}", angular=sign * rate, seconds=(math.pi / 2) / rate),
                          Step("rest", seconds=2.0)]
    if max_linear >= 0.06:
        steps += [Step("fast+", linear=0.06, seconds=straight_m / 0.06), Step("rest", seconds=2.0),
                  Step("fast-", linear=-0.06, seconds=straight_m / 0.06), Step("rest", seconds=2.0)]
    return steps + [Step("rest-end", seconds=5.0)]


def duration_s(steps):
    return sum(s.seconds for s in steps)


# --- clearance guard ----------------------------------------------------------

class ScanFreshness:
    """Staleness judged on the PC's monotonic clock: when did received_at last change?

    The robot's clock is never compared with the PC's (8kcn ran days off). A
    missing or non-numeric received_at counts as stale."""

    def __init__(self):
        self.value, self.changed_at = None, None

    def fresh(self, sample, now_mono):
        received = sample.get("received_at") if isinstance(sample, dict) else None
        if not isinstance(received, (int, float)) or isinstance(received, bool) or not math.isfinite(received):
            return False
        if received != self.value:
            self.value, self.changed_at = received, now_mono
        return now_mono - self.changed_at <= SCAN_STALE_S


def scan_problem(sample, fresh=True):
    """Why this scan cannot be judged at all (None = usable). Any of these aborts the run."""
    if sample is None:
        return "no LiDAR sample"
    if not fresh:
        return "LiDAR sample stale"
    if len(sample.get("ranges") or []) < 2:
        return "empty LiDAR sample"
    return None


def _view(sample, lidar_yaw_deg, body, self_mask):
    return body.scan_view(sample, forward_deg=lidar_yaw_deg, self_mask=self_mask)


def straight_room_m(sample, step: Step, lidar_yaw_deg, *, body=BODY, self_mask=()):
    """Straight travel the step may still make: the body's strip gap minus the D-422 stop gap
    g(v) (inf = nothing in the strip). 0 when an unknown beam reaches past the body edge that
    way (no ultrasonic in this tool to cover it)."""
    view = _view(sample, lidar_yaw_deg, body, self_mask)
    reverse = step.linear < 0
    if body.unknown_blocks(view, reverse=reverse):
        return 0.0
    gap = body.translation_gap(view.points, reverse=reverse)
    return math.inf if gap is None else max(0.0, gap - body.stop_gap_m(step.linear))


def clearance_reason(sample, step: Step, lidar_yaw_deg, fresh=True, *, body=BODY, self_mask=()):
    """Why this step may not continue (None = clear). sample: GET /api/v1/sensors/lidar;
    fresh: ScanFreshness.fresh() for this sample. scan_problem() reasons abort the run; the
    others only end or hold this step (D-424)."""
    problem = scan_problem(sample, fresh)
    if problem:
        return problem
    if step.linear == 0.0 and step.angular == 0.0:
        return None
    if step.linear == 0.0:
        # D-424 review M1/L2: every base sector seen, every point beyond rho + margin, no
        # unknown band in the sweep (this tool has no ultrasonic); an empty scan is not clear.
        reason = body.rotation_reason(_view(sample, lidar_yaw_deg, body, self_mask), PIVOT_MARGIN_M)
        return None if reason is None else f"clearance: {reason}"
    room = straight_room_m(sample, step, lidar_yaw_deg, body=body, self_mask=self_mask)
    if room > 0.0:
        return None
    return f"clearance: the {'rear' if step.linear < 0 else 'front'} stop gap is reached"


def pivot_kind(sample, lidar_yaw_deg, *, body=BODY, self_mask=()):
    """RobotBody.rotation_check kind for a pivot on this scan (None = clear)."""
    return body.rotation_check(_view(sample, lidar_yaw_deg, body, self_mask), PIVOT_MARGIN_M)[0]


def plan_step(sample, step: Step, lidar_yaw_deg, fresh=True, *, body=BODY, self_mask=()):
    """(step to run or None, note). A straight with less room than its distance is shortened
    to the room there is (>= SHORTEST_STRAIGHT_M); otherwise None = wait (the caller retries
    for CLEARANCE_WAIT_S, then skips the step). A scan problem is returned as the note with
    no step: the caller aborts."""
    problem = scan_problem(sample, fresh)
    if problem:
        return None, problem
    if step.linear == 0.0:
        reason = clearance_reason(sample, step, lidar_yaw_deg, fresh, body=body, self_mask=self_mask)
        return (step, None) if reason is None else (None, reason)
    room = straight_room_m(sample, step, lidar_yaw_deg, body=body, self_mask=self_mask)
    want = abs(step.linear) * step.seconds
    if room >= want:
        return step, None
    if room >= SHORTEST_STRAIGHT_M:
        return (replace(step, seconds=room / abs(step.linear)),
                f"shortened to {room:.3f} m of {want:.3f} m (room before the stop gap)")
    return None, f"only {room:.3f} m of room before the stop gap"


# --- robot I/O ------------------------------------------------------------------

class Core:
    def __init__(self, host, token=None, port=8080):
        self.base, self.token = f"http://{host}:{port}", token

    def call(self, method, path, body=None, timeout=2.0):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {self.token}"} if self.token else {})})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode() or "null"
            return resp.status, json.loads(text)

    def pair(self, code, label="Rosy calibration (PC)"):
        _status, doc = self.call("POST", "/api/v1/auth/pair", {"code": code.upper(), "label": label})
        self.token = doc["token"]

    def lidar(self):
        try:
            return self.call("GET", "/api/v1/sensors/lidar", timeout=0.5)[1]
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def teleop(self, linear, angular):
        self.call("POST", "/api/v1/teleop", {"linear": linear, "angular": angular}, timeout=0.4)

    def stop(self):
        for _ in range(3):
            try:
                self.teleop(0.0, 0.0)
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(0.1)

    def session_api(self, action, path):
        """CORE calibration session start/stop (feat/calibration-session-mode); absent API tolerated."""
        try:
            return self.call("POST", path, {"action": action})
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 405, 501):
                return exc.code, {"skipped": "calibration session API not available"}
            raise


def ssh(host, command, timeout=60):
    args = ["ssh", "-i", str(SSH_KEY), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
            "-o", "ConnectTimeout=5", f"rosy@{host}", command]
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False,
                          env={**os.environ, "PYTHONUTF8": "1"})


def pull(host, remote_folder, dest_root=RAW):
    dest_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["scp", "-r", "-i", str(SSH_KEY), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                    "-o", f"UserKnownHostsFile={KNOWN_HOSTS}", f"rosy@{host}:{remote_folder}", str(dest_root)],
                   check=True, timeout=1800)
    return dest_root / Path(remote_folder).name


def parse_self_mask(text):
    """--self-mask: name=FROM:TO:REACH[/FROM:TO:REACH...],name2=... (robot-frame degrees, 0 =
    forward, + = left; reach in metres, at most 0.30) -- the robot's line_follow.lidar_self_mask
    (D-422 format). Returns {name: ((from, to, reach), ...)}."""
    out = {}
    for item in filter(None, (part.strip() for part in (text or "").split(","))):
        name, _, windows = item.partition("=")
        mask = []
        for window in filter(None, windows.split("/")):
            lo, hi, reach = (float(v) for v in window.split(":"))
            if not (-180.0 <= lo < hi <= 180.0) or not 0.0 < reach <= 0.30:
                raise ValueError(f"self-mask window out of range: {window!r}")
            mask.append((lo, hi, reach))
        if not name.strip() or not mask:
            raise ValueError(f"self-mask needs name=FROM:TO:REACH: {item!r}")
        out[name.strip()] = tuple(mask)
    return out


def drive(core: Core, steps, lidar_yaw_deg, log, stop_event=None, *, body=BODY, self_mask=(),
          adjustments=None):
    """Run the steps; returns None or the abort reason (zero is always sent last).

    A missing or stale scan aborts. Clearance never aborts the run (D-424): a step is first
    planned (a straight is shortened to the room there is), a step without room waits up to
    CLEARANCE_WAIT_S sending zero and is then skipped, and a step that reaches its stop gap
    while moving ends there. Each adjustment is appended to `adjustments` (a list) as
    {"step", "action": skipped | shortened | ended_early, "note"} for the run's result."""
    freshness = ScanFreshness()
    adjustments = [] if adjustments is None else adjustments
    look = {"body": body, "self_mask": self_mask}

    def tick_wait(tick):
        time.sleep(max(0.0, 1.0 / RATE_HZ - (time.monotonic() - tick)))

    try:
        for step in steps:
            if step.linear or step.angular:
                give_up = time.monotonic() + CLEARANCE_WAIT_S
                while True:
                    tick = time.monotonic()
                    if stop_event is not None and stop_event.is_set():
                        return "stopped by the operator"
                    sample = core.lidar()
                    fresh = freshness.fresh(sample, tick)
                    planned, note = plan_step(sample, step, lidar_yaw_deg, fresh, **look)
                    if planned is None and scan_problem(sample, fresh):
                        return f"{step.name}: {note}"
                    if planned is not None or tick >= give_up:
                        break
                    core.teleop(0.0, 0.0)
                    tick_wait(tick)
                if planned is None:
                    log(f"{step.name}: skipped, {note}")
                    adjustments.append({"step": step.name, "action": "skipped", "note": note})
                    continue
                if note:
                    log(f"{step.name}: {note}")
                    adjustments.append({"step": step.name, "action": "shortened", "note": note})
                step = planned
            log(f"{step.name}: v={step.linear:+.3f} w={step.angular:+.2f} {step.seconds:.1f}s")
            end = time.monotonic() + step.seconds
            gap_ticks = 0
            while time.monotonic() < end:
                tick = time.monotonic()
                if stop_event is not None and stop_event.is_set():
                    return "stopped by the operator"
                sample = core.lidar()
                fresh = freshness.fresh(sample, tick)
                reason = clearance_reason(sample, step, lidar_yaw_deg, fresh, **look)
                if reason and (step.linear or step.angular):
                    if scan_problem(sample, fresh):
                        return f"{step.name}: {reason}"
                    if step.linear == 0.0 and pivot_kind(sample, lidar_yaw_deg, **look) != "near":
                        # D-424 follow-up: one flickering scan (an unseen sector, no return)
                        # ends a pivot only after PIVOT_GAP_DEBOUNCE_TICKS in a row.
                        gap_ticks += 1
                        if gap_ticks < PIVOT_GAP_DEBOUNCE_TICKS:
                            core.teleop(step.linear, step.angular)
                            tick_wait(tick)
                            continue
                    log(f"{step.name}: ended early, {reason}")
                    adjustments.append({"step": step.name, "action": "ended_early", "note": reason})
                    break
                gap_ticks = 0
                core.teleop(step.linear, step.angular)   # zero during rests keeps the deadman fed
                tick_wait(tick)
        return None
    except (urllib.error.URLError, OSError) as exc:
        return f"CORE link lost: {exc}"
    finally:
        core.stop()


# --- repeat rule ----------------------------------------------------------------

def repeat_reason(run, adjustments=(), steps=()):
    """Why the run must be repeated (None = accept the run for the candidate). D-424 review
    M5 and follow-up: a run that skipped every straight, or every pivot, for clearance is
    never a success, whatever was recorded (`steps` = the protocol that was driven)."""
    skipped = {a.get("step") for a in adjustments if a.get("action") == "skipped"}
    for kind, chosen in (("straight", [s for s in steps if s.linear]),
                         ("pivot", [s for s in steps if s.angular and not s.linear])):
        if chosen and all(s.name in skipped for s in chosen):
            return f"every {kind} step was skipped for clearance ({len(chosen)} of {len(chosen)})"
    recs = [r for r in run["records"] if "error" not in r]
    radii = [r["ds"] / ((r["phi_l"] + r["phi_r"]) / 2) for r in recs
             if r["kind"] == "straight" and abs(r["phi_l"] + r["phi_r"]) > 1.0]
    turns = [r["dth"] / (r["phi_r"] - r["phi_l"]) for r in recs
             if r["kind"] == "pivot" and abs(r["dth"]) > math.radians(300)]
    if len(radii) < 4 or len(turns) < 2:
        return f"too few usable segments (straights {len(radii)}, full pivots {len(turns)})"
    spread_r = (max(radii) - min(radii)) / (sum(radii) / len(radii))
    spread_c = (max(turns) - min(turns)) / abs(sum(turns) / len(turns))
    if spread_r > REPEAT_RADIUS_SPREAD:
        return f"straight radius spread {spread_r:.2%} > {REPEAT_RADIUS_SPREAD:.1%}"
    if spread_c > REPEAT_TURN_SPREAD:
        return f"pivot turn-gain spread {spread_c:.2%} > {REPEAT_TURN_SPREAD:.1%}"
    return None


def lidar_yaw_for(robot_name, explicit):
    if explicit is not None:
        return explicit, "argument"
    from core_common.calibration_store import CalibrationStore
    rec = CalibrationStore(STORE).current(robot_name, "lidar_mount") if (STORE / robot_name).exists() else None
    if rec:
        return math.degrees(rec["values"]["lidar_yaw_offset"]) % 360.0, f"accepted record {rec['id']}"
    from geometry import robot_lidar_yaw_deg
    return robot_lidar_yaw_deg(), "robot.yaml (SUSPECT: motion/camera say ~181-182 deg; pass --lidar-yaw-deg)"


def run_robot(name, host, code, args, results, stop_event=None, live=None):
    """One robot, end to end. Always records a result; always stops the recorder it started."""
    log = lambda msg: print(f"[{name}] {msg}", flush=True)  # noqa: E731
    state = {"recording": False}
    try:
        _run_robot(name, host, code, args, results, stop_event, live, state, log)
    except Exception as exc:  # noqa: BLE001 - one robot's failure must not hide the others
        log(f"FAILED: {exc!r}")
        results[name] = {**results.get(name, {}), "error": repr(exc)}
    finally:
        if state["recording"]:
            stopped = ssh(host, "~/rosy_rec.sh stop")
            log(f"recorder stopped: {stopped.stdout.strip().splitlines()[:1]}")
        results.setdefault(name, {"error": "no result recorded"})


def _run_robot(name, host, code, args, results, stop_event, live, state, log):
    max_w = args.max_angular.get(name, 0.1)
    steps = protocol(max_linear=args.max_linear.get(name, 0.03), max_angular=max_w)
    yaw, yaw_source = lidar_yaw_for(device_name(name), args.lidar_yaw_deg)
    log(f"protocol {len(steps)} steps, {duration_s(steps) / 60:.1f} min; LiDAR yaw {yaw:.2f} deg from {yaw_source}")
    if args.dry_run:
        for s in steps:
            log(f"  {s.name:12s} v={s.linear:+.3f} w={s.angular:+.2f} {s.seconds:5.1f}s")
        results[name] = {"dry_run": True}
        return
    core = Core(host)
    if live is not None:
        live[name] = (core, host)
    core.pair(code)
    core.call("POST", "/api/v1/mode", {"mode": "MANUAL"})
    sessions = []
    for attempt in range(1 + MAX_REPEATS):
        if stop_event is not None and stop_event.is_set():
            results[name] = {"error": "stopped by the operator", "sessions": [str(s) for s in sessions]}
            return
        if args.session_api:
            log(f"session start: {core.session_api('start', args.session_api_path)}")
        started = ssh(host, f"~/rosy_rec.sh start calib-protocol-v1-{name}-{attempt}")
        if started.returncode != 0 or "recording:" not in started.stdout:
            log(f"recorder did not start: {started.stdout.strip()} {started.stderr.strip()}")
            results[name] = {"error": "recorder did not start"}
            return
        state["recording"] = True
        folder = started.stdout.split("recording:", 1)[1].strip().splitlines()[0]
        adjustments = []
        abort = drive(core, steps, yaw, log, stop_event, self_mask=getattr(args, "self_mask", {}).get(name, ()),
                      adjustments=adjustments)
        if adjustments:
            log(f"clearance adjusted {len(adjustments)} step(s): "
                + ", ".join(f"{a['step']} {a['action']}" for a in adjustments))
        stopped = ssh(host, "~/rosy_rec.sh stop")
        state["recording"] = False
        if args.session_api:
            log(f"session stop: {core.session_api('stop', args.session_api_path)}")
        log(f"recorder: {stopped.stdout.strip().splitlines()[:1]}")
        if abort:
            log(f"ABORTED: {abort}")
            results[name] = {"error": abort, "sessions": sessions, "adjusted_steps": adjustments}
            return
        local = pull(host, folder)
        sessions.append(local)
        import analyze_session as AS
        run = AS.analyse_run(local, yaw, AS.load_profile())
        why = repeat_reason(run, adjustments, steps)
        log(f"attempt {attempt}: {'accepted run' if why is None else 'repeat: ' + why}")
        if why is None:
            break
    results[name] = {"sessions": [str(s) for s in sessions], "adjusted_steps": adjustments,
                     "repeat_reason": why}


def stop_all(stop_event, live, threads):
    """Ctrl-C: every drive loop stops, and the main thread also sends zero and
    stops each recorder itself (a worker may be blocked in I/O). Two passes -
    zero to every robot first, recorders second - and one robot's failure
    never skips another's stop."""
    stop_event.set()
    robots = list(live.items())
    for name, (core, _host) in robots:
        print(f"[{name}] operator stop: zero", flush=True)
        try:
            core.stop()
        except Exception as exc:  # noqa: BLE001 - keep stopping the others
            print(f"[{name}] zero failed: {exc!r}", flush=True)
    for name, (_core, host) in robots:
        try:
            ssh(host, "~/rosy_rec.sh stop")
        except Exception as exc:  # noqa: BLE001
            print(f"[{name}] recorder stop failed: {exc!r}", flush=True)
    join_all(threads, 5.0)


def join_all(threads, timeout_s):
    """Join workers for at most timeout_s in total (bounded, so main can report)."""
    deadline = time.monotonic() + timeout_s
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    return [t.name for t in threads if t.is_alive()]


def device_name(name):
    """The store/session device for --robots name: rosy_rec.sh writes session.json
    "device" as the hostname with [^A-Za-z0-9_-] replaced by '_', and the Pinky Pro
    hostnames are rosy-pinky-<name>."""
    return rec_device(f"rosy-pinky-{name}")


def rec_device(hostname):
    import re
    return re.sub(r"[^A-Za-z0-9_-]", "_", hostname)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--robots", default="", help="name=host,... (name as in rosy-pinky-<name>)")
    ap.add_argument("--codes", default="", help="name=LOGIN-CODE,... (asked for when missing)")
    ap.add_argument("--max-angular", default="", help="name=rad/s,... robot limit (default 0.1, L0)")
    ap.add_argument("--max-linear", default="", help="name=m/s,... robot limit (default 0.03)")
    ap.add_argument("--lidar-yaw-deg", type=float, default=None)
    ap.add_argument("--self-mask", default="",
                    help="name=FROM:TO:REACH[/...],... robot-frame deg + m: the robot's own parts the "
                         "LiDAR sees (its line_follow.lidar_self_mask; D-424)")
    ap.add_argument("--session-api", action="store_true", help="call the CORE calibration session API")
    ap.add_argument("--session-api-path", default="/api/v1/calibration/session")
    ap.add_argument("--dry-run", action="store_true", help="print the protocol; touch nothing")
    ap.add_argument("--offline", nargs="*", type=Path, help="analyse existing sessions only")
    args = ap.parse_args(argv)

    def pairs(text, cast=str):
        return {k.strip(): cast(v.strip()) for k, v in (p.split("=", 1) for p in text.split(",") if "=" in p)}
    args.max_angular, args.max_linear = pairs(args.max_angular, float), pairs(args.max_linear, float)
    args.self_mask = parse_self_mask(args.self_mask)
    if args.offline:
        import analyze_session as AS
        extra = ["--lidar-yaw-deg", str(args.lidar_yaw_deg)] if args.lidar_yaw_deg is not None else []
        return AS.main([str(p) for p in args.offline] + extra)
    robots, codes = pairs(args.robots), pairs(args.codes)
    if not robots:
        ap.error("give --robots name=host,... or --offline SESSION_DIR ...")
    if not args.dry_run:
        for name in robots:
            codes.setdefault(name, input(f"login code for {name}: ").strip())
    results, threads, live, stop_event = {}, [], {}, threading.Event()
    for name, host in robots.items():
        t = threading.Thread(target=run_robot, name=f"calib-{name}",
                             args=(name, host, codes.get(name), args, results, stop_event, live))
        t.start()
        threads.append(t)
    try:
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(0.2)
    except KeyboardInterrupt:
        stop_all(stop_event, live, threads)
    still = join_all(threads, 30.0)
    for name in still:
        print(f"[{name}] worker still running after the bounded join", flush=True)
    missing = [name for name in robots if name not in results]
    for name in missing:
        results[name] = {"error": "no result recorded"}
    runs = [Path(s) for r in results.values() for s in r.get("sessions", [])]
    if runs:
        import analyze_session as AS
        extra = ["--lidar-yaw-deg", str(args.lidar_yaw_deg)] if args.lidar_yaw_deg is not None else []
        AS.main([str(p) for p in runs] + extra)
    print(json.dumps({"finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "results": results}, indent=1))
    return 0 if results and all("error" not in r for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
