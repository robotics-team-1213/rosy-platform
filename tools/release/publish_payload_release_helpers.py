"""Rollout signing, process locking, canary watching, withdrawal, and CLI helpers for publish_payload_release.py."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
RELEASE_TOOLS = ROOT / "deploy" / "robot" / "pinky_pro" / "release"
if str(RELEASE_TOOLS) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOLS))
import signing  # noqa: E402

REPO = "robotics-team-1213/rosy-platform"
REPO_NAME = re.compile(r"[\w.-]+/[\w.-]+")
KEY_NAME = re.compile(r"[\w.-]+")
CANARY_HOSTNAME = re.compile(r"rosy-[a-z0-9-]+")
REVISION = re.compile(r"[0-9a-f]{40}")
STATUS_COMMAND = "sudo -n python3 /opt/rosy/native-runtime/rosy_auto_update.py status --json"
CANARY_NOT_STARTED = 4
POLL_S = 30
#: Robot and PC clocks are NTP-synced; allow this much when comparing a robot's result time to published_at.
CLOCK_SKEW_S = 120
DEFAULT_EVIDENCE = Path(os.environ.get("ROSY_SCRATCH") or tempfile.gettempdir()) / "rosy-rollout-evidence"
SCRIPT = r"python tools\release\publish_payload_release.py"

Runner = Callable[[list[str]], tuple[int, str, str]]


def _load_inspection():
    spec = importlib.util.spec_from_file_location("payload_inspection", Path(__file__).with_name("payload_inspection.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inspection = _load_inspection()
prepare = inspection.prepare
PublishError = inspection.PublishError
_rejections = inspection._rejections
read_tarball_identity = inspection.read_tarball_identity
verify_tarball = inspection.verify_tarball
build_rollout = inspection.build_rollout
rollout_bytes = inspection.rollout_bytes


class RolloutUnverified(PublishError):
    """The remote rollout.json does not verify (tampered, or a half-finished --clobber upload)."""


# --- rollout.json --------------------------------------------------------------

def utc_stamp(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_stamp(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def sign_rollout(data: bytes, private_key: Path, public_key: Path,
                 signer: Callable[[bytes, Path], str] = signing.sign_checksums, key_name: str = "release key") -> str:
    """Sign, then verify against the public key the robots trust before anything leaves this PC.

    A signer error (openssl names the key file in it) is replaced by one that names only the key.
    """
    try:
        signature = signer(data, private_key)
    except signing.SigningToolMissing:
        raise
    except Exception:  # noqa: BLE001 - the message would carry the private key path
        raise PublishError(f"signing rollout.json with key {key_name} failed: "
                           "openssl could not use that private key") from None
    rejections = signing.verify_signature(data, signature, public_key)
    if rejections:
        raise PublishError("rollout.json self-verify failed: " + _rejections(rejections))
    return signature


# --- runners & canary mixin ----------------------------------------------------

def run_gh(argv: list[str]) -> tuple[int, str, str]:
    try:
        done = subprocess.run(argv, capture_output=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, "", f"{type(error).__name__}: {error}"
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


class PublisherCanaryMixin:
    # -- ssh --
    def ssh(self, host: str, command: str) -> tuple[int, str, str]:
        return self._ssh(prepare.ssh_argv(host, self.local_appdata, command))

    def hostname(self, host: str) -> str:
        code, out, err = self.ssh(host, "hostname")
        name = out.strip()
        if code != 0:
            raise PublishError(f"ssh {host} hostname failed (exit {code}): {err.strip()[-200:]}")
        if not CANARY_HOSTNAME.fullmatch(name):
            raise PublishError(f"{host} reports hostname {name!r}, not rosy-<name>")
        return name

    def status(self, host: str) -> dict | None:
        code, out, _err = self.ssh(host, STATUS_COMMAND)
        if code != 0:
            return None
        try:
            parsed = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return None
        return parsed if isinstance(parsed, dict) else None

    # -- canary --
    @staticmethod
    def last_result(state: dict | None) -> dict | None:
        last = (state or {}).get("last_result")
        return last if isinstance(last, dict) else None

    def watch_canary(self, host: str, name: str, timeout_min: int, published_at: str,
                     baseline: dict | None) -> tuple[bool, str]:
        """Only a result that is not the baseline and not older than published_at - skew decides."""
        not_before = parse_stamp(published_at) - dt.timedelta(seconds=CLOCK_SKEW_S)

        def fresh(stamp) -> bool:
            moment = parse_stamp(stamp)
            return moment is not None and moment >= not_before

        deadline = self.monotonic() + timeout_min * 60
        seen = None
        phase = "unreachable"
        while True:
            state = self.status(host)
            if state is None:
                phase, key, line = "unreachable", ("unreachable",), f"{name} ({host}) unreachable or status unreadable"
            elif not state.get("hostname"):
                phase, key = "not-run-yet", ("not-run-yet",)
                line = f"{name} ({host}): the updater has not run yet (no status.json)"
            elif state.get("hostname") != name:
                phase = "not-the-canary"
                key = (phase, state.get("hostname"))
                line = f"{host} status is from {state.get('hostname')!r}, not {name} ({state.get('reason') or '-'})"
            else:
                phase = str(state.get("phase"))
                last = self.last_result(state) or {}
                key = (phase, state.get("current_release"), state.get("candidate"),
                       last.get("release_id"), last.get("outcome"), last.get("at"))
                line = (f"{name} phase={phase} current={state.get('current_release')} "
                        f"candidate={state.get('candidate')} reason={state.get('reason') or '-'}")
                if last:
                    line += f" last={last.get('release_id')}:{last.get('outcome')}@{last.get('at')}"
                if last.get("release_id") == self.release_id and last != baseline and fresh(last.get("at")):
                    outcome = last.get("outcome")
                    if outcome == "committed" and state.get("current_release") == self.release_id:
                        self.log("canary-phase", line, phase=phase)
                        return True, f"canary {name} committed {self.release_id}"
                    if outcome in ("rolled_back", "refused", "image_required"):
                        self.log("canary-phase", line, phase=phase)
                        return False, f"canary {name} {outcome} {self.release_id}: {last.get('detail') or '-'}"
                # "failed" is T2's verdict on a candidate; "error" is transient (network, activator
                # timeout, busy) and only the timeout turns it into a withdraw.
                if (phase == "failed" and state.get("candidate") == self.release_id
                        and fresh(state.get("updated_at"))):
                    self.log("canary-phase", line, phase=phase)
                    return False, f"canary {name} {phase} on {self.release_id}: {state.get('reason') or '-'}"
            if key != seen:
                self.log("canary-phase", line, phase=phase)
                seen = key
            if self.monotonic() >= deadline:
                # A robot that never started says nothing about the release; unreachable or applying might.
                not_started = phase in ("idle", "staged", "waiting", "held", "ineligible", "disabled")
                return None if not_started else False, f"canary {name} did not commit within {timeout_min} min (last phase: {phase})"
            self.sleep(POLL_S)

    def show_others(self, rollout: dict, robots: list[str]) -> None:
        published = dt.datetime.strptime(rollout["published_at"], "%Y-%m-%dT%H:%M:%SZ")
        opens = published + dt.timedelta(seconds=int(rollout["wave_delay_s"]))
        print(f"other robots may apply after {opens.strftime('%Y-%m-%dT%H:%M:%SZ')} "
              "(idle, no hold, battery >= 40% or charging)", flush=True)
        for host in robots:
            state = self.status(host)
            if state is None:
                print(f"  {host}: unreachable", flush=True)
            else:
                print(f"  {host}: {state.get('hostname')} phase={state.get('phase')} "
                      f"current={state.get('current_release')} candidate={state.get('candidate')} "
                      f"reason={state.get('reason') or '-'}", flush=True)


# --- lock & withdraw -----------------------------------------------------------

def pid_alive(pid: int) -> bool:
    """Whether a process with this id exists. Never signals it (os.kill on Windows would end it)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def take_lock(work_dir: Path) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    lock = work_dir / ".lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            pid = int(lock.read_text(encoding="ascii").split()[0])
        except (OSError, ValueError, IndexError):
            pid = None
        if pid is not None and not pid_alive(pid):
            raise PublishError(f"{lock} is stale: process {pid} is not running. "
                               f"Delete it (del \"{lock}\") and run again") from None
        if pid is not None:
            raise PublishError(f"another publish of this release (process {pid}) is running and holds {lock}; "
                               "stop it (Ctrl+C) first") from None
        raise PublishError(f"another publish of this release holds {lock}; stop it (Ctrl+C) first, "
                           "or delete the file if no publish is running") from None
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(f"{os.getpid()}\n")
    return lock


