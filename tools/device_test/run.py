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
import signal
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "capture"))
import edge_drive  # noqa: E402  (Core, tls_context, rec_start/rec_stop, front_frame, advisory)
from core_common.robot_body import PINKY_PRO  # noqa: E402  (edge_drive put contracts/foundation on sys.path)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tether  # noqa: E402
from live_transport import Live  # noqa: E402
from plan_rules import (OVERLAY_PATH, VERDICT_KEYS, check_verdict, flatten, load_plan,  # noqa: E402
                        merge, sanitize, sha)

UPDATER = "sudo -n python3 /opt/rosy/native-runtime/rosy_auto_update.py"
HOLDER = "agent-device-test"
MARKER = "RESTORE_PENDING.json"
PHASES = ("peers", "identity", "health", "camera", "verdict", "hold", "overlay", "localized",
          "record", "start", "stream")
LOOP_CALL_S = 0.25           # per loop call, one attempt: hold + status + state (+ events) <= ~1 s
STATE_FAILS_MAX = 5          # consecutive failed /robot/state at 10 Hz = 0.5 s of unknown pose/estop
PRECHECK_BUSY = 3            # rosy_auto_update.py PRECHECK_BUSY_EXIT: reasons were printed
VALIDATE = ("sudo -n python3 -c 'import sys,yaml,hashlib,json; b=open(sys.argv[1],\"rb\").read(); "
            "print(hashlib.sha256(b).hexdigest()); print(json.dumps(yaml.safe_load(b.decode(\"utf-8\")), "
            "sort_keys=True))' ")


Abort = tether.Abort


log = edge_drive.log


def _sigterm(_signum, _frame):
    raise KeyboardInterrupt("SIGTERM")


# --- phases --------------------------------------------------------------------------------

