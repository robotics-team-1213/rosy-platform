#!/usr/bin/env python3
"""The robot-side auto-updater (D-412).

Runs from rosy-auto-update.timer as root. One ``run``:

1. stops if config.json says ``enabled: false``;
2. reads the GitHub Releases list with an ETag (a 304 reuses the cached list)
   and picks the highest ``payload-<id>`` above the current release that has
   its three assets, is not recorded as failed, and whose signed rollout.json
   verifies and is not withdrawn;
3. stages it (download to .part, sha256 against the rollout, the native unpack
   script, ``native_release.py verify``) even when the robot is busy; current
   is never moved by staging;
4. applies only when the rollout lets this host (canary, or ``canary_ok`` and
   the wave delay passed) and the robot is eligible: no hold, no sealed
   approval for the current release, CORE idle and still in two samples 10 s
   apart, battery >= 40 % or charging, no live /run/rosy-claim;
5. applies under the claim: activate, the core-release check, the new
   release's sync-image-layer.py, restarts, then health (CORE ready, core/io/
   camera active from the new release, no failed rosy-* unit, held 60 s);
6. on failure rolls back, syncs from the rolled-back release, and records the
   id as failed (never retried). status.json and history.jsonl record it all.

    rosy_auto_update.py run
    rosy_auto_update.py status [--json]
    rosy_auto_update.py hold --holder H --reason R --hours N     # 0 < N <= 168
    rosy_auto_update.py release-hold
    rosy_auto_update.py eligibility [--json]                       # read-only

Standard library only; signing.py, rosy_claim.py and the auto_update_*.py modules
(host, records, stage, apply; split out by D-798) sit beside it on the device.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import shlex
import sys

# The unit runs python3 -I (no script directory on sys.path): add it, and the
# repository's release tools as a fallback when run from a checkout.
sys.dont_write_bytecode = True
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
RELEASE_TOOLS = SCRIPT_DIR.parent / "release"
if RELEASE_TOOLS.is_dir() and str(RELEASE_TOOLS) not in sys.path:
    sys.path.append(str(RELEASE_TOOLS))

RESYNCED_ENV = "ROSY_AUTO_UPDATE_RESYNCED"


def _resync_and_rerun(error: ImportError) -> None:
    """Resync the image layer from the active release once, then run again (D-798).

    sync-image-layer.py replaces native-runtime files one at a time under a journal, not as a
    set: a power loss mid-sync leaves this folder with files from two releases until the next
    sync reconciles them, and that next sync normally comes from this updater. Only the
    image-layer copy run as a program does this; an import (tests) or another copy re-raises.
    """
    root = SCRIPT_DIR.parents[2]
    sync = root / "opt/rosy/current/deploy/robot/native/sync-image-layer.py"
    if (__name__ != "__main__" or os.environ.get(RESYNCED_ENV)
            or SCRIPT_DIR != root / "opt/rosy/native-runtime" or not sync.is_file()):
        raise error
    import subprocess
    # 600 s: SYNC_TIMEOUT_S, which lives in the sibling that may be the broken one.
    synced = subprocess.run([sys.executable, "-B", str(sync)], capture_output=True, text=True, timeout=600)
    if synced.returncode != 0:
        raise ImportError(f"{error}; image-layer resync failed: {synced.stderr.strip()[-300:]}") from error
    rerun = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), *sys.argv[1:]]
    raise SystemExit(subprocess.call(rerun, env={**os.environ, RESYNCED_ENV: "1"}))


try:
    import rosy_claim  # noqa: E402
    from auto_update_host import (API_BASE, APPLY_MAX_TRANSIENT, CLAIM_HOLDER, CLAIM_TTL_S, CORE_DOWN_NOTE,
        Definitive, ESCALATED_REASON, Host, Http, NATIVE_RUNTIME, parse_z, PRECHECK_BUSY_EXIT, _read_json,
        RELEASES, RunBusy, RUNTIME_ENV, STUCK_AFTER_S, STUCK_REASON, UpdateError, UPDATES, _z)  # noqa: E402
    # Re-exported: tests and tools read these as rosy_auto_update.<name>.
    from auto_update_host import (FACE_UNIT, HEALTH_UNITS, PHASES, RETIRED_DISPLAY_UNIT,  # noqa: E402,F401
        UPDATE_DISPLAY)
    from auto_update_apply import UpdaterApply  # noqa: E402
    from auto_update_records import UpdaterRecords  # noqa: E402
    from auto_update_stage import UpdaterStage  # noqa: E402
except ImportError as error:  # siblings from two releases after an interrupted image-layer sync
    _resync_and_rerun(error)


# --- the updater ----------------------------------------------------------------------


class Updater(UpdaterRecords, UpdaterStage, UpdaterApply):
    def __init__(self, host: Host, *, api_base: str | None = None, http: Http | None = None) -> None:
        self.host = host
        self.root = host.root
        self._own_http = http is None
        self.http = http
        self._use_api_base(api_base or API_BASE)
        self.updates = self.root / UPDATES

    def _use_api_base(self, api_base: str) -> None:
        self.api_base = api_base.rstrip("/")
        # Plain http only when the API itself is (a local test server).
        if self._own_http:
            self.http = Http(("https", "http") if self.api_base.startswith("http://") else ("https",))

    # paths and commands -------------------------------------------------------

    def _dev(self, relative: str) -> str:
        return str(self.root / relative)

    def release_path(self, release_id: str) -> str:
        return str(self.root / RELEASES / release_id)

    def _native(self, name: str) -> str:
        return self._dev(f"{NATIVE_RUNTIME}/{name}")

    def _ready_command(self) -> list[str]:
        env = shlex.quote(self._dev(RUNTIME_ENV))
        probe = shlex.quote(self._native("wait-core-ready.py"))
        return ["bash", "-c", f"set -a; [ -f {env} ] && . {env}; set +a; exec python3 -B {probe}"]

    def _resume(self, state: dict) -> dict:
        """A run died mid-apply (power loss, kill): finish it, once the robot is free again."""
        applying = state["applying"]
        release_id = str(applying.get("release_id"))
        step = applying.get("step")
        if not applying.get("interrupted_logged"):
            applying["interrupted_logged"] = True
            self._history("apply_interrupted", release_id, f"step {step}")
        # Review H1: nothing restarts while the robot is held, sealed or busy. Coordinator
        # decision: with rosy-core not running nothing can command motion (CORE is the only
        # cmd_vel publisher, D-2), so idleness is waived; hold, seal and claim still apply.
        core_down = self._core_down()
        report = self.eligibility(own_claim_ok=True, waive_inputs=core_down)
        if not report["eligible"]:
            silent = (not report["held"] and not core_down
                      and any(("stale" in reason or "missing" in reason or "not rewritten" in reason)
                              for reason in report["reasons"]))
            if not silent:
                applying.pop("silent_since", None)
            else:
                # Verification review M1: measured from the first resume that saw the silence.
                applying.setdefault("silent_since", _z(self.host.now()))
                since = parse_z(applying["silent_since"])
                if since is not None and (self.host.now() - since).total_seconds() > STUCK_AFTER_S:
                    # Re-review N5: no automatic rollback; a person has to look.
                    return self._finish(state, "stuck", STUCK_REASON, release_id)
            phase = "held" if report["held"] else "ineligible"
            return self._finish(state, phase, f"finishing {release_id} (step {step}) waits: "
                                + "; ".join(report["reasons"]), release_id)
        applying.pop("silent_since", None)
        # Re-review N15: the note describes this resume only.
        if core_down:
            applying["note"] = CORE_DOWN_NOTE
            self._history("idleness_waived", release_id, CORE_DOWN_NOTE)
        else:
            applying.pop("note", None)
        self._release_claim()  # our own claim from the dead run
        try:
            rosy_claim.acquire(self.root, CLAIM_HOLDER, f"finish auto-update to {release_id}", CLAIM_TTL_S,
                               now=self.host.now())
        except rosy_claim.ClaimBusy as exc:
            return self._finish(state, "ineligible", f"claim held by {(exc.claim or {}).get('holder')}",
                                release_id)
        try:
            # Review H2: a journal that reached rollback is only ever rolled back further.
            network = self._network_problems()
            if network:
                return self._finish(state, "ineligible", "; ".join(network), release_id)
            if step == "rollback":
                return self._roll_back(state, release_id, applying.get("why") or "interrupted rollback",
                                       mark_failed=applying.get("mark_failed", True))
            if step == "activate":
                self._recover_native()
            current = self.host.current_release()
            if current == release_id:
                return self._settle(state, release_id)
            if step == "activate" and current == applying.get("previous"):
                # Re-review N11: the switch never happened; nothing to blame on the release.
                state["applying"] = None
                self._apply_error(state, release_id, "activation interrupted before the switch")
                return self._finish(state, "waiting", f"an interrupted activation of {release_id} never "
                                    "switched; retrying after a backoff", release_id)
            # Boot recovery (or the activator) already restored the old release.
            problems = self._rollback_tail(release_id) if step != "activate" else []
            if any("BOOT_INVERSE" in problem for problem in problems):
                applying["step"] = "rollback"
                return self._finish(state, "held", "; ".join(problems), release_id)
            why = "; ".join(filter(None, ["interrupted; the previous release is current", applying.get("note")]))
            state["applying"] = None
            self._mark_failed(state, release_id, why)
            detail = why if not problems else f"{why}; rollback incomplete: {'; '.join(problems)}"
            self._result(state, release_id, "rolled_back", detail)
            return self._finish(state, "rolled_back" if not problems else "failed", detail, release_id)
        finally:
            self._release_claim()

    # the timer entry -----------------------------------------------------------------

    @staticmethod
    @contextlib.contextmanager
    def _locked_file(path: Path):
        """Non-blocking exclusive lock (flock; msvcrt on a Windows test host). OSError when busy."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            handle.seek(0)
            if os.name == "posix":
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "posix":
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_UN)
                else:
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    @contextlib.contextmanager
    def _run_lock(self):
        try:
            lock = self._locked_file(self.updates / ".run.lock")
            lock.__enter__()
        except OSError as exc:
            raise RunBusy("RUN_BUSY: another updater run is active") from exc
        try:
            yield
        finally:
            lock.__exit__(None, None, None)

    def run(self) -> dict:
        try:
            with self._run_lock():
                # Review M3: state is read only under the lock, and a busy run writes nothing.
                state = self._load_state()
                try:
                    return self._run(state)
                except UpdateError as exc:
                    return self._finish(state, "error", str(exc), state.get("candidate"))
                except Exception as exc:  # noqa: BLE001 - the oneshot must record, not crash
                    return self._finish(state, "error", f"UNEXPECTED: {exc!r}", state.get("candidate"))
        except RunBusy as exc:
            return {"schema": 1, "updated_at": _z(self.host.now()), "hostname": self.host.hostname(),
                    "current_release": self.host.current_release(), "candidate": None, "phase": "error",
                    "reason": str(exc), "last_result": None}

    def _run(self, state: dict) -> dict:
        self._policy_path("config.json")  # Resume must pass slot admission before touching a journal.
        # Review L9: an apply in flight is finished (or rolled back) even when disabled.
        if state.get("applying"):
            return self._resume(state)
        self._face_swap()
        state["candidate"] = None
        config = self._config()
        if not config["enabled"]:
            return self._finish(state, "disabled", "config.json has enabled=false")
        if config.get("api_base"):
            self._use_api_base(config["api_base"])
        current = self.host.current_release()
        if current is None:
            raise UpdateError("CURRENT_UNKNOWN: /opt/rosy/current does not name a release")
        last = state.get("last_result") or {}
        if last.get("outcome") == "rollback_failed" and last.get("release_id") == current:
            # Verification review L2: still on the release that could not be rolled back;
            # say so on every run until a person changes current.
            return self._finish(state, "failed", f"{current} could not be rolled back; operator action required: "
                                "rosy-release-push.ps1 -Rollback, or accept it with rosy_auto_update.py "
                                "release-hold", current)
        failed = state.setdefault("failed", {})
        # Review H4: a release we committed that is now above current was rolled back
        # on purpose by an operator; never apply it again.
        withdrawn_ids = state.get("withdrawn") or {}
        previous = self.host.previous_release()
        mine = state.get("self_rolled_back") or {}
        for item in list(mine):
            # Verification review 2, LOW (+ final LOW 3): an entry only matters while it
            # can still explain previous > current.
            if (item == current or item in failed or item in withdrawn_ids
                    or (item < current and item != previous)):
                del mine[item]
        rolled_back = [item for item in state.get("committed") or [] if item > current]
        if previous is not None and previous > current and previous not in (state.get("self_rolled_back") or {}):
            rolled_back.append(previous)  # re-review N9: previous above current was rolled away from
        for item in rolled_back:
            if item not in failed:
                self._mark_failed(state, item, "operator rolled back")
                self._history("operator_rolled_back", item, f"current is {current}")
        self._expire_hold()
        backoff = parse_z(state.get("backoff_until"))
        if backoff is not None and self.host.now() < backoff:
            raise UpdateError(f"GITHUB_BACKOFF: not asking GitHub until {_z(backoff)}")
        state["backoff_until"] = None
        try:
            releases = self._releases(state, config["repo"])
        finally:
            self._save_state(state)
        withdrawn = state.setdefault("withdrawn", {})
        candidates = sorted((item for item in releases
                             if item["release_id"] > current and item["release_id"] not in failed
                             and item["release_id"] not in withdrawn),
                            key=lambda item: item["release_id"], reverse=True)
        skipped = []
        for release in candidates:
            try:
                rollout = self._rollout(release)
            except Definitive as exc:
                # Review L1: only a definitive problem lets a lower release go first.
                skipped.append(f"{release['release_id']}: {exc}")
                continue
            except UpdateError as exc:
                state["candidate"] = release["release_id"]
                return self._finish(state, "error", str(exc), release["release_id"])
            if rollout["withdrawn"]:
                # Review M4: a withdrawal is permanent on this robot.
                withdrawn[release["release_id"]] = {"at": _z(self.host.now()), "reason": rollout.get("reason")}
                skipped.append(f"{release['release_id']}: withdrawn ({rollout.get('reason')})")
                continue
            break
        else:
            reason = "no newer release" + (f"; skipped {'; '.join(skipped)}" if skipped else "")
            return self._finish(state, "idle", reason)
        release_id = release["release_id"]
        state["candidate"] = release_id
        self._stage(state, release, rollout)
        waiting = self._gate(rollout)
        if waiting:
            return self._finish(state, "waiting", waiting, release_id)
        attempts = (state.get("apply_errors") or {}).get(release_id) or {}
        if attempts.get("attempts", 0) >= APPLY_MAX_TRANSIENT:
            return self._finish(state, "held", ESCALATED_REASON, release_id)
        retry = parse_z(attempts.get("retry_after"))
        if retry is not None and self.host.now() < retry:
            return self._finish(state, "waiting", f"apply backoff after {attempts.get('last')}; "
                                f"next attempt after {_z(retry)}", release_id)
        report = self.eligibility()
        if not report["eligible"]:
            phase = "held" if report["held"] else "ineligible"
            return self._finish(state, phase, "; ".join(report["reasons"]), release_id)
        return self.apply(release_id, state)


