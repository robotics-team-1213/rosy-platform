"""Staging-bay pink-line docking on a real Pinky, as one command (D-512 extension).

    bay_dock.py --robot rosy-pinky-y8xs --token-file FILE (--ca-file CA | --insecure)
                --site-url URL (--site-ca-file CA | --site-insecure) --peer-check-ok "EVIDENCE"
                --bay-verdict VERDICT.json --dock-id bay_c2 [--remove-dock]

Steps: preflight (identity, battery unplugged, update hold, a bay verdict that names the bay and says
the robot stands inside the bay line, rear toward the bay, no cable) -> approval_refresh (only when the
navigation approval is not valid for the current release, D-985) -> navigation_start (LOCALIZED) ->
line_view (dock/observation over SSH; the bay line, not only the aisle line) -> dock_register (SLAM
origin moves with every navigation restart, so every run registers) -> dock (watch, cancel at 180 s).
Every abort names its step; cleanup cancels the dock/approval, zeroes teleop, IDLE, releases the hold.
Raw evidence stays in the evidence dir (default $ROSY_SCRATCH/device-test/); no robot or Fleet is
touched by importing this module.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import statistics
import sys
import time

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "tools" / "capture"))
sys.path.insert(0, str(HERE))
from live_transport import Live  # noqa: E402
from plan_rules import OVERLAY_PATH, sanitize  # noqa: E402
from run_helpers import Abort, _sigterm, log  # noqa: E402
from tether import wrap  # noqa: E402


def _load_run():
    """run.py by path under the name test_device_test_run uses (another suite owns the bare name 'run')."""
    if "device_test_run" not in sys.modules:
        spec = importlib.util.spec_from_file_location("device_test_run", HERE / "run.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["device_test_run"] = module
        spec.loader.exec_module(module)
    return sys.modules["device_test_run"].Run


TRIALS = (("forward", "button_release"), ("forward", "command_loss"), ("reverse", "button_release"),
          ("cw", "button_release"), ("ccw", "button_release"))
FATAL = ("CLEARANCE_TOO_SMALL", "CLEARANCE_UNKNOWN", "WHEELS_NOT_MOVING_BODY")
MAX_TRIES = 4
HOLD_S, HOLD_EVERY_S = 0.6, 0.05        # CORE ends a trial when the gap between holds passes 0.4 s
DOCK_TIMEOUT_S, LOCALIZE_TIMEOUT_S = 180.0, 100.0
MIN_OBS, MAX_LINE_DIFF_DEG, MIN_BATTERY = 12, 10.0, 20
DOCK_END = ("DOCKED", "DOCK_FAILED", "UNDOCKED")
SECTORS = ("front", "front-left", "left", "rear-left", "rear", "rear-right", "right", "front-right")
BAY_TYPE = {"name": "bay_line_c", "detector": "camera_line", "approach": "line", "staging_offset_m": 0.32,
            "max_retries": 1}
OBS_CMD = (". /opt/ros/*/setup.bash 2>/dev/null; t=$(ros2 topic list 2>/dev/null | grep -m1 /dock/observation); "
           "[ -n \"$t\" ] && timeout 20 ros2 topic echo --field data \"$t\" 2>/dev/null")


# --- pure helpers ---------------------------------------------------------------------------

def obs_errors(o):
    """(along to the stop face, lateral, heading) of one observation: same split as rear_phases.rear_errors."""
    ax, ay = math.cos(o["yaw"]), math.sin(o["yaw"])
    return o["x"] * ax + o["y"] * ay, ay * o["x"] - ax * o["y"], wrap(math.pi - o["yaw"])


def _median_obs(rows):
    ref = rows[0]["yaw"]
    return {"x": statistics.median(r["x"] for r in rows), "y": statistics.median(r["y"] for r in rows),
            "yaw": wrap(ref + statistics.median(wrap(r["yaw"] - ref) for r in rows))}


def summarize_observations(obs, min_n=MIN_OBS, max_diff_deg=MAX_LINE_DIFF_DEG):
    """Medians of the bay line (lateral_measured true, A) and the aisle line (false, X). ok False + reason
    when the robot cannot register a dock from what it sees."""
    vis = [o for o in obs if o.get("visible") and all(isinstance(o.get(k), (int, float)) for k in ("x", "y", "yaw"))]
    a = [o for o in vis if o.get("lateral_measured") is True]
    x = [o for o in vis if o.get("lateral_measured") is False]
    s = {"frames": len(obs), "visible": len(vis), "bay_line": len(a), "aisle_line": len(x), "ok": False,
         "reason": None, "median": None, "errors": None, "aisle_median": None, "line_diff_deg": None}
    if len(vis) < min_n:
        s["reason"] = f"only {len(vis)} visible observations (need {min_n}): the line is not in view"
    elif not a:
        s["reason"] = ("only the aisle line is measured, not the bay line: the robot is probably ahead of the "
                       "stop face by more than about 0.305 m (the aisle line is under its nose)")
    else:
        s["median"] = _median_obs(a)
        s["errors"] = dict(zip(("along", "lateral", "heading"), obs_errors(s["median"])))
        if x:
            s["aisle_median"] = _median_obs(x)
            s["line_diff_deg"] = round(abs(math.degrees(wrap(s["median"]["yaw"] - s["aisle_median"]["yaw"]))), 2)
        if s["line_diff_deg"] is not None and s["line_diff_deg"] > max_diff_deg:
            s["reason"] = f"bay and aisle line differ by {s['line_diff_deg']} deg (limit {max_diff_deg})"
        else:
            s["ok"] = True
    return s


def dock_pose(pose, median):
    """Stop-face centre in map coordinates: pose composed with the observation (x, y, yaw in the robot frame)."""
    c, s = math.cos(pose["yaw"]), math.sin(pose["yaw"])
    return {"x": pose["x"] + c * median["x"] - s * median["y"], "y": pose["y"] + s * median["x"] + c * median["y"],
            "yaw": wrap(pose["yaw"] + median["yaw"])}


def trial_should_retry(row, last):
    """A trial that did not become valid is measured again unless CORE named a cause a retry cannot fix."""
    text = json.dumps([row, last], default=str)
    return not any(code in text for code in FATAL)


def approval_needed(approval, release_id):
    """D-985: a new release drops the approval, so it is valid only for the release it was measured on."""
    if not isinstance(approval, dict) or not approval.get("valid"):
        return True
    return bool(release_id) and approval.get("measured_release_id") != release_id


def sectors(scan):
    """Nearest valid range per 45-degree sector; LiDAR 0 deg is the REAR of a Pinky Pro."""
    out = {}
    for i, r in enumerate(scan.get("ranges") or []):
        if not isinstance(r, (int, float)) or not scan.get("range_min", 0.05) < r < 8.0:
            continue
        heading = math.degrees(wrap(scan["angle_min"] + i * scan["angle_increment"] - math.pi))
        name = SECTORS[int(((heading + 22.5) % 360) // 45)]
        out[name] = round(min(out.get(name, 9.0), r), 3)
    return out


def check_bay_verdict(v):
    """Fail closed: no movement without a stated place and identity (2026-11-18: almost ran off the bay)."""
    if not isinstance(v, dict):
        raise ValueError("bay verdict is not a JSON object")
    bad = [k for k, want in (("in_bay_line", True), ("rear_toward_bay", True), ("cable_absent", True))
           if v.get(k) is not want]
    if not str(v.get("bay_id") or "").strip():
        bad.append("bay_id")
    if not str(v.get("judged_by") or "").strip():
        bad.append("judged_by")
    if bad:
        raise ValueError("bay verdict must say, for the frames/photo you looked at: bay_id, judged_by, "
                         f"in_bay_line true, rear_toward_bay true, cable_absent true; not satisfied: {bad}")
    return v


# --- the run ----------------------------------------------------------------------------------

class BayDock(_load_run()):
    def __init__(self, robot, args, evidence):
        super().__init__(robot, {"topic": "bay-dock", "overlay_path": OVERLAY_PATH, "overlay": {}}, args, evidence)
        self.step = "start"
        self.measuring = self.dock_active = False
        self.summary.update(bay_dock={"dock_id": args.dock_id}, trials=[])

    def post(self, path, body=None, timeout=3.0):
        return self.r.core.call("POST", path, {} if body is None else body, timeout=timeout)

    def camera(self, tag):
        """Overhead frame + LiDAR sectors only (the base class also asks for the robot cameras)."""
        saved = {}
        data = self.r.overhead()
        if data:
            (self.ev / f"{tag}_overhead.jpg").write_bytes(data)
            saved[f"{tag}_overhead.jpg"] = "saved"
        s, scan = self.r.core.call("GET", "/sensors/lidar")
        self.phase(f"camera:{tag}", frames=saved, lidar=sectors(scan) if s == 200 and isinstance(scan, dict) else None)

    def lidar_odom(self):
        s, scan = self.r.core.call("GET", "/sensors/lidar")
        _, st = self.r.core.call("GET", "/robot/state")
        return {"lidar": sectors(scan) if s == 200 and isinstance(scan, dict) else None,
                "odom": (st or {}).get("pose") if isinstance(st, dict) else None}

    # 1
    def preflight(self):
        self.peers()
        self.identity()
        st = self.get("/robot/state")
        pct = (st.get("battery") or {}).get("percent")
        charging = (st.get("battery_status") or {}).get("charging")
        why = [w for w, bad in ((f"battery {pct}% < {MIN_BATTERY}%", pct is None or pct < MIN_BATTERY),
                                ("charging or charge state unknown: unplug first", charging is not False),
                                ("estop", (st.get("safety") or {}).get("estop")),
                                ("pose unknown", not isinstance(st.get("pose"), dict))) if bad]
        lf = self.get("/line-follow")
        if lf.get("mode") not in ("OFF", None):
            why.append(f"line-follow already {lf.get('mode')} (someone else is driving)")
        if why:
            raise Abort("preflight: " + "; ".join(why))
        try:
            verdict = check_bay_verdict(json.loads(Path(self.args.bay_verdict).read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise Abort(f"bay verdict: {exc}") from exc
        self.summary["bay_dock"]["bay_id"] = verdict["bay_id"]
        self.phase("preflight", battery_percent=pct, pose=st.get("pose"), bay_id=verdict["bay_id"],
                   judged_by=verdict["judged_by"])
        self.hold()

    # 2
    def refresh_approval(self):
        ap = self.get("/navigation/approval")
        release = self.get("/system/info").get("release_id")
        self.summary["release_id"] = release
        if not approval_needed(ap.get("approval"), release):
            self.summary["approval"] = {"refreshed": False, **ap["approval"]}
            self.phase("approval", skipped=True, release_id=release)
            return
        if ap.get("phase") != "MEASURING":
            s, b = self.post("/navigation/approval/begin")
            if s != 200:
                raise Abort(f"approval begin -> {s} {json.dumps(b)[:200]}")
        self.measuring = True
        self.wait_approval(lambda a: a.get("phase") == "MEASURING" and a.get("runtime_mode") == "motor", 90,
                           "MEASURING in runtime_mode motor")
        for direction, cause in TRIALS:
            self.run_trial(direction, cause)
        s, b = self.post("/navigation/approval/seal", {"test_surface": "floor"})
        if s != 200:
            raise Abort(f"approval seal -> {s} {json.dumps(b)[:200]}")
        ap = self.wait_approval(lambda a: a.get("phase") == "IDLE" and (a.get("approval") or {}).get("valid"), 90,
                                "IDLE with a valid approval")
        self.measuring = False
        self.summary["approval"] = {"refreshed": True, **ap["approval"]}
        self.phase("approval", refreshed=True, release_id=release, measured=ap["approval"].get("measured_release_id"))

    def wait_approval(self, ok, limit_s, what):
        t0 = self.r.now()
        while True:
            ap = self.get("/navigation/approval")
            if ok(ap):
                return ap
            if self.r.now() - t0 > limit_s:
                raise Abort(f"approval: {what} not reached in {limit_s} s (phase {ap.get('phase')}, "
                            f"reason {ap.get('reason')!r})")
            self.r.sleep(1.0)

    def run_trial(self, direction, cause):
        why = None
        for attempt in range(1, MAX_TRIES + 1):
            before = self.lidar_odom()
            s, b = self.post("/navigation/approval/trial/start",
                             {"direction": direction, "stop_cause": cause, "test_surface": "floor"})
            if s != 200:
                why = f"start -> {s} {json.dumps(b)[:200]}"
                if not trial_should_retry({}, b):
                    raise Abort(f"trial {direction}/{cause}: {why}")
            else:
                self.hold_trial(cause)
                after = self.lidar_odom()
                ap = self.wait_approval(lambda a: not (a.get("trial") or {}).get("active"), 10, "trial finished")
                row = next((t for t in ap.get("trials", []) if (t.get("direction"), t.get("stop_cause")) == (direction, cause)), {})
                last = (ap.get("trial") or {}).get("last")
                self.summary["trials"].append({"direction": direction, "stop_cause": cause, "attempt": attempt,
                                               "state": row.get("state"), "last": last, "before": before, "after": after})
                if row.get("state") == "valid":
                    self.phase("trial", direction=direction, stop_cause=cause, attempt=attempt)
                    return
                why = f"not valid: row {json.dumps(row)[:200]} last {json.dumps(last)[:200]}"
                if not trial_should_retry(row, last):
                    raise Abort(f"trial {direction}/{cause}: {why}")
            self.phase("trial_retry", direction=direction, stop_cause=cause, attempt=attempt, why=why)
            self.r.sleep(1.0)
        raise Abort(f"trial {direction}/{cause} not valid after {MAX_TRIES} tries: {why}")

    def hold_trial(self, cause):
        """Hold every 0.05 s for 0.6 s on one kept-alive connection; then release by stop or by silence."""
        end = self.r.now() + HOLD_S
        while self.r.now() < end:
            s, b = self.r.core.call("POST", "/navigation/approval/trial/hold", {}, timeout=0.25, attempts=1)
            if s != 200:
                self.phase("trial_hold_refused", status=s, body=json.dumps(b)[:120])
                break
            self.r.sleep(HOLD_EVERY_S)
        if cause == "button_release":
            self.post("/navigation/approval/trial/stop")

    # 3
    def navigation_start(self):
        s, b = self.post("/navigation/approval/navigation-start", timeout=10.0)
        if s != 200:
            raise Abort(f"navigation-start -> {s} {json.dumps(b)[:200]}")
        t0, loc = self.r.now(), None
        while self.r.now() - t0 <= LOCALIZE_TIMEOUT_S:
            loc = self.get("/robot/state").get("localization") or {}
            if loc.get("state") == "LOCALIZED":
                self.phase("navigation", localized_after_s=round(self.r.now() - t0, 1))
                return
            self.r.sleep(1.0)
        raise Abort(f"not LOCALIZED in {LOCALIZE_TIMEOUT_S:.0f} s ({loc}); with the slam backend loc_assist "
                    "can hide UNKNOWN (fix/loc-assist-not-under-slam)")

    # 4
    def line_view(self):
        rc, out = self.sh(OBS_CMD)
        obs = []
        for chunk in out.split("\n---"):
            try:
                value = yaml.safe_load(chunk)
                obs.append(json.loads(value) if isinstance(value, str) else value)
            except (ValueError, yaml.YAMLError):
                continue            # the cut-off last message
        obs = [o for o in obs if isinstance(o, dict)]
        (self.ev / "observations.jsonl").write_text("".join(json.dumps(o) + "\n" for o in obs), encoding="utf-8")
        summary = summarize_observations(obs)
        self.summary["observation"] = summary
        self.phase("line_view", ssh_rc=rc, **{k: summary[k] for k in ("frames", "visible", "bay_line", "aisle_line")})
        if not summary["ok"]:
            raise Abort(f"line_view: {summary['reason']}")
        pose = self.get("/robot/state").get("pose")
        if not isinstance(pose, dict):
            raise Abort("line_view: pose unknown")
        self.summary["bay_dock"]["pose"] = pose
        self.median, self.pose = summary["median"], pose

    # 5
    def dock_register(self):
        pose = dock_pose(self.pose, self.median)
        _, types = self.r.core.call("GET", "/docking/types")
        if "bay_line_c" not in json.dumps(types):
            s, b = self.post("/docking/types", BAY_TYPE)
            if s not in (200, 201):
                raise Abort(f"dock type -> {s} {json.dumps(b)[:200]}")
        self.r.core.call("DELETE", f"/docking/docks/{self.args.dock_id}")
        s, b = self.post("/docking/docks", {"id": self.args.dock_id, "type": "bay_line_c", **pose})
        if s not in (200, 201):
            raise Abort(f"dock register -> {s} {json.dumps(b)[:200]}")
        self.summary["bay_dock"]["registered"] = pose
        self.phase("dock_register", dock=self.args.dock_id, **{k: round(v, 4) for k, v in pose.items()})

    # 6
    def dock(self):
        s, b = self.post("/docking/dock", {"dock": self.args.dock_id,
                                           "correlation_id": f"bay-dock-{int(self.r.now())}"})
        if s != 200:
            raise Abort(f"dock -> {s} {json.dumps(b)[:200]}")
        self.dock_active = True
        t0, last, seen, final = self.r.now(), None, [], None
        while self.r.now() - t0 <= DOCK_TIMEOUT_S:
            s, st = self.r.core.call("GET", "/docking/status", timeout=1.0, attempts=1)
            st = st if s == 200 and isinstance(st, dict) else {}
            key = (st.get("state"), st.get("phase"), st.get("error"))
            if key != last:
                seen.append({"t": round(self.r.now() - t0, 1), "state": key[0], "phase": key[1], "error": key[2]})
                last = key
            if key[0] in DOCK_END:
                final = key[0]
                break
            self.r.sleep(0.5)
        self.summary["bay_dock"].update(transitions=seen, final=final)
        self.phase("dock", final=final, transitions=len(seen))
        if final is None:
            raise Abort(f"dock still running after {DOCK_TIMEOUT_S:.0f} s: cancelled")
        if final == "DOCKED":
            self.dock_active = False
        return final

    def undo_motion(self):
        """Before the base cleanup: every step runs; the base cleanup then does IDLE and the hold."""
        steps = []
        if self.dock_active:
            steps.append(("dock cancel", lambda: self.post("/docking/cancel")))
        if self.measuring:
            steps.append(("approval cancel", lambda: self.post("/navigation/approval/cancel")))
        steps.append(("teleop 0", lambda: self.post("/teleop", {"linear": 0.0, "angular": 0.0})))
        for name, fn in steps:
            try:
                status = fn()[0]
                self.phase(f"cleanup:{name}", status=status)
                if status not in (200, 204):
                    raise Abort(f"HTTP {status}")
            except BaseException as exc:   # noqa: B036 - the next undo must still run
                self.summary["errors"].append(f"{name}: {exc or type(exc).__name__}")
                log(f"!!! CLEANUP FAILED {name}: {exc or type(exc).__name__}")

    def execute(self):
        previous = signal.signal(signal.SIGTERM, _sigterm)
        code, final = 2, None
        try:
            for name in ("preflight", "refresh_approval", "navigation_start", "line_view", "dock_register", "dock"):
                self.step = name
                final = getattr(self, name)()
            self.summary["outcome"] = f"completed ({final})"
            code = 0 if final == "DOCKED" else 1
        except BaseException as exc:   # noqa: B036 - Ctrl-C/SIGTERM end in cleanup too
            self.summary["outcome"] = f"aborted at {self.step}: {exc or type(exc).__name__}"
            log("ABORT", self.summary["outcome"])
        finally:
            signal.signal(signal.SIGTERM, previous)
            if self.held:
                self.undo_motion()
                self.cleanup()
            if self.summary["errors"]:
                self.summary["outcome"] = f"CLEANUP FAILED ({self.summary['outcome']})"
                code = 2
            if self.args.remove_dock and self.step not in ("start", "preflight"):
                self.r.core.call("DELETE", f"/docking/docks/{self.args.dock_id}")
            self.write_summary()
            (self.ev / "summary.json").write_text(json.dumps(sanitize(json.loads(json.dumps(self.summary, default=str))),
                                                             indent=2, ensure_ascii=False), encoding="utf-8")
        return code


def main(argv=None, robot=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--robot", required=True)
    ap.add_argument("--host")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--token-file", default=os.environ.get("ROSY_CORE_OPERATOR_TOKEN_FILE"))
    ap.add_argument("--ca-file")
    ap.add_argument("--insecure", action="store_true")
    ap.add_argument("--site-url", default=os.environ.get("ROSY_SITE_URL"))
    ap.add_argument("--site-ca-file")
    ap.add_argument("--site-insecure", action="store_true")
    ap.add_argument("--overhead-source")
    ap.add_argument("--peer-check-ok", default="", help="what the agent checked: ListAgents result, Fleet view")
    ap.add_argument("--bay-verdict", required=True, help="JSON: bay_id, judged_by, in_bay_line, rear_toward_bay, cable_absent")
    ap.add_argument("--dock-id", required=True)
    ap.add_argument("--remove-dock", action="store_true", help="delete the dock record when the run ends")
    ap.add_argument("--evidence-dir")
    ap.add_argument("--summary-dir")
    args = ap.parse_args(argv)
    args.host = args.host or f"{args.robot}.local"
    if robot is None and (not args.token_file or not (args.ca_file or args.insecure)):
        ap.error("pass --token-file (or ROSY_CORE_OPERATOR_TOKEN_FILE) and --ca-file or --insecure")
    stamp = dt.datetime.now().strftime("%Y-%m-%d")
    base = os.environ.get("ROSY_SCRATCH") or os.environ.get("TEMP") or "/tmp"
    args.evidence_dir = args.evidence_dir or f"{base}/device-test/bay-dock-{stamp}-{time.strftime('%H%M%S')}"
    args.summary_dir = args.summary_dir or str(REPO / "docs" / "validation" / f"bay-dock-{stamp}")
    return BayDock(robot or Live(args), args, args.evidence_dir).execute()


if __name__ == "__main__":
    sys.exit(main())