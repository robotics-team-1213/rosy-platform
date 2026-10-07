"""Agent-run supervised device test on a real Pinky (D-512).

    run.py --robot rosy-pinky-9dfk --plan PLAN.yaml --token-file FILE (--ca-file CA | --insecure)
           --site-url URL (--site-ca-file CA | --site-insecure) --peer-check-ok "EVIDENCE"
           [--preflight-only | --camera-verdict VERDICT.json] [--dry-run]

Two calls per test. First --preflight-only: identity, health, camera frames and a
verdict template under the evidence directory; nothing moves, nothing changes. The
agent looks at the frames, fills the template and runs again with --camera-verdict.
The second call checks the verdict (age, robot not moved since the frames), holds the
robot's automatic update, applies the plan's temporary CORE overlay with readback,
records (D-379), runs CAMERA_LINE under a hold deadman while it writes CORE status at
10 Hz and events to JSONL, and stops on time, distance, stillness, an abort reason or
event, a STOP file in the evidence directory, or Ctrl-C. Whatever happens, the finally
block turns line-follow OFF, sets IDLE, stops the recording, restores the overlay byte
for byte (readback), releases the hold and saves after-frames. summary.json and a
README stub go to docs/validation/<topic>-<date>/ with sha256: digests of the raw
evidence, which stays outside the public repo (default X:/DevTemp/device-test/...).

CORE's own safety stays on: D-422 body stop, the teleop watchdog, the IR guard as the
plan sets it, and the plan's speed must stay under MAX_LINEAR. --dry-run validates the
plan and prints the phases without any network or SSH call.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "capture"))
import edge_drive  # noqa: E402  (Core, tls_context, rec_start/rec_stop, front_frame, advisory)
from core_common.robot_body import PINKY_PRO  # noqa: E402  (edge_drive put contracts/foundation on sys.path)

MAX_LINEAR = 0.10            # m/s, rosy_default.yaml line_follow.max_linear (host default)
OVERLAY_PATH = "/var/lib/rosy/core/.rosy/rosy.yaml"   # rosy-core.service HOME (D-189 D3)
HOLDER = "agent-device-test"
PHASES = ("peers", "identity", "health", "camera", "verdict", "hold", "overlay", "record",
          "start", "stream")
SAFE = re.compile(r"^[A-Za-z0-9_./-]+$")
VERDICT_KEYS = ("robot_at_start", "robot_seen_is_target", "path_clear", "cable_seen",
                "cable_in_path_or_wheels")


class Abort(RuntimeError):
    pass


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sha(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- plan ----------------------------------------------------------------------------------

def flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(flatten(v, f"{prefix}{k}."))
        else:
            out[prefix + k] = v
    return out


def merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = merge(out.get(k) or {}, v) if isinstance(v, dict) else v
    return out


def load_plan(path):
    plan = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or not re.fullmatch(r"[a-z0-9-]+", str(plan.get("topic", ""))):
        raise SystemExit("plan needs topic: lower-case words joined by '-'")
    plan.setdefault("overlay", {})
    plan.setdefault("overlay_path", OVERLAY_PATH)
    if not SAFE.match(plan["overlay_path"]):
        raise SystemExit("overlay_path has characters a remote shell would interpret")
    flat = flatten(plan["overlay"])
    for key in ("line_follow.cruise_speed", "line_follow.max_linear"):
        if key in flat and not 0 < float(flat[key]) <= MAX_LINEAR:
            raise SystemExit(f"{key} {flat[key]} outside (0, {MAX_LINEAR}] m/s")
    stop = plan.setdefault("stop", {})
    if not 0 < float(stop.get("duration_s", 0)) <= 600:
        raise SystemExit("stop.duration_s must be in (0, 600]")
    plan.setdefault("min_battery_percent", 40)
    plan.setdefault("verdict_max_age_s", 300)
    plan.setdefault("hold_s", 1.0)
    return plan


# --- live robot ----------------------------------------------------------------------------

class Live:
    """The real transports: CORE over one kept-alive HTTPS connection (edge_drive.Core),
    key-only SSH as rosy (rosy-device-access skill) and the site Vision lease."""

    def __init__(self, args):
        self.core = edge_drive.Core(args.host, Path(args.token_file).read_text(encoding="utf-8").strip(),
                                    args.port, edge_drive.tls_context(args.ca_file, args.insecure))
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Rosy"
        self.ssh_argv = ["ssh", "-i", str(base / "ssh" / "rosy-operator-ed25519"), "-o", "IdentitiesOnly=yes",
                         "-o", "BatchMode=yes", "-o", "PasswordAuthentication=no",
                         "-o", "KbdInteractiveAuthentication=no", "-o", "StrictHostKeyChecking=accept-new",
                         "-o", f"UserKnownHostsFile={base / 'known_hosts'}", "-o", "ConnectTimeout=5",
                         f"rosy@{args.host}"]
        self.site_url, self.source = args.site_url, args.overhead_source
        self.site_ctx = edge_drive.tls_context(args.site_ca_file, args.site_insecure) if args.site_url else None

    def ssh(self, command, stdin=b""):
        p = subprocess.run(self.ssh_argv + [command], input=stdin, capture_output=True, timeout=120)
        return p.returncode, p.stdout.decode("utf-8", "replace")

    def _site(self, path, body=None, token=None):
        req = urllib.request.Request(self.site_url.rstrip("/") + path, method="POST" if body else "GET",
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": "Bearer " + token} if token else {})})
        with urllib.request.urlopen(req, timeout=5, context=self.site_ctx) as r:
            return r.read()

    def overhead(self):
        """One fresh Rosy Cam JPEG through a 60 s Viewer lease (D-318), None on any failure."""
        if not self.site_url:
            return None
        try:
            source = self.source or json.loads(self._site("/api/fleet/vision/sources"))["sources"][0]
            lease = json.loads(self._site("/api/fleet/vision/lease", {"source_id": source}))
            return self._site(lease["frame_path"], token=lease["lease"])
        except (OSError, ValueError, KeyError, IndexError):
            return None

    now = staticmethod(time.time)
    sleep = staticmethod(time.sleep)


# --- phases --------------------------------------------------------------------------------

class Run:
    def __init__(self, robot, plan, args, evidence):
        self.r, self.plan, self.args, self.ev = robot, plan, args, Path(evidence)
        self.ev.mkdir(parents=True, exist_ok=True)
        self.summary = {"topic": plan["topic"], "robot": args.robot, "plan": plan, "phases": [],
                        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                        "peer_check": args.peer_check_ok, "outcome": None, "errors": []}
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

    # -- read-only checks --
    def peers(self):
        if not (self.args.peer_check_ok or "").strip():
            raise Abort("no --peer-check-ok: check ListAgents for peers driving this robot first")
        self.phase("peers", evidence=self.args.peer_check_ok)

    def identity(self):
        rc, host = self.r.ssh("hostname")
        info = self.get("/system/info")
        if rc != 0 or host.strip() != self.args.robot:
            raise Abort(f"identity: ssh hostname {host.strip()!r} is not {self.args.robot}")
        self.phase("identity", hostname=host.strip(), robot_id=info.get("robot_id"),
                   robot_name=info.get("robot_name"))

    def health(self):
        rc, active = self.r.ssh("systemctl is-active rosy-core")
        st, lf = self.get("/robot/state"), self.get("/line-follow")
        pct = (st.get("battery") or {}).get("percent")
        why = [w for w, bad in (
            (f"rosy-core {active.strip()}", active.strip() != "active"),
            ("offline", st.get("online") is False),
            ("estop", (st.get("safety") or {}).get("estop")),
            (f"battery {pct}% < {self.plan['min_battery_percent']}%",
             pct is None or pct < self.plan["min_battery_percent"]),
            (f"line-follow already {lf.get('mode')} (someone else is driving)", lf.get("mode") not in ("OFF", None)),
        ) if bad]
        if why:
            raise Abort("health: " + "; ".join(why))
        self.phase("health", battery_percent=pct, mode=st.get("mode"), pose=st.get("pose"))
        return st

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
        """The agent's visual verdict on the preflight frames (D-512 decision 3)."""
        try:
            v = json.loads(Path(self.args.camera_verdict).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise Abort(f"camera verdict unreadable: {exc}") from exc
        missing = [k for k in VERDICT_KEYS if not isinstance(v.get(k), bool)]
        if missing:
            raise Abort(f"camera verdict: {missing} must be true/false")
        age = self.r.now() - float(v.get("captured_at", 0))
        if not 0 <= age <= self.plan["verdict_max_age_s"]:
            raise Abort(f"camera verdict is {age:.0f} s old (max {self.plan['verdict_max_age_s']} s)")
        was = v.get("pose_at_capture") or {}
        if pose and was and math.hypot(pose["x"] - was["x"], pose["y"] - was["y"]) > 0.05:
            raise Abort("robot moved since the judged frames; run --preflight-only again")
        if v["cable_in_path_or_wheels"]:
            raise Abort("camera verdict: cable in the planned path or the wheels")
        bad = [k for k in ("robot_at_start", "robot_seen_is_target", "path_clear") if not v[k]]
        if bad:
            raise Abort(f"camera verdict: {bad} false")
        self.phase("verdict", **{k: v[k] for k in VERDICT_KEYS}, note=v.get("note", ""),
                   accepted_risk="cable near the robot (user 2026-10-08)" if v["cable_seen"] else None)

    # -- changes (each undone in finally) --
    def hold(self):
        rc, out = self.r.ssh("sudo -n python3 /opt/rosy/native-runtime/rosy_auto_update.py precheck")
        if "hold by " in out or "claim held by" in out:
            raise Abort(f"peer conflict on the robot: {out.strip()}")
        rc, out = self.r.ssh(f"sudo -n python3 /opt/rosy/native-runtime/rosy_auto_update.py hold "
                             f"--holder {HOLDER} --reason {self.plan['topic']} --hours 1")
        if rc != 0:
            raise Abort(f"update hold refused: {out.strip()}")
        self.held = True
        self.phase("hold", holder=HOLDER)

    def read_overlay(self):
        p = self.plan["overlay_path"]
        rc, out = self.r.ssh(f"if sudo -n test -e {p}; then sudo -n cat {p}; else exit 3; fi")
        if rc == 3:
            return b""
        if rc != 0:
            raise Abort(f"cannot read {p} (rc {rc})")
        return out.encode("utf-8")

    def write_overlay(self, data):
        p, d = self.plan["overlay_path"], self.plan["overlay_path"].rsplit("/", 1)[0]
        if not data:
            rc, _ = self.r.ssh(f"sudo -n rm -f {p}")
        else:
            rc, _ = self.r.ssh(f"sudo -n install -d -o rosy-core -g rosy-core {d} && sudo -n tee {p} >/dev/null"
                               f" && sudo -n chown rosy-core:rosy-core {p} && sudo -n python3 -c "
                               f"'import sys,yaml; yaml.safe_load(open(sys.argv[1],encoding=\"utf-8\"))' {p}",
                               stdin=data)
        if rc != 0:
            raise Abort(f"overlay write failed (rc {rc})")
        self.restart_core()

    def restart_core(self):
        self.r.ssh("sudo -n systemctl restart rosy-core")
        t0 = self.r.now()
        while self.r.now() - t0 < 90:
            self.r.sleep(2.0)
            if self.r.ssh("systemctl is-active rosy-core")[1].strip() == "active" \
                    and self.r.core.call("GET", "/robot/state")[0] == 200:
                return
        raise Abort("CORE did not come back within 90 s after the overlay change")

    def overlay(self):
        if not self.plan["overlay"]:
            return
        before = self.read_overlay()
        (self.ev / "overlay_before.yaml").write_bytes(before)
        if before:
            self.r.ssh(f"sudo -n cp -a {self.plan['overlay_path']} {self.plan['overlay_path']}.bak-{int(self.r.now())}")
        self.original_overlay = before
        new = merge(yaml.safe_load(before.decode("utf-8")) or {}, self.plan["overlay"])
        self.write_overlay(yaml.safe_dump(new, sort_keys=True, allow_unicode=True).encode("utf-8"))
        back = flatten(yaml.safe_load(self.read_overlay().decode("utf-8")) or {})
        wrong = {k: back.get(k) for k, v in flatten(self.plan["overlay"]).items() if back.get(k) != v}
        if wrong:
            raise Abort(f"overlay readback mismatch: {wrong}")
        self.phase("overlay", applied=flatten(self.plan["overlay"]), path=self.plan["overlay_path"])

    def start(self):
        s, b = self.r.core.call("PUT", "/line-follow/mode", {"mode": "CAMERA_LINE", "hold_s": self.plan["hold_s"]})
        if s != 200:
            raise Abort(f"CAMERA_LINE refused {s} {b}")
        self.started = True
        self.phase("start", mode="CAMERA_LINE", hold_s=self.plan["hold_s"])

    def stream(self):
        """CORE line-follow at 10 Hz with the hold deadman, events and pose every 0.5 s."""
        stop, seen = self.plan["stop"], {"states": {}, "reasons": {}, "events": {}}
        abort_reasons, abort_events = stop.get("abort_on_reasons", []), stop.get("abort_on_events", [])
        _, ev = self.r.core.call("GET", "/events?limit=1")
        since = (ev or {}).get("last_seq") if isinstance(ev, dict) else None
        t0 = last_ok = self.r.now()
        last_pose, dist, still_since, tick, end = None, 0.0, None, 0, None
        with open(self.ev / "status.jsonl", "a", encoding="utf-8") as sf, \
                open(self.ev / "events.jsonl", "a", encoding="utf-8") as ef:
            while end is None:
                now = self.r.now()
                hs, _ = self.r.core.call("POST", "/line-follow/hold", timeout=0.8)
                s, lf = self.r.core.call("GET", "/line-follow", timeout=0.8)
                lf = lf if isinstance(lf, dict) else {}
                sf.write(json.dumps({"t": round(now - t0, 2), "hold": hs, "status": s, **lf}) + "\n")
                state, reason = str(lf.get("state")), str(lf.get("reason"))
                seen["states"][state] = seen["states"].get(state, 0) + 1
                seen["reasons"][reason] = seen["reasons"].get(reason, 0) + 1
                if s == 200 and hs == 200:
                    last_ok = now
                if tick % 5 == 0:
                    _, page = self.r.core.call("GET", f"/events?since_seq={since or 0}&limit=200", timeout=0.8)
                    for e in (page or {}).get("events", []) if isinstance(page, dict) else []:
                        ef.write(json.dumps(e) + "\n")
                        since = max(since or 0, int(e.get("seq", 0)))
                        typ = str(e.get("type"))
                        seen["events"][typ] = seen["events"].get(typ, 0) + 1
                        if any(fnmatch.fnmatch(typ, p) for p in abort_events):
                            raise Abort(f"event {typ}: {json.dumps(e.get('data'))[:200]}")
                    _, st = self.r.core.call("GET", "/robot/state", timeout=0.8)
                    st = st if isinstance(st, dict) else {}
                    pose = st.get("pose")
                    if (st.get("safety") or {}).get("estop"):
                        raise Abort("estop")
                    if pose and last_pose:
                        dist += math.hypot(pose["x"] - last_pose["x"], pose["y"] - last_pose["y"])
                    last_pose = pose or last_pose
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
                    end = "still"
                tick += 1
                self.r.sleep(0.1)
        self.summary["observed"] = {**seen, "distance_m": round(dist, 3), "ticks": tick}
        self.phase("stream", end=end, distance_m=round(dist, 3), ticks=tick)
        return end

    # -- always --
    def cleanup(self):
        steps = []
        if self.started:
            steps.append(("line-follow OFF", lambda: self.r.core.call("PUT", "/line-follow/mode", {"mode": "OFF"})))
        if self.held:    # before the hold the robot may be a peer's: leave it alone
            steps.append(("IDLE", lambda: self.r.core.call("POST", "/mode", {"mode": "IDLE"})))
        if self.recording:
            steps.append(("recording stop", lambda: edge_drive.rec_stop(self.r.core)))
        if self.original_overlay is not None:
            steps.append(("overlay revert", self.revert))
        if self.held:
            steps.append(("hold release", lambda: self.r.ssh(
                "sudo -n python3 /opt/rosy/native-runtime/rosy_auto_update.py release-hold")))
            steps.append(("after frames", lambda: self.camera("after")))
        for name, fn in steps:
            try:
                out = fn()
                self.phase(f"cleanup:{name}", result=out if isinstance(out, (tuple, str, type(None))) else "ok")
            except (Exception, SystemExit) as exc:   # one failed undo must not skip the next
                self.summary["errors"].append(f"{name}: {exc}")
                log(f"CLEANUP FAILED {name}: {exc}")

    def revert(self):
        self.write_overlay(self.original_overlay)
        back = self.read_overlay()
        if back != self.original_overlay:
            raise Abort("overlay revert readback differs from the original")
        return "restored byte for byte"

    def execute(self, preflight_only=False):
        try:
            self.peers()
            self.identity()
            st = self.health()
            frames = self.camera("before")
            if preflight_only:
                template = {"captured_at": self.r.now(), "pose_at_capture": st.get("pose"),
                            "frames": frames, **{k: None for k in VERDICT_KEYS}, "note": "", "judged_by": ""}
                path = self.ev / "camera_verdict.json"
                path.write_text(json.dumps(template, indent=2), encoding="utf-8")
                self.summary["outcome"] = "preflight"
                log(f"look at the frames in {self.ev}, fill {path}, then rerun with --camera-verdict {path}")
                return 0
            self.verdict(st.get("pose"))
            self.hold()
            self.overlay()
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
            return 0 if not missing else 1
        except (Exception, SystemExit, KeyboardInterrupt) as exc:
            self.summary["outcome"] = f"aborted: {exc or type(exc).__name__}"
            log("ABORT", exc)
            return 2
        finally:
            if not preflight_only:
                self.cleanup()
            self.write_summary()

    def write_summary(self):
        out = Path(self.args.summary_dir)
        out.mkdir(parents=True, exist_ok=True)
        self.summary["evidence_dir"] = str(self.ev)
        self.summary["evidence"] = {p.name: sha(p) for p in sorted(self.ev.iterdir()) if p.is_file()}
        if self.summary["errors"]:
            self.summary["outcome"] += "; cleanup errors (check the robot by hand)"
        (out / "summary.json").write_text(json.dumps(self.summary, indent=2, ensure_ascii=False, default=str),
                                          encoding="utf-8")
        readme = out / "README.md"
        if not readme.exists():
            readme.write_text(
                f"# {self.plan['topic']} ({self.args.robot})\n\n"
                f"결과: {self.summary['outcome']}\n\n"
                "`summary.json`이 단계, 관찰한 상태·사유·이벤트, 증거 파일의 `sha256:` 요약을 담는다. "
                f"원본 증거(프레임, `status.jsonl`, `events.jsonl`)는 `{self.ev}`에 있다. D-512.\n\n"
                "## 판단\n\n(에이전트가 프레임과 기록을 보고 적는다.)\n", encoding="utf-8")
        log("summary", out / "summary.json", self.summary["outcome"])


def dry_run(plan, args):
    print(f"DRY RUN {plan['topic']} on {args.robot} ({args.host}); no network, no SSH")
    for name in PHASES:
        print(" -", name)
    print("overlay", plan["overlay_path"], json.dumps(flatten(plan["overlay"])))
    print("stop", json.dumps(plan["stop"]), "expect", json.dumps(plan.get("expect", {})))
    print("finally: line-follow OFF, IDLE, recording stop, overlay revert + readback, hold release, after frames")
    return 0


def main(argv=None, robot=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--robot", required=True, help="robot hostname, e.g. rosy-pinky-9dfk")
    ap.add_argument("--host", help="address (default <robot>.local)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--plan", required=True)
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
    ap.add_argument("--evidence-dir")
    ap.add_argument("--summary-dir")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    plan = load_plan(args.plan)
    args.host = args.host or f"{args.robot}.local"
    stamp = dt.datetime.now().strftime("%Y-%m-%d")
    args.evidence_dir = args.evidence_dir or f"X:/DevTemp/device-test/{plan['topic']}-{stamp}-{time.strftime('%H%M%S')}"
    args.summary_dir = args.summary_dir or str(REPO / "docs" / "validation" / f"{plan['topic']}-{stamp}")
    if args.dry_run:
        return dry_run(plan, args)
    if not (args.preflight_only or args.camera_verdict):
        ap.error("pass --preflight-only first, then --camera-verdict FILE")
    if robot is None:
        if not args.token_file or not (args.ca_file or args.insecure):
            ap.error(f"pass --token-file (or {edge_drive.TOKEN_ENV}) and --ca-file or --insecure")
        robot = Live(args)
    return Run(robot, plan, args, args.evidence_dir).execute(preflight_only=args.preflight_only)


if __name__ == "__main__":
    sys.exit(main())
