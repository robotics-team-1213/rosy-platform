"""Overlay, hold, cleanup, restore, and dry-run helpers for tools/device_test/run.py (D-512)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import signal
import sys

import yaml

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools" / "capture") not in sys.path:
    sys.path.insert(0, str(REPO / "tools" / "capture"))
import edge_drive  # noqa: E402
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import tether  # noqa: E402
from plan_rules import OVERLAY_PATH, flatten, merge, sanitize, sha  # noqa: E402

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


class RunOverlayAndCleanupMixin:
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

    def restart_core(self, rebase=False):
        """Restart CORE and show the new process reads overlay_path without a config error.
        CORE has no endpoint for effective line_follow config; the process env, its journal and
        a steady PID are the readback (D-512 decision 6). With rebase the tether guard takes the
        odometry pose after the restart as its reference (tether.Guard.rebase)."""
        pose_before = self.pose_now() if rebase else None
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
        if rebase and getattr(self, "tether", None) is not None:
            self.tether.rebase(pose_before, self.pose_now())

    def pose_now(self):
        """The odometry pose from /robot/state, None when it cannot be read."""
        s, b = self.r.core.call("GET", "/robot/state")
        return tether.pose_of(b.get("pose")) if s == 200 and isinstance(b, dict) else None

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
        self.restart_core(rebase=True)
        back = flatten(yaml.safe_load(self.read_overlay().decode("utf-8")) or {})
        wrong = {k: back.get(k) for k, v in flatten(self.plan["overlay"]).items() if back.get(k) != v}
        if wrong:
            raise Abort(f"overlay readback mismatch: {wrong}")
        self.phase("overlay", applied=flatten(self.plan["overlay"]), path=p, backup=backup)

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


def restore_with_run(robot, args, run_cls):
    """--restore EVIDENCE_DIR: line-follow OFF, IDLE, overlay restore + readback, hold release,
    from RESTORE_PENDING.json. The marker goes only when all of it is verified."""
    ev = Path(args.restore)
    m = json.loads((ev / MARKER).read_text(encoding="utf-8"))
    if m["robot"] != args.robot:
        raise SystemExit(f"marker is for {m['robot']}, not {args.robot}")
    if m.get("overlay_path") != OVERLAY_PATH:
        raise SystemExit(f"marker overlay_path {m.get('overlay_path')!r} is not {OVERLAY_PATH}; restore by hand")
    run = run_cls(robot, {"topic": m["topic"], "overlay_path": OVERLAY_PATH, "overlay": {}}, args, ev)
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