# --- CLI --------------------------------------------------------------------------------


def _print_status(status: dict) -> None:
    for key in ("phase", "reason", "current_release", "candidate", "updated_at"):
        print(f"{key}: {status.get(key)}")
    last = status.get("last_result")
    if last:
        print(f"last_result: {last.get('outcome')} {last.get('release_id')} at {last.get('at')} ({last.get('detail')})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path("/"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    show = sub.add_parser("status")
    show.add_argument("--json", action="store_true")
    hold = sub.add_parser("hold")
    hold.add_argument("--holder", required=True)
    hold.add_argument("--reason", required=True)
    hold.add_argument("--hours", type=float, required=True)
    sub.add_parser("release-hold")
    sub.add_parser("precheck")
    check = sub.add_parser("eligibility")
    check.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    updater = Updater(Host(args.root), api_base=API_BASE)
    if args.command == "run":
        print(json.dumps(updater.run(), sort_keys=True))
        return 0  # every outcome is in status.json; a failed oneshot would only add noise
    if args.command == "status":
        try:
            status = _read_json(updater.updates / "status.json")
        except (OSError, ValueError):
            status = {"phase": None, "reason": "the updater has not run yet"}
        if args.json:
            print(json.dumps(status, sort_keys=True))
        else:
            _print_status(status if isinstance(status, dict) else {})
        return 0
    if args.command == "hold":
        try:
            print(json.dumps(updater.hold(args.holder, args.reason, args.hours), sort_keys=True))
        except UpdateError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0
    if args.command == "precheck":
        reasons = updater.precheck()
        print("; ".join(reasons) if reasons else "ok")
        return PRECHECK_BUSY_EXIT if reasons else 0
    if args.command == "release-hold":
        try:
            result = {"ok": True, **updater.release_hold()}
        except RunBusy as exc:
            print(json.dumps({"ok": False, "error": f"{exc}; retry when the run has finished"}, sort_keys=True))
            return 4
        print(json.dumps(result, sort_keys=True))
        return 0
    report = updater.eligibility()
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print("eligible" if report["eligible"] else "not eligible")
        for reason in report["reasons"]:
            print(f"- {reason}")
    return 0 if report["eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