def withdraw(publisher, reason: str, out_dir: Path) -> int:
    """Withdraw by hand. An unverified or missing remote rollout (a half-finished --clobber upload) falls back
    to the copy this PC signed last; only a verified GitHub copy that is already withdrawn needs nothing."""
    from_github = True
    try:
        rollout, _data = publisher.download()
    except RolloutUnverified as error:
        print(f"warning: {error}", file=sys.stderr)
        rollout, _data = publisher.local_copy()
        from_github = False
        print(f"using the local signed rollout.json in {publisher.work_dir}", flush=True)
    if from_github and rollout["withdrawn"]:
        print(f"{publisher.tag} is already withdrawn: {rollout['reason']}")
        return 0
    publisher.upload_or_explain({**rollout, "withdrawn": True, "reason": reason}, out_dir)
    publisher.log("withdrawn", f"withdrawn by hand: {reason}", reason=reason)
    return 0


# --- CLI parser helpers --------------------------------------------------------

def _nonnegative_wave(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return value


def _positive_minutes(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _matching(pattern: re.Pattern, what: str) -> Callable[[str], str]:
    def check(text: str) -> str:
        if not pattern.fullmatch(text):
            raise argparse.ArgumentTypeError(f"{text!r} is not {what}")
        return text
    return check


def build_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--tarball", type=Path, help="the signed <id>.tar.gz from prepare_payload_release.py")
    source.add_argument("--release-id", help="YYYY.MM.DD-NNN; the tarball is <out-dir>/<id>.tar.gz")
    parser.add_argument("--out-dir", type=Path, help=r"prepare's work folder (default $ROSY_SCRATCH\rosy-release-<id>, else the system temp directory)")
    parser.add_argument("--canary", help="IP or host of the canary robot")
    parser.add_argument("--robot", action="append", default=[], help="other robots, only shown after canary_ok")
    parser.add_argument("--resume", action="store_true", help="re-attach to an existing release")
    parser.add_argument("--open-wave-now", action="store_true",
                        help="with --resume, remove the wave delay after canary approval")
    parser.add_argument("--withdraw", action="store_true", help="withdraw an existing release (needs --reason)")
    parser.add_argument("--reason", help="why, for --withdraw")
    parser.add_argument("--repo", type=_matching(REPO_NAME, "OWNER/NAME"), default=REPO)
    parser.add_argument("--key-name", type=_matching(KEY_NAME, "a key name"), default="rosy-release-2026-01")
    parser.add_argument("--public-key", type=Path, help="default deploy/robot/pinky_pro/release/public-keys/<key>.pem")
    parser.add_argument("--wave-delay-s", type=_nonnegative_wave, default=0)
    parser.add_argument("--canary-timeout-min", type=_positive_minutes, default=30)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    return parser
