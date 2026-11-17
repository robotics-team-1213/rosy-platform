"""Agent-run supervised device test on a real Pinky (D-512).

    run.py --robot rosy-pinky-9dfk --plan PLAN.yaml --token-file FILE (--ca-file CA | --insecure)
           --site-url URL (--site-ca-file CA | --site-insecure) --peer-check-ok "EVIDENCE"
           (--preflight-only | --camera-verdict VERDICT.json) [--dry-run]
    run.py --robot rosy-pinky-9dfk --token-file FILE (--ca-file CA | --insecure) --restore EVIDENCE_DIR

--preflight-only saves frames and a verdict template and changes nothing; --camera-verdict
runs the test; --restore finishes the undo of a run that died (RESTORE_PENDING.json).
Order, abort rules, tether guard (tether.py) and undo: tools/device_test/AGENTS.md, ADR D-512.
CORE is the motion authority when this loop stalls (line-follow hold session <= 1 s, D-422
body stop, teleop watchdog); loop calls make one short attempt each. SIGTERM handling is best
effort: a Windows kill runs no handler, so only RESTORE_PENDING.json and --restore help then.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import time

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "capture"))
import edge_drive  # noqa: E402  (Core, tls_context, rec_start/rec_stop, front_frame, advisory)
from core_common.robot_body import PINKY_PRO  # noqa: E402  (edge_drive put contracts/foundation on sys.path)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tether  # noqa: E402
from live_transport import Live  # noqa: E402
from plan_rules import (OVERLAY_PATH, VERDICT_KEYS, check_verdict, flatten, load_plan,  # noqa: E402, F401
                        merge, sanitize, sha)
from run_helpers import (  # noqa: E402, F401
    HOLDER,
    LOOP_CALL_S,
    MARKER,
    PHASES,
    PRECHECK_BUSY,
    STATE_FAILS_MAX,
    UPDATER,
    VALIDATE,
    Abort,
    RunOverlayAndCleanupMixin,
    _sigterm,
    dry_run,
    log,
    restore_with_run,
)


# --- phases --------------------------------------------------------------------------------

class Run(RunOverlayAndCleanupMixin):
    def __init__(self, robot, plan, args, evidence):
        self.r, self.plan, self.args, self.ev = robot, plan, args, Path(evidence)
        self.ev.mkdir(parents=True, exist_ok=True)
        self.summary = {"topic": plan["topic"], "robot": args.robot, "plan": plan, "phases": [],
                        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                        "peer_check": args.peer_check_ok, "outcome": "not started", "errors": []}
        self.original_overlay = None     # bytes, or b"" when there was no file; None = untouched
        self.held = self.recording = self.started = False

    def phase(self, name, **info):
        self.summary["phases"].append({"phase": name, "t": round(self.r.now(), 2), **info})
        log(f"[{name}]", json.dumps(info, ensure_ascii=False, default=str)[:300])

    def get(self, path):
        s, b = self.r.core.call("GET", path)
        if s != 200 or not isinstance(b, dict):
            raise Abort(f"GET {path} -> {s}")
        return b

    def sh(self, command, stdin=b""):
        rc, out = self.r.ssh(command, stdin)
        return rc, out.decode("utf-8", "replace")

    def marker(self, **fields):
        path = self.ev / MARKER
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
            "robot": self.args.robot, "host": self.args.host, "topic": self.plan["topic"],
            "overlay_path": self.plan["overlay_path"], "hold_owner": HOLDER, "held": False,
            "overlay_touched": False, "created_at": self.r.now()}
        data.update(fields)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # -- read-only checks --
    def peers(self):
        if not (self.args.peer_check_ok or "").strip():
            raise Abort("no --peer-check-ok: check ListAgents for peers driving this robot first")
        self.phase("peers", evidence=self.args.peer_check_ok)

    def identity(self):
        rc, host = self.sh("hostname")
        info = self.get("/system/info")
        if rc != 0 or host.strip() != self.args.robot:
            raise Abort(f"identity: ssh hostname {host.strip()!r} is not {self.args.robot}")
        self.phase("identity", hostname=host.strip(), robot_id=info.get("robot_id"),
                   robot_name=info.get("robot_name"))

    @staticmethod
    def not_localized(st):
        """D-395: CAMERA_LINE needs LOCALIZED with a map pose; null localization = pre-D-395 robot."""
        loc = st.get("localization")
        if isinstance(loc, dict) and (loc.get("state") != "LOCALIZED" or loc.get("pose_frame") == "odom"):
            return f"not localized ({loc.get('state')}, {loc.get('pose_frame')})"
        return None

    def health(self):
        rc, active = self.sh("systemctl is-active rosy-core")
        st, lf = self.get("/robot/state"), self.get("/line-follow")
        pct = (st.get("battery") or {}).get("percent")
        why = [w for w, bad in (
            (f"rosy-core {active.strip()}", active.strip() != "active"),
            ("offline", st.get("online") is False),
            ("estop", (st.get("safety") or {}).get("estop")),
            (f"battery {pct}% < {self.plan['min_battery_percent']}%",
             pct is None or pct < self.plan["min_battery_percent"]),
            (f"line-follow already {lf.get('mode')} (someone else is driving)", lf.get("mode") not in ("OFF", None)),
            (self.not_localized(st), self.not_localized(st)),
        ) if bad]
        if why:
            raise Abort("health: " + "; ".join(why))
        self.phase("health", battery_percent=pct, mode=st.get("mode"), pose=st.get("pose"),
                   localization=(st.get("localization") or {}).get("state"))
        return st

    def localized(self):
        why = self.not_localized(self.get("/robot/state"))
        if why:
            raise Abort(f"after the overlay restart: {why}")
        self.phase("localized")

    def camera(self, tag):
        """Save overhead + robot frames + one LiDAR scan; machine-check the body path (advisory)."""
        saved = {}
        for name, data in ((f"{tag}_overhead.jpg", self.r.overhead()),
                           (f"{tag}_front.jpg", edge_drive.front_frame(self.r.core)),
                           (f"{tag}_raw.jpg", self.r.core.raw_frame(timeout=3.0))):
            if data:
                (self.ev / name).write_bytes(data)
                saved[name] = sha(self.ev / name)
        s, scan = self.r.core.call("GET", "/sensors/lidar")
        body = None
        if s == 200 and isinstance(scan, dict):
            (self.ev / f"{tag}_lidar.json").write_text(json.dumps(scan), encoding="utf-8")
            deg, _src = edge_drive.lidar_forward_deg(self.args.robot)
            speed = float(flatten(self.plan["overlay"]).get("line_follow.cruise_speed", 0.08))
            body = edge_drive.advisory(PINKY_PRO.scan_view(scan, forward_deg=deg), speed, 1.0)
        self.phase(f"camera:{tag}", frames=saved, body=body)
        return saved

    def verdict(self, pose):
        try:
            v = check_verdict(self.args.camera_verdict, self.plan["verdict_max_age_s"], self.r.now(), pose)
            self.tether = tether.Guard(v, self.plan["tether_policy"], self.ev)
        except ValueError as exc:
            raise Abort(str(exc)) from exc
        self.phase("verdict", **{k: v.get(k) for k in (*VERDICT_KEYS, "note", "judged_by", "tether")},
                   accepted_risk="cable near the robot (user 2026-10-08)" if v["cable_seen"] else None)

    def start(self):
        s, b = self.r.core.call("PUT", "/line-follow/mode", {"mode": "CAMERA_LINE", "hold_s": self.plan["hold_s"]})
        self.started = True                  # OFF in cleanup even if CORE half-accepted
        if s != 200:
            raise Abort(f"CAMERA_LINE refused {s} {b}")
        self.phase("start", mode="CAMERA_LINE", hold_s=self.plan["hold_s"])

    def call(self, method, path, body=None):
        return self.r.core.call(method, path, body, timeout=LOOP_CALL_S, attempts=1)

    def stream(self):
        """CORE line-follow at 10 Hz with the hold deadman, events and pose every 0.5 s."""
        stop, seen = self.plan["stop"], {"states": {}, "reasons": {}, "events": {}}
        abort_reasons, abort_events = stop.get("abort_on_reasons", []), stop.get("abort_on_events", [])
        ok_still, ok_events = stop.get("ok_still_reasons", []), stop.get("ok_events", [])
        _, ev = self.r.core.call("GET", "/events?limit=1")
        since = ev.get("last_seq") if isinstance(ev, dict) else None
        t0 = last_ok = self.r.now()
        last_pose, dist, still_since, tick, end, state_fails = None, 0.0, None, 0, None, 0
        with open(self.ev / "status.jsonl", "a", encoding="utf-8") as sf, \
                open(self.ev / "events.jsonl", "a", encoding="utf-8") as ef:
            while end is None:
                now = self.r.now()
                hs, _ = self.call("POST", "/line-follow/hold")
                s, lf = self.call("GET", "/line-follow")
                lf = lf if isinstance(lf, dict) else {}
                sf.write(json.dumps({"t": round(now - t0, 2), "hold": hs, "status": s, **lf}) + "\n")
                state, reason = str(lf.get("state")), str(lf.get("reason"))
                seen["states"][state] = seen["states"].get(state, 0) + 1
                seen["reasons"][reason] = seen["reasons"].get(reason, 0) + 1
                if s == 200 and hs == 200:
                    last_ok = now
                if tick % 5 == 0:
                    _, page = self.call("GET", f"/events?since_seq={since or 0}&limit=200")
                    for e in page.get("events", []) if isinstance(page, dict) else []:
                        ef.write(json.dumps(e) + "\n")
                        since = max(since or 0, int(e.get("seq", 0)))
                        typ = str(e.get("type"))
                        seen["events"][typ] = seen["events"].get(typ, 0) + 1
                        if typ not in ok_events and any(fnmatch.fnmatch(typ, p) for p in abort_events):
                            raise Abort(f"event {typ}: {json.dumps(e.get('data'))[:200]}")
                ss, st = self.call("GET", "/robot/state")
                st = st if ss == 200 and isinstance(st, dict) else None
                state_fails = 0 if st else state_fails + 1
                if state_fails >= STATE_FAILS_MAX:
                    raise Abort(f"/robot/state failed {state_fails} times in a row: pose and estop unknown")
                pose = st.get("pose") if st and isinstance(st.get("pose"), dict) else None
                if st and (st.get("safety") or {}).get("estop"):
                    raise Abort("estop")
                if st and stop.get("max_distance_m") and pose is None:
                    raise Abort("pose unknown: the distance cap cannot be enforced")
                if pose and last_pose:
                    dist += math.hypot(pose["x"] - last_pose["x"], pose["y"] - last_pose["y"])
                last_pose = pose or last_pose
                self.tether.tick(st, self)   # trail.jsonl; tether limits, retrace and abort on a trip (D-512)
                if now - last_ok > 1.0:
                    raise Abort("CORE unreachable or hold refused for > 1 s")
                if any(p in reason for p in abort_reasons):
                    raise Abort(f"stop reason {reason}")
                if (self.ev / "STOP").exists():
                    raise Abort("operator STOP file")
                moving = abs(lf.get("linear") or 0) > 1e-3 or abs(lf.get("angular") or 0) > 1e-3
                still_since = None if moving else (still_since or now)
                if now - t0 >= float(stop["duration_s"]):
                    end = "duration"
                elif stop.get("max_distance_m") and dist >= float(stop["max_distance_m"]):
                    end = "distance"
                elif still_since and now - still_since > float(stop.get("still_s", 5)) and now - t0 > 3:
                    if reason not in ok_still:   # D-512 decision 5: an unexplained stop is suspected contact
                        raise Abort(f"stopped for {stop.get('still_s', 5)} s with reason {reason} "
                                    "(not in ok_still_reasons): suspected contact")
                    end = "still"
                tick += 1
                self.r.sleep(0.1)
        self.summary["observed"] = {**seen, "distance_m": round(dist, 3), "ticks": tick}
        self.phase("stream", end=end, distance_m=round(dist, 3), ticks=tick)
        return end

    def execute(self, preflight_only=False):
        previous = signal.signal(signal.SIGTERM, _sigterm)
        code = 2
        try:
            self.peers()
            self.identity()
            st = self.health()
            frames = self.camera("before" if preflight_only else "start")
            if preflight_only:
                template = {"captured_at": self.r.now(), "pose_at_capture": st.get("pose"), "frames": frames,
                            "localization_at_capture": st.get("localization"), **{k: None for k in VERDICT_KEYS},
                            "note": "", "judged_by": "", "tether": None, "map_id_at_capture": st.get("map_id")}
                path = self.ev / "camera_verdict.json"
                path.write_text(json.dumps(template, indent=2), encoding="utf-8")
                self.summary["outcome"] = "preflight"
                log(f"look at the frames in {self.ev}, fill {path} (judged_by too), "
                    f"then rerun with --camera-verdict {path}")
                return 0
            self.verdict(st.get("pose"))
            self.hold()
            self.overlay()
            self.localized()
            self.recording = True      # a half-started recorder is stopped too
            edge_drive.rec_start(self.r.core)
            self.phase("record")
            self.start()
            end = self.stream()
            expected = self.plan.get("expect", {})
            missing = [f"{kind}:{x}" for kind in ("states", "reasons", "events")
                       for x in expected.get(kind, []) if not self.summary["observed"][kind].get(x)]
            self.summary["missing_expected"] = missing
            self.summary["outcome"] = f"completed ({end})" + (f", missing {missing}" if missing else "")
            code = 0 if not missing else 1
        except BaseException as exc:   # noqa: B036 - Ctrl-C/SIGTERM/SystemExit end in cleanup too
            self.summary["outcome"] = f"aborted: {exc or type(exc).__name__}"
            log("ABORT", exc or type(exc).__name__)
            code = 2
        finally:
            signal.signal(signal.SIGTERM, previous)
            if not preflight_only:
                self.cleanup()
            if self.summary["errors"]:
                self.summary["outcome"] = f"CLEANUP FAILED ({self.summary['outcome']})"
                code = 2
                log("!!! CLEANUP FAILED - the robot may still carry the test overlay or hold. Errors:",
                    self.summary["errors"])
                if (self.ev / MARKER).exists():
                    log(f"!!! then run: run.py --robot {self.args.robot} ... --restore {self.ev}")
            self.write_summary()
        return code


def restore(robot, args):
    return restore_with_run(robot, args, Run)


def main(argv=None, robot=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--robot", required=True, help="robot hostname, e.g. rosy-pinky-9dfk")
    ap.add_argument("--host", help="address (default <robot>.local)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--plan")
    ap.add_argument("--token-file", default=os.environ.get(edge_drive.TOKEN_ENV))
    ap.add_argument("--ca-file")
    ap.add_argument("--insecure", action="store_true")
    ap.add_argument("--site-url", default=os.environ.get("ROSY_SITE_URL"), help="site Fleet URL (env ROSY_SITE_URL)")
    ap.add_argument("--site-ca-file")
    ap.add_argument("--site-insecure", action="store_true")
    ap.add_argument("--overhead-source", help="Vision source id (default: the first one)")
    ap.add_argument("--peer-check-ok", default="", help="what the agent checked: ListAgents result, Fleet view")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--camera-verdict")
    mode.add_argument("--restore", metavar="EVIDENCE_DIR", help=f"undo a run that died, from its {MARKER}")
    mode.add_argument("--tether-check", metavar="VERDICT", help="draw the declared tether (tether.py); lamp blink only")
    ap.add_argument("--evidence-dir")
    ap.add_argument("--summary-dir")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    args.host = args.host or f"{args.robot}.local"
    if robot is None and not args.dry_run:
        if not args.token_file or not (args.ca_file or args.insecure):
            ap.error(f"pass --token-file (or {edge_drive.TOKEN_ENV}) and --ca-file or --insecure")
    if args.restore or args.tether_check:
        return (restore if args.restore else tether.tether_check)(robot or Live(args), args)
    if not args.plan:
        ap.error("--plan is required")
    plan = load_plan(args.plan)
    stamp = dt.datetime.now().strftime("%Y-%m-%d")
    args.evidence_dir = args.evidence_dir or f"{os.environ.get('ROSY_SCRATCH') or os.environ.get('TEMP') or '/tmp'}/device-test/{plan['topic']}-{stamp}-{time.strftime('%H%M%S')}"
    args.summary_dir = args.summary_dir or str(REPO / "docs" / "validation" / f"{plan['topic']}-{stamp}")
    if args.dry_run:
        return dry_run(plan, args)
    if not (args.preflight_only or args.camera_verdict):
        ap.error("pass --preflight-only first, then --camera-verdict FILE")
    return Run(robot or Live(args), plan, args, args.evidence_dir).execute(preflight_only=args.preflight_only)


if __name__ == "__main__":
    sys.exit(main())
