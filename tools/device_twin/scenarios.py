"""The D-406 device twin scenarios. Each runs on a fresh twin and checks real systemd state. Twin only."""

from __future__ import annotations

import json
import subprocess
import time

from twin_lib import (API_BASE, HOSTNAME, R, ROOT, TWIN, UPDATER, UPDATES, Build, GitHubSide, Twin, log, run)


class Result:
    def __init__(self, key: str, title: str) -> None:
        self.key, self.title = key, title
        self.checks: list[tuple[str, bool, str]] = []
        self.evidence: list[tuple[str, str]] = []
        self.error: str | None = None
        self.seconds = 0.0

    def check(self, description: str, ok: object, detail: object = "") -> bool:
        self.checks.append((description, bool(ok), str(detail)))
        log(f"  {'PASS' if ok else 'FAIL'} {description} {str(detail)[:200]}")
        return bool(ok)

    @property
    def passed(self) -> bool:
        return self.error is None and bool(self.checks) and all(ok for _d, ok, _x in self.checks)


def _ordered(items: list[str], wanted: list[str]) -> bool:
    position = 0
    for item in items:
        if position < len(wanted) and item == wanted[position]:
            position += 1
    return position == len(wanted)


def _wait(process: subprocess.Popen, timeout: float) -> object:
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        return "timeout"