class Run:
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

    # -- changes (each undone in cleanup) --
    def hold(self):
        if self.hold_state() == "ours":
            raise Abort(f"hold by {HOLDER} already on the robot (an earlier run of this tool? use --restore)")
        self.marker(held=True)               # written before the first robot write
        self.held = True
        rc, out = self.sh(f"{UPDATER} hold --holder {HOLDER} --reason {self.plan['topic']} --hours 1")
        if rc != 0:
            raise Abort(f"update hold refused: {out.strip()}")
        self.phase("hold", holder=HOLDER)

    def read_overlay(self):
        p = self.plan["overlay_path"]
        rc, out = self.r.ssh(f"if sudo -n test -e {p}; then sudo -n cat {p}; else exit 3; fi")
        if rc == 3:
            return b""
        if rc != 0:
            raise Abort(f"cannot read {p} (rc {rc})")
        return out

    def write_overlay(self, data):
        """Atomic: temp file, validated on the robot (digest + parsed content), then mv. An existing
        directory and file keep their owner and mode; only a new one is created for rosy-core."""
        p = self.plan["overlay_path"]
        d, t = p.rsplit("/", 1)[0], p + ".device-test.tmp"
        if not data:
            rc, _ = self.sh(f"sudo -n rm -f {p}")
            if rc != 0:
                raise Abort(f"overlay remove failed (rc {rc})")
            return
        rc, out = self.sh(f"(sudo -n test -d {d} || sudo -n install -d -o rosy-core -g rosy-core -m 0750 {d})"
                          f" && sudo -n tee {t} >/dev/null && {VALIDATE}{t}", stdin=data)
        lines = out.strip().splitlines()
        want = [hashlib.sha256(data).hexdigest(), json.dumps(yaml.safe_load(data.decode("utf-8")), sort_keys=True)]
        if rc != 0 or lines[-2:] != want:
            self.sh(f"sudo -n rm -f {t}")
            raise Abort(f"overlay temp file did not validate on the robot (rc {rc})")
        rc, _ = self.sh(f"if sudo -n test -e {p}; then sudo -n chown --reference={p} {t} && "
                        f"sudo -n chmod --reference={p} {t}; else sudo -n chown rosy-core:rosy-core {t}; fi"
                        f" && sudo -n mv -f {t} {p}")
        if rc != 0:
            raise Abort(f"overlay replace failed (rc {rc})")

    def core_proc(self):
        _rc, out = self.sh("pid=$(systemctl show -p MainPID --value rosy-core); echo pid=$pid; "
                           "echo active=$(systemctl is-active rosy-core); "
                           "sudo -n cat /proc/$pid/environ 2>/dev/null | tr '\\0' '\\n' | grep -E '^(HOME|ROSY_CONFIG)='; "
                           "j=$(sudo -n journalctl -u rosy-core _PID=$pid --no-pager -o cat) && echo errors=$(printf '%s\\n' "
                           "\"$j\" | grep -ciE 'ConfigError|ValueError|refus') || echo 'errors=?'")
        return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)

    def restart_core(self):
        """Restart CORE and show the new process reads overlay_path without a config error.
        CORE has no endpoint for effective line_follow config; the process env, its journal and
        a steady PID are the readback (D-512 decision 6)."""
        before = self.core_proc().get("pid")
        if self.sh("sudo -n systemctl restart rosy-core")[0] != 0:
            raise Abort("systemctl restart rosy-core failed")
        t0 = self.r.now()
        while True:
            self.r.sleep(2.0)
            proc = self.core_proc()
            if proc.get("active") == "active" and proc.get("pid") not in (None, "0", before) \
                    and self.r.core.call("GET", "/robot/state")[0] == 200:
                break
            if self.r.now() - t0 > 90:
                raise Abort(f"CORE not ready 90 s after the overlay change (active={proc.get('active')}, "
                            f"config errors in its journal: {proc.get('errors')})")
        if proc.get("errors") != "0":
            raise Abort(f"CORE journal shows config errors or could not be read (errors={proc.get('errors')})")
        reads = proc.get("ROSY_CONFIG") or (proc.get("HOME", "") + "/.rosy/rosy.yaml")
        if reads != self.plan["overlay_path"]:
            raise Abort(f"CORE reads {reads}, not {self.plan['overlay_path']}")
        self.r.sleep(5.0)
        again = self.core_proc()
        if again.get("pid") != proc.get("pid") or again.get("active") != "active" or again.get("errors") != "0":
            raise Abort(f"CORE not steady after restart (pid {proc.get('pid')} -> {again.get('pid')}, "
                        f"config errors {again.get('errors')})")

    def overlay(self):
        if not self.plan["overlay"]:
            return
        p = self.plan["overlay_path"]
        before = self.read_overlay()
        (self.ev / "overlay_before.yaml").write_bytes(before)
        backup = None
        if before:
            backup = f"{p}.bak-{int(self.r.now())}"
            if self.sh(f"sudo -n cp -a {p} {backup}")[0] != 0:
                raise Abort("robot-side overlay backup failed")
        self.marker(overlay_touched=True, original_present=bool(before), backup=backup,
                    original_sha=sha(self.ev / "overlay_before.yaml"))
        self.original_overlay = before
        new = merge(yaml.safe_load(before.decode("utf-8")) or {}, self.plan["overlay"])
        data = yaml.safe_dump(new, sort_keys=True, allow_unicode=True).encode("utf-8")
        self.marker(applied_sha="sha256:" + hashlib.sha256(data).hexdigest())
        self.write_overlay(data)
        self.restart_core()
        back = flatten(yaml.safe_load(self.read_overlay().decode("utf-8")) or {})
        wrong = {k: back.get(k) for k, v in flatten(self.plan["overlay"]).items() if back.get(k) != v}
        if wrong:
            raise Abort(f"overlay readback mismatch: {wrong}")
        self.phase("overlay", applied=flatten(self.plan["overlay"]), path=p, backup=backup)

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

    # -- always --
    def _core_ok(self, what, result):
        if result[0] not in (200, 204):
            raise Abort(f"{what} -> HTTP {result[0]}")
        return result[0]

    def stop_recording(self):
        edge_drive.rec_stop(self.r.core)
        s, b = self.r.core.call("GET", "/recordings/active")
        if s != 200 or not isinstance(b, dict):
            raise Abort(f"recorder state unknown (HTTP {s})")      # unreachable is not idle
        state = (b.get("active") or {}).get("state")
        if state not in ("idle", None):
            raise Abort(f"recorder still {state}")
        return "stopped"

    def revert(self):
        self.write_overlay(self.original_overlay)
        if self.read_overlay() != self.original_overlay:
            raise Abort("overlay revert readback differs from the original bytes")
        self.restart_core()
        return "restored byte for byte"

    def hold_state(self):
        """"ours" only on exact "hold by agent-device-test:", else "none"; Abort on anything unclear.
        TOCTOU before release-hold remains: the D-412 updater (not ours) has no release-by-holder."""
        rc, out = self.sh(f"{UPDATER} precheck")
        if rc not in (0, PRECHECK_BUSY):
            raise Abort(f"precheck failed (rc {rc}): hold state unknown")
        ours = f"hold by {HOLDER}:"
        rest = out.replace(ours, "")
        if any(k in rest for k in ("hold by ", "hold.json", "claim held by")):
            raise Abort(f"foreign or unclear hold/claim on the robot: {out.strip()[:200]}")
        return "ours" if ours in out else "none"

    def release_hold(self):
        if self.hold_state() == "none":
            return "no hold left"
        rc, out = self.sh(f"{UPDATER} release-hold")
        if rc != 0:
            raise Abort(f"release-hold rc {rc}: {out.strip()[:200]}")
        return "released"

    def cleanup(self):
        """Every step runs (BaseException per step); signals are ignored until it is done.
        The hold is released only after a verified overlay restore; otherwise the marker stays."""
        previous = {s: signal.signal(s, signal.SIG_IGN) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            steps = []
            if self.started:
                steps.append(("line-follow OFF", lambda: self._core_ok(
                    "line-follow OFF", self.r.core.call("PUT", "/line-follow/mode", {"mode": "OFF"}))))
            if self.held:    # before the hold the robot may be a peer's: leave it alone
                steps.append(("IDLE", lambda: self._core_ok(
                    "IDLE", self.r.core.call("POST", "/mode", {"mode": "IDLE"}))))
            if self.recording:
                steps.append(("recording stop", self.stop_recording))
            if self.original_overlay is not None:
                steps.append(("overlay revert", self.revert))
            failed = set()
            for name, fn in steps + [("hold release", self.release_hold)] * self.held:
                if name == "hold release" and "overlay revert" in failed:
                    msg = "hold KEPT: overlay restore not verified; fix the robot, then run --restore"
                    self.summary["errors"].append(msg)
                    log("!!!", msg)
                    continue
                try:
                    self.phase(f"cleanup:{name}", result=fn())
                except BaseException as exc:   # noqa: B036 - a second Ctrl-C must not skip the next undo
                    failed.add(name)
                    self.summary["errors"].append(f"{name}: {exc or type(exc).__name__}")
                    log(f"!!! CLEANUP FAILED {name}: {exc or type(exc).__name__}")
            if not self.summary["errors"]:
                (self.ev / MARKER).unlink(missing_ok=True)
            if self.held:
                try:
                    self.camera("after")
                except BaseException as exc:   # noqa: B036
                    log(f"after frames failed: {exc}")
        finally:
            for s, h in previous.items():
                signal.signal(s, h)

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

    def write_summary(self):
        out = Path(self.args.summary_dir)
        out.mkdir(parents=True, exist_ok=True)
        self.summary["evidence_dir"] = str(self.ev)
        self.summary["evidence"] = {p.name: sha(p) for p in sorted(self.ev.iterdir()) if p.is_file()}
        clean = sanitize(json.loads(json.dumps(self.summary, default=str)))   # values, not the JSON text
        text = json.dumps(clean, indent=2, ensure_ascii=False)
        (out / "summary.json").write_text(text, encoding="utf-8")
        readme = out / "README.md"
        if not readme.exists():
            readme.write_text(
                f"# {self.plan['topic']} ({self.args.robot})\n\n"
                f"결과: {sanitize(self.summary['outcome'])}\n\n"
                "`summary.json`이 단계, 관찰한 상태·사유·이벤트, 증거 파일의 `sha256:` 요약을 담는다. "
                f"원본 증거(프레임, `status.jsonl`, `events.jsonl`)는 `{self.ev}`에 있다. D-512.\n\n"
                "## 판단\n\n(에이전트가 프레임과 기록을 보고 적는다.)\n", encoding="utf-8")
        log("summary", out / "summary.json", self.summary["outcome"])


def restore(robot, args):
    """--restore EVIDENCE_DIR: line-follow OFF, IDLE, overlay restore + readback, hold release,
    from RESTORE_PENDING.json. The marker goes only when all of it is verified."""
    ev = Path(args.restore)
    m = json.loads((ev / MARKER).read_text(encoding="utf-8"))
    if m["robot"] != args.robot:
        raise SystemExit(f"marker is for {m['robot']}, not {args.robot}")
    if m.get("overlay_path") != OVERLAY_PATH:
        raise SystemExit(f"marker overlay_path {m.get('overlay_path')!r} is not {OVERLAY_PATH}; restore by hand")
    run = Run(robot, {"topic": m["topic"], "overlay_path": OVERLAY_PATH, "overlay": {}}, args, ev)
    run.identity()
    # Read-only checks first: act only while the robot is still as this run left it.
    try:
        hold = run.hold_state()
    except Abort as exc:
        raise SystemExit(f"{exc}; nothing sent") from exc
    mode = run.get("/line-follow").get("mode")
    if mode not in ("OFF", None):
        raise SystemExit(f"line-follow is {mode}: someone is driving; nothing sent")
    if m.get("overlay_touched"):
        original = ev / "overlay_before.yaml"
        if sha(original) != m["original_sha"]:
            raise SystemExit("overlay_before.yaml does not match the marker digest; restore by hand")
        now = "sha256:" + hashlib.sha256(run.read_overlay()).hexdigest()
        if now not in (m.get("applied_sha"), m["original_sha"]):
            raise SystemExit("the robot overlay changed since this run wrote it; nothing sent, restore by hand")
        run.original_overlay = original.read_bytes()
    run.held = bool(m.get("held")) and hold == "ours"
    run.cleanup()
    result = {"restored_at": robot.now(), "errors": run.summary["errors"], "phases": run.summary["phases"]}
    (ev / "restore_result.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    if run.summary["errors"]:
        log("!!! RESTORE FAILED:", run.summary["errors"])
        return 2
    log("restore verified; marker removed")
    return 0


def dry_run(plan, args):
    print(f"DRY RUN {plan['topic']} on {args.robot} ({args.host}); no network, no SSH")
    for name in PHASES:
        print(" -", name)
    print("overlay", plan["overlay_path"], json.dumps(flatten(plan["overlay"])))
    print("stop", json.dumps(plan["stop"]), "expect", json.dumps(plan.get("expect", {})))
    print("cleanup: OFF, IDLE, recording stop, overlay restore + readback + CORE check, hold release, after frames")
    return 0


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
    args.evidence_dir = args.evidence_dir or f"X:/DevTemp/device-test/{plan['topic']}-{stamp}-{time.strftime('%H%M%S')}"
    args.summary_dir = args.summary_dir or str(REPO / "docs" / "validation" / f"{plan['topic']}-{stamp}")
    if args.dry_run:
        return dry_run(plan, args)
    if not (args.preflight_only or args.camera_verdict):
        ap.error("pass --preflight-only first, then --camera-verdict FILE")
    return Run(robot or Live(args), plan, args, args.evidence_dir).execute(preflight_only=args.preflight_only)


if __name__ == "__main__":
    sys.exit(main())