class Scenarios:
    ORDER = ["a", "b", "c", "d", "e", "f", "f2", "g", "h", "h3", "i", "j"]

    def __init__(self, build: Build) -> None:
        self.build = build
        self.twin = Twin(build)
        self.github = GitHubSide(build)
        self.r: Result | None = None

    # evidence helpers ----------------------------------------------------------------
    def ev(self, command: str, *, check: bool = False, timeout: float = 900) -> str:
        done = self.twin.x(command, timeout=timeout, check=check)
        text = (done.stdout + (f"\n[stderr] {done.stderr.strip()}" if done.stderr.strip() else "")).strip()
        self.r.evidence.append((command, text[-3000:]))
        return done.stdout.strip()

    def note(self, label: str, text: str) -> None:
        self.r.evidence.append((label, text[-4000:]))

    def core(self) -> tuple[int, str]:
        pid = self.twin.main_pid()
        return pid, self.twin.cwd(pid)

    def updater(self, label: str = "") -> dict:
        seconds = self.twin.run_updater()
        status = self.twin.status()
        self.r.evidence.append((f"systemctl start rosy-auto-update.service {label}".strip(),
                                f"({seconds:.0f} s) status.json: " + json.dumps(status, sort_keys=True)))
        return status

    @staticmethod
    def rel(name: str) -> str:
        return f"/opt/rosy/releases/{R[name]}"

    def publish_output(self, process: subprocess.Popen) -> None:
        self.note("publish tool output", process.log_path.read_text(encoding="utf-8", errors="replace"))

    # (a) ----------------------------------------------------------------------------
    def a(self) -> None:
        """Activation defect regression: the fixed activator moves CORE; the old target-only sequence did not."""
        t = self.twin
        pid0, cwd0 = self.core()
        self.r.check("CORE starts on the factory release A", cwd0 == self.rel("A"), f"pid {pid0} cwd {cwd0}")
        self.ev(f"cp /twin/releases/{R['B']}.tar.gz /tmp/ && bash /opt/rosy/native-runtime/rosy-release-unpack.sh "
                f"{R['B']} /tmp/{R['B']}.tar.gz", check=True)
        self.ev(f"bash /opt/rosy/native-runtime/activate-release.sh {R['B']}", check=True)
        pid1, cwd1 = self.core()
        self.r.check("fixed activator: rosy-core MainPID changed", pid1 != pid0 and pid1 > 0, f"{pid0} -> {pid1}")
        self.r.check("fixed activator: rosy-core cwd is B", cwd1 == self.rel("B"), cwd1)
        for unit in ("rosy-io.service", "rosy-camera.service"):
            unit_cwd = t.cwd(t.main_pid(unit))
            self.r.check(f"fixed activator: {unit} cwd is B", unit_cwd == self.rel("B"), unit_cwd)
        self.r.check("CORE API reports release B", t.api_version() == f"twin-{R['B']}", t.api_version())
        # The pre-fix activator (before a48f75f8): stop the target only, switch, start the target.
        old = (f"systemctl stop rosy-runtime.target && ln -sfn {self.rel('A')} /opt/rosy/.current.new && "
               f"mv -T /opt/rosy/.current.new /opt/rosy/current && systemctl start rosy-runtime.target")
        self.ev(old, check=True)
        t.wait_runtime()
        pid2, cwd2 = self.core()
        io_cwd = t.cwd(t.main_pid("rosy-io.service"))
        reproduced = t.current() == R["A"] and pid2 == pid1 and cwd2 == self.rel("B")
        self.r.check("old single-target sequence leaves CORE on the old process (the defect, reproduced)", reproduced,
                     f"current={t.current()} core pid {pid1}->{pid2} cwd={cwd2} io cwd={io_cwd} API {t.api_version()}")
        self.ev("journalctl -u rosy-core.service -u rosy-io.service -u rosy-camera.service -u rosy-runtime.target "
                "-o short-monotonic --no-pager | grep -E 'Stopp|Started|Starting' | tail -n 16")

    # (b) ----------------------------------------------------------------------------
    def b(self) -> None:
        """Happy path: the real publish tool with the twin as canary; the updater started by systemctl commits."""
        t, gh = self.twin, self.github
        pid0, _ = self.core()
        publish = gh.start_publish(R["B"])
        gh.wait_release(R["B"])
        self.note("publish command", " ".join(gh.publish_argv(R["B"], "--tarball", f"<releases>/{R['B']}.tar.gz",
                                                              "--canary", HOSTNAME, "--canary-timeout-min", "10")))
        rollout, ok = gh.remote_rollout(R["B"])
        self.r.check("published rollout.json verifies and is canary-only", ok and rollout["canary"] == [HOSTNAME]
                     and rollout["canary_ok"] is False, json.dumps(rollout, sort_keys=True))
        status = self.updater()
        pid1, cwd1 = self.core()
        phases = [item["event"] for item in t.history()]
        self.r.check("updater committed B", status.get("phase") == "committed"
                     and (status.get("last_result") or {}).get("outcome") == "committed", status.get("reason"))
        self.r.check("history: staged -> applying -> committed", _ordered(phases, ["staged", "applying", "committed"]),
                     phases)
        self.r.check("/opt/rosy/current is B", t.current() == R["B"], t.current())
        self.r.check("rosy-core MainPID changed and cwd is B", pid1 != pid0 and cwd1 == self.rel("B"),
                     f"{pid0} -> {pid1} {cwd1}")
        self.r.check("CORE API reports B", t.api_version() == f"twin-{R['B']}", t.api_version())
        code = _wait(publish, 240)
        self.publish_output(publish)
        rollout, ok = gh.remote_rollout(R["B"])
        self.r.check("publish tool exited 0 and set canary_ok=true (signed)", code == 0 and ok
                     and rollout["canary_ok"] is True and rollout["withdrawn"] is False, f"exit {code}")
        # canary_ok re-uploaded rollout.json (a new asset size, so a new list ETag): the
        # next run gets a 200, the one after it a 304.
        self.updater("(second run)")
        status = self.updater("(third run)")
        requests = [json.loads(line) for line in
                    (self.build.store / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
        listing = [item for item in requests if "/releases" in item["path"]]
        self.note("fake GitHub list requests", "\n".join(json.dumps(item) for item in listing))
        self.r.check("later run: idle, current B", status.get("phase") == "idle"
                     and status.get("current_release") == R["B"], status.get("reason"))
        self.r.check("later run sent If-None-Match and got 304", bool(listing) and listing[-1]["status"] == 304
                     and bool(listing[-1]["if_none_match"]), listing[-1] if listing else None)
        self.ev(f"cat {UPDATES}/history.jsonl")

    # (c) ----------------------------------------------------------------------------
    def c(self) -> None:
        """Busy robot: moving, MANUAL, low battery, E-stop, stale inputs -> ineligible, CORE untouched."""
        t = self.twin
        self.github.release(R["B"])
        pid0, _ = self.core()
        expected = {"moving": "robot mode is NAVIGATING", "manual": "robot mode is MANUAL",
                    "battery": "below 40", "estop": "E-stop is engaged", "stale": "status-inputs"}
        for mode, words in expected.items():
            t.control(mode)
            if mode == "stale":
                time.sleep(16)  # the last write ages past 25 s
            status = self.updater(f"(control={mode})")
            self.r.check(f"{mode}: phase ineligible", status.get("phase") == "ineligible"
                         and words in (status.get("reason") or ""), status.get("reason"))
            self.r.check(f"{mode}: CORE PID unchanged, current A", t.main_pid() == pid0 and t.current() == R["A"],
                         f"pid {t.main_pid()} current {t.current()}")
        self.r.check("B is staged while busy", t.state().get("staged") == R["B"], t.state().get("staged"))

    # (d) ----------------------------------------------------------------------------
    def d(self) -> None:
        """Hold -> held (staged, not applied); release-hold -> applies."""
        t = self.twin
        self.github.release(R["B"])
        pid0, _ = self.core()
        self.ev(f"sudo -n python3 {UPDATER} hold --holder twin-session --reason 'd406 twin hold test' --hours 1",
                check=True)
        status = self.updater("(held)")
        self.r.check("hold: phase held", status.get("phase") == "held"
                     and "hold by twin-session" in (status.get("reason") or ""), status.get("reason"))
        self.r.check("hold: CORE PID unchanged, current A, B staged", t.main_pid() == pid0 and t.current() == R["A"]
                     and t.state().get("staged") == R["B"], f"pid {t.main_pid()} staged {t.state().get('staged')}")
        self.ev(f"sudo -n python3 {UPDATER} release-hold", check=True)
        status = self.updater("(after release-hold)")
        pid1, cwd1 = self.core()
        self.r.check("release-hold: committed B", status.get("phase") == "committed" and t.current() == R["B"],
                     status.get("reason"))
        self.r.check("release-hold: CORE restarted on B", pid1 != pid0 and cwd1 == self.rel("B"), f"{pid1} {cwd1}")

    # (e) ----------------------------------------------------------------------------
    def e(self) -> None:
        """A sealed hardware approval naming the current release holds the robot."""
        t = self.twin
        self.github.release(R["B"])
        pid0, _ = self.core()
        self.ev(f"printf '{{\"release_id\": \"{R['A']}\", \"approved_by\": \"twin\"}}\\n' "
                "> /etc/rosy/approvals/hardware.approved && cat /etc/rosy/approvals/hardware.approved", check=True)
        status = self.updater("(sealed)")
        self.r.check("sealed approval: phase held", status.get("phase") == "held"
                     and "sealed approval hardware.approved" in (status.get("reason") or ""), status.get("reason"))
        self.r.check("sealed approval: CORE PID unchanged, current A", t.main_pid() == pid0 and t.current() == R["A"],
                     f"pid {t.main_pid()} current {t.current()}")

    # (f) ----------------------------------------------------------------------------
    def f(self) -> None:
        """Bad release C (CORE ready, then dies): rollback to B, image layer synced back, C failed and withdrawn."""
        t, gh = self.twin, self.github
        self.note("setup: B current via unpack + activate + sync", t.unpack_and_activate(R["B"]))
        t.wait_runtime()
        _pid0, cwd0 = self.core()
        self.r.check("setup: CORE on B", cwd0 == self.rel("B"), cwd0)
        marker = "/opt/rosy/native-runtime/twin-layer-marker.txt"
        publish = gh.start_publish(R["C"])
        gh.wait_release(R["C"])
        status = self.updater("(bad release C)")
        t.wait_runtime()
        _pid1, cwd1 = self.core()
        state = t.state()
        events = [(item["event"], item["release_id"]) for item in t.history()]
        self.r.check("C rolled back", status.get("phase") == "rolled_back"
                     and (status.get("last_result") or {}).get("outcome") == "rolled_back", status.get("reason"))
        self.r.check("current is B again and CORE runs from B", t.current() == R["B"] and cwd1 == self.rel("B"),
                     f"current {t.current()} cwd {cwd1}")
        self.r.check("C recorded as failed", R["C"] in (state.get("failed") or {}),
                     json.dumps((state.get("failed") or {}).get(R["C"])))
        manifests = self.ev(
            "for f in /var/lib/rosy/image-layer-backup/*/backup-manifest.json; do echo \"== $f\"; "
            "python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d[\"release_id\"], "
            "[(x[\"path\"], x[\"state\"]) for x in d[\"files\"] if \"marker\" in x[\"path\"]])' \"$f\"; done")
        present = t.x(f"test -e {marker}", check=False).returncode == 0
        self.r.check("image layer: C's sync installed the marker, the rollback sync removed it",
                     "'new')" in manifests and "'removed')" in manifests and not present,
                     f"marker present now: {present}")
        self.r.check("history: rollback_started then rolled_back for C",
                     ("rollback_started", R["C"]) in events and ("rolled_back", R["C"]) in events, events[-6:])
        code = _wait(publish, 240)
        self.publish_output(publish)
        rollout, ok = gh.remote_rollout(R["C"])
        self.r.check("publish tool withdrew C (exit 3, signed withdrawn=true)", code == 3 and ok
                     and rollout["withdrawn"] is True, f"exit {code} reason {rollout.get('reason')!r}")
        pid2 = t.main_pid()
        status = self.updater("(after the rollback)")
        self.r.check("C is never retried: idle, current B, CORE untouched", status.get("phase") == "idle"
                     and t.current() == R["B"] and t.main_pid() == pid2, status.get("reason"))
        self.note("rosy-core journal", t.journal("rosy-core.service", 30))

    # (f2) ---------------------------------------------------------------------------
    def f2(self) -> None:
        """Bad release N (CORE never ready): N refused or rolled back, A restored, N failed and withdrawn."""
        t, gh = self.twin, self.github
        publish = gh.start_publish(R["N"])
        gh.wait_release(R["N"])
        status = self.updater("(never-ready release N)")
        t.wait_runtime()
        _pid1, cwd1 = self.core()
        state = t.state()
        self.r.check("N not committed; phase failed or rolled_back", status.get("phase") in ("failed", "rolled_back"),
                     f"{status.get('phase')}: {status.get('reason')}")
        self.r.check("current is A and CORE runs from A", t.current() == R["A"] and cwd1 == self.rel("A"),
                     f"current {t.current()} cwd {cwd1}")
        self.r.check("N recorded as failed", R["N"] in (state.get("failed") or {}),
                     json.dumps((state.get("failed") or {}).get(R["N"])))
        self.r.check("no rosy-* unit left failed", not t.out("systemctl list-units --state=failed --plain "
                                                             "--no-legend 'rosy-*'"),
                     t.out("systemctl list-units --state=failed --plain --no-legend 'rosy-*'"))
        code = _wait(publish, 240)
        self.publish_output(publish)
        rollout, ok = gh.remote_rollout(R["N"])
        self.r.check("publish tool withdrew N", code == 3 and ok and rollout["withdrawn"] is True,
                     f"exit {code} reason {rollout.get('reason')!r}")
        self.note("rosy-core journal", t.journal("rosy-core.service", 30))

    # (g) ----------------------------------------------------------------------------
    def g(self) -> None:
        """A withdrawn release is never applied, even after a later rollout says withdrawn:false."""
        t, gh = self.twin, self.github
        pid0, _ = self.core()
        gh.release(R["D"])
        done = run(gh.publish_argv(R["D"], "--release-id", R["D"], "--withdraw", "--reason", "twin: withdrawn by hand"),
                   env=gh.env(), check=False, cwd=ROOT)
        self.note("publish_payload_release.py --withdraw", (done.stdout + done.stderr).strip())
        rollout, ok = gh.remote_rollout(R["D"])
        self.r.check("publish tool --withdraw uploaded a signed withdrawn rollout", done.returncode == 0 and ok
                     and rollout["withdrawn"] is True, rollout.get("reason"))
        status = self.updater("(withdrawn)")
        self.r.check("withdrawn: not applied (idle, skipped)", status.get("phase") == "idle"
                     and "withdrawn" in (status.get("reason") or "") and t.current() == R["A"], status.get("reason"))
        gh.reupload(R["D"], withdrawn=False, canary_ok=True)
        rollout, ok = gh.remote_rollout(R["D"])
        self.r.check("a later, validly signed rollout says withdrawn:false", ok and rollout["withdrawn"] is False)
        status = self.updater("(un-withdrawn rollout)")
        self.r.check("still never applied: idle, current A, CORE untouched", status.get("phase") == "idle"
                     and t.current() == R["A"] and t.main_pid() == pid0, status.get("reason"))
        self.r.check("state.json keeps D withdrawn", R["D"] in (t.state().get("withdrawn") or {}),
                     json.dumps(t.state().get("withdrawn")))

    # (h) ----------------------------------------------------------------------------
    def _start_and_interrupt(self, steps: tuple[str, ...], how: str, timeout: float = 240,
                             wait_runtime: bool = True) -> str:
        """Start the updater, wait until its journal names one of ``steps``, then interrupt it."""
        t = self.twin
        t.x("systemctl start --no-block rosy-auto-update.service")
        probe = (f"python3 -c 'import json; a=json.load(open(\"{UPDATES}/state.json\")).get(\"applying\") or {{}}; "
                 "print(a.get(\"step\") or \"\")' 2>/dev/null || true")
        deadline = time.monotonic() + timeout
        step = ""
        while time.monotonic() < deadline:
            step = t.out(probe)
            if step in steps:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError(f"the updater never reached {steps} (last {step!r})")
        if how == "kill":
            t.x("systemctl kill --signal=SIGKILL rosy-auto-update.service")
        else:  # a power cut: the whole container dies at once, then boots again
            run(["docker", "kill", TWIN])
            run(["docker", "start", TWIN])
            if wait_runtime:
                t.wait_runtime()
        return step

    def h(self) -> None:
        """Interruption after activate: SIGKILL the updater, and a power cut; both resume and commit."""
        t = self.twin
        self.github.release(R["B"])
        pid0, _ = self.core()
        step = self._start_and_interrupt(("image-layer-sync", "restart", "health"), "kill")
        time.sleep(2)
        state = t.state()
        claim = t.out("cat /run/rosy-claim/claim.json 2>/dev/null || echo none")
        self.note("after SIGKILL", f"killed at step {step}; applying={json.dumps(state.get('applying'))}; claim={claim}")
        self.r.check("SIGKILL left the apply journaled", (state.get("applying") or {}).get("release_id") == R["B"],
                     f"step {step}")
        status = self.updater("(resume after SIGKILL)")
        events = [item["event"] for item in t.history()]
        pid1, cwd1 = self.core()
        self.r.check("resume after SIGKILL: committed B", status.get("phase") == "committed"
                     and "apply_interrupted" in events and t.current() == R["B"], status.get("reason"))
        self.r.check("CORE runs from B", cwd1 == self.rel("B") and pid1 != pid0, f"{pid0} -> {pid1} {cwd1}")

        t.start()  # the power cut, in the same place, on a fresh twin
        self.github.release(R["B"])
        step = self._start_and_interrupt(("image-layer-sync", "restart", "health"), "power")
        state = t.state()
        self.note("after docker kill + start", f"cut at step {step}; applying={json.dumps(state.get('applying'))}; "
                                               f"current {t.current()}; claim dir: "
                                               f"{t.out('ls -d /run/rosy-claim 2>/dev/null || echo gone')}")
        self.r.check("power cut left the apply journaled", (state.get("applying") or {}).get("release_id") == R["B"],
                     f"step {step}")
        status = self.updater("(resume after power cut)")
        _pid2, cwd2 = self.core()
        self.r.check("resume after power cut: committed B, CORE on B", status.get("phase") == "committed"
                     and t.current() == R["B"] and cwd2 == self.rel("B"), status.get("reason"))

    def h3(self) -> None:
        """Power cut during activate: boot recovery must restore a release and the runtime; the resume settles."""
        t = self.twin
        self.github.release(R["B"])
        step = self._start_and_interrupt(("activate",), "power", wait_runtime=False)
        time.sleep(25)  # boot: rosy-release-recover, then the runtime
        journal = t.out("cat /var/lib/rosy/releases/native-activation.json 2>/dev/null || echo none")
        self.note("after docker kill + start", f"cut at step {step}; native journal: {journal}; "
                                               f"current {t.current()}")
        recover = t.out("systemctl is-active rosy-release-recover.service", check=False)
        self.note("rosy-release-recover after the cut", t.journal("rosy-release-recover.service", 6))
        self.ev("systemctl is-active rosy-release-recover.service rosy-core.service rosy-runtime.target; "
                "systemctl show -p ProtectSystem -p PrivateTmp -p ReadWritePaths rosy-release-recover.service")
        self.r.check("boot recovery (rosy-release-recover.service) succeeds after a cut during activate",
                     recover == "active", recover)
        runtime_up = t.x("systemctl is-active --quiet rosy-core.service", check=False).returncode == 0
        self.r.check("the runtime comes back after the cut", runtime_up)
        if not runtime_up:
            done = t.x("systemctl start rosy-auto-update.service", check=False)
            self.note("systemctl start rosy-auto-update.service (runtime down)", (done.stdout + done.stderr).strip())
            self.r.check("the updater can still run to settle the apply", done.returncode == 0,
                         f"exit {done.returncode}; status.json phase {t.status().get('phase')!r}")
            # Diagnosis only (not a fix): the same recovery with a private /tmp.
            t.x("mkdir -p /run/systemd/system/rosy-release-recover.service.d && printf '[Service]\nPrivateTmp=yes\n' "
                "> /run/systemd/system/rosy-release-recover.service.d/twin-diagnosis.conf && systemctl daemon-reload")
            self.ev("systemctl restart rosy-release-recover.service; systemctl is-active rosy-release-recover.service; "
                    "journalctl -u rosy-release-recover.service -o cat --no-pager | tail -n 2", timeout=120)
            t.x("rm -rf /run/systemd/system/rosy-release-recover.service.d && systemctl daemon-reload")
            t.x("systemctl start rosy-runtime.target", check=False)
            t.wait_runtime()
        status = self.updater("(resume after a cut during activate)")
        _pid1, cwd1 = self.core()
        self.r.check("the robot ends on one release with CORE running from it",
                     cwd1 == f"/opt/rosy/releases/{t.current()}" and t.main_pid() > 0,
                     f"current {t.current()} cwd {cwd1}")
        # A cut before the link switch is retried after a backoff ("waiting"); after it, committed or rolled back.
        self.r.check("the apply is settled, not left journaled",
                     not t.state().get("applying")
                     and status.get("phase") in ("committed", "rolled_back", "waiting"),
                     f"{status.get('phase')}: {status.get('reason')}")
        self.note("history", "\n".join(json.dumps(item) for item in t.history()[-8:]))

    # (i) ----------------------------------------------------------------------------
    def i(self) -> None:
        """A manual push holding the claim keeps the updater off."""
        t = self.twin
        self.github.release(R["B"])
        pid0, _ = self.core()
        self.ev("sudo -n python3 /opt/rosy/native-runtime/rosy_claim.py acquire --holder rosy-release-push "
                "--purpose 'manual push (twin)' --ttl-s 900", check=True)
        status = self.updater("(claim held)")
        self.r.check("claim: phase ineligible naming the push", status.get("phase") == "ineligible"
                     and "claim held by rosy-release-push" in (status.get("reason") or ""), status.get("reason"))
        self.r.check("claim: CORE PID unchanged, current A", t.main_pid() == pid0 and t.current() == R["A"])
        self.r.check("claim: still the push's claim after the run",
                     "rosy-release-push" in t.out("cat /run/rosy-claim/claim.json"))

    # (j) ----------------------------------------------------------------------------
    def j(self) -> None:
        """systemd-analyze verify on the rosy units; the sandboxed updater can read rosy-core's /proc cwd."""
        t = self.twin
        units = t.out("cd /etc/systemd/system && ls rosy-*.service rosy-*.target rosy-*.timer rosy-*.path").split()
        reports = {}
        for unit in units:
            done = t.x(f"systemd-analyze verify /etc/systemd/system/{unit}", check=False)
            reports[unit] = (done.returncode, (done.stdout + done.stderr).strip())
        self.note("systemd-analyze verify", "\n".join(f"{unit}: exit {code} {text}" for unit, (code, text)
                                                      in reports.items()))
        d406 = ("rosy-auto-update.service", "rosy-auto-update.timer", "rosy-core.service", "rosy-io.service",
                "rosy-camera.service", "rosy-runtime.target", "rosy-release-recover.service")
        self.r.check("systemd-analyze verify: D-406 path units exit 0 with no output",
                     all(reports[unit] == (0, "") for unit in d406),
                     {unit: reports[unit] for unit in d406 if reports[unit] != (0, "")})
        self.r.check("systemd-analyze verify: every rosy unit exits 0",
                     all(code == 0 for code, _text in reports.values()),
                     {unit: text for unit, (code, text) in reports.items() if code != 0})
        self.ev("systemctl start twin-sandbox-probe.service; journalctl -u twin-sandbox-probe.service -o cat "
                "--no-pager | grep TWIN_SANDBOX_PROBE | tail -n 1")
        line = t.out("journalctl -u twin-sandbox-probe.service -o cat --no-pager | grep TWIN_SANDBOX_PROBE | tail -n 1")
        probe = json.loads(line.split(" ", 1)[1]) if line else {}
        self.r.check("under rosy-auto-update.service's sandbox, /proc/<rosy-core pid>/cwd is readable",
                     probe.get("cwd") == self.rel("A") and probe.get("process_uid") == 960, probe)
        self.ev("diff <(grep -v '^ExecStart=' /etc/systemd/system/rosy-auto-update.service) "
                "<(grep -v '^ExecStart=' /etc/systemd/system/twin-sandbox-probe.service) && echo 'identical except ExecStart'")
        self.ev("ps -o user=,pid=,cmd= -p $(systemctl show -p MainPID --value rosy-core.service)")
        self.ev(f"grep -o 'api_base[^,}}]*' {UPDATES}/config.json; echo {API_BASE}")
