"""Publish a signed payload as a GitHub Release, let one canary robot take it, then open it to the rest (D-410).

Takes the signed tarball prepare_payload_release.py made and does what the robots' updater reads:

    python tools/release/publish_payload_release.py --tarball X:/DevTemp/rosy-release-<id>/<id>.tar.gz --canary 192.168.1.202
    python tools/release/publish_payload_release.py --release-id <id> --canary 192.168.1.202 --resume
    python tools/release/publish_payload_release.py --release-id <id> --withdraw --reason "canary drove badly"

1. check: the tarball's own release signature (signing.verify_release_files on a temporary extract),
   `manifest.json` and `source-revision.txt`.
2. rollout: tarball sha256, source revision, the canary's hostname (`ssh rosy@<ip> hostname`, must match
   ^rosy-[a-z0-9-]+$). `rollout.json` is sorted-key LF UTF-8 JSON
   (docs/plans/2026-10-01-d410-robot-auto-update.md, schema 1).
3. sign: `signing.sign_checksums` with the operator's private key <key-name>, then verified against the
   repo public key before anything is uploaded.
4. release: `gh release create payload-<id> --target <source_revision>` with the tarball, rollout.json and
   rollout.json.sig. An existing tag is refused unless --resume.
5. canary: `rosy_auto_update.py status --json` over ssh every 30 s for --canary-timeout-min. Only a result
   newer than the one the canary reported before the release (and not older than published_at) counts.
   A commit of this id sets canary_ok=true; a rollback or refusal of this id, a "failed" phase for it
   ("error" is transient and keeps the watch going), or the timeout sets withdrawn=true. Before re-uploading, the remote rollout is downloaded again:
   one withdrawn meanwhile stays withdrawn, and one that changed otherwise is never overwritten.

--resume re-attaches to an existing release (its rollout.json, signature checked). --withdraw withdraws
one by hand. One process per release id (a lock file in the work folder). Every phase is printed and
appended to <evidence-dir>/<YYYY-MM-DD>/rollout.jsonl. Standard library plus the repo's signing.py.
No token, key or private-key path is ever printed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
RELEASE_TOOLS = ROOT / "deploy" / "robot" / "pinky_pro" / "release"
if str(RELEASE_TOOLS) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOLS))
import signing  # noqa: E402

REPO = "livsbittt/rosy-os"
REPO_NAME = re.compile(r"[\w.-]+/[\w.-]+")
KEY_NAME = re.compile(r"[\w.-]+")
CANARY_HOSTNAME = re.compile(r"rosy-[a-z0-9-]+")
REVISION = re.compile(r"[0-9a-f]{40}")
STATUS_COMMAND = "sudo -n python3 /opt/rosy/native-runtime/rosy_auto_update.py status --json"
POLL_S = 30
#: Robot and PC clocks are NTP-synced; allow this much when comparing a robot's result time to published_at.
CLOCK_SKEW_S = 120
DEFAULT_EVIDENCE = Path("X:/DevTemp/rosy-rollout-evidence")
SCRIPT = r"python tools\release\publish_payload_release.py"

Runner = Callable[[list[str]], tuple[int, str, str]]


def _load_prepare():
    spec = importlib.util.spec_from_file_location("prepare_payload_release",
                                                  Path(__file__).with_name("prepare_payload_release.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = _load_prepare()


class PublishError(RuntimeError):
    pass


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


def build_rollout(release_id: str, tarball_sha256: str, source_revision: str, published_at: str,
                  canary: str, wave_delay_s: int) -> dict:
    return {"schema": 1, "release_id": release_id, "tarball": f"{release_id}.tar.gz",
            "tarball_sha256": tarball_sha256, "source_revision": source_revision,
            "published_at": published_at, "canary": [canary], "canary_ok": False,
            "wave_delay_s": wave_delay_s, "withdrawn": False, "reason": ""}


def rollout_bytes(rollout: dict) -> bytes:
    """The exact bytes that are signed: sorted keys, LF, UTF-8, no BOM."""
    return (json.dumps(rollout, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def _rejections(rejections) -> str:
    return "; ".join(f"{r.code} {r.field}: {r.detail}" for r in rejections)


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


def read_tarball_identity(tarball: Path) -> tuple[str, str]:
    """(release_id from manifest.json, source_revision from source-revision.txt)."""
    found: dict[str, bytes] = {}
    with tarfile.open(tarball, "r:gz") as tar:
        for member in tar:
            name = str(PurePosixPath(member.name)).removeprefix("./")
            if name in ("manifest.json", "source-revision.txt") and member.isreg():
                found[name] = tar.extractfile(member).read()
    for name in ("manifest.json", "source-revision.txt"):
        if name not in found:
            raise PublishError(f"{tarball.name} has no top-level {name}")
    release_id = json.loads(found["manifest.json"].decode("utf-8")).get("release_id")
    if release_id != tarball.name.removesuffix(".tar.gz"):
        raise PublishError(f"manifest.json release_id is {release_id!r}, not the tarball name {tarball.name}")
    revision = found["source-revision.txt"].decode("ascii").strip()
    if not REVISION.fullmatch(revision):
        raise PublishError(f"source-revision.txt is not a full Git commit: {revision!r}")
    return release_id, revision


def verify_tarball(tarball: Path, public_key: Path, work_dir: Path) -> None:
    """The release signature over SHA256SUMS and every file, on a temporary extract (the robot checks it too)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".verify-", dir=work_dir))
    try:
        with tarfile.open(tarball, "r:gz") as tar:
            for member in tar:
                if member.issym() or member.islnk():
                    raise PublishError(f"{tarball.name} has a link member {member.name!r}")
            tar.extractall(temporary, filter="tar")
        rejections = signing.verify_release_files(temporary, public_key)
        if rejections:
            raise PublishError(f"{tarball.name} release signature does not verify: {_rejections(rejections)}")
    finally:
        prepare._remove_tree(temporary)


# --- runners ---------------------------------------------------------------------

def run_gh(argv: list[str]) -> tuple[int, str, str]:
    try:
        done = subprocess.run(argv, capture_output=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, "", f"{type(error).__name__}: {error}"
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


class Publisher:
    # Plain class, not @dataclass: the tests load this file by path without a sys.modules entry.
    def __init__(self, *, release_id: str, repo: str, work_dir: Path, key_name: str, private_key: Path,
                 public_key: Path, local_appdata: Path, evidence_dir: Path, gh: Runner, ssh: Runner,
                 now: Callable[[], dt.datetime], monotonic: Callable[[], float], sleep: Callable[[float], None]):
        self.release_id = release_id
        self.tag = f"payload-{release_id}"
        self.repo = repo
        self.work_dir = work_dir
        self.key_name = key_name
        self.private_key = private_key
        self.public_key = public_key
        self.local_appdata = local_appdata
        self.evidence_dir = evidence_dir
        self._gh, self._ssh = gh, ssh
        self.now, self.monotonic, self.sleep = now, monotonic, sleep
        #: The rollout.json bytes this process last put on GitHub (or found there on --resume).
        self.last_uploaded: bytes | None = None

    # -- output and audit --
    def log(self, event: str, message: str, **fields) -> None:
        print(f"[{event}] {message}", flush=True)
        moment = self.now()
        folder = self.evidence_dir / moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        record = {"at": utc_stamp(moment), "event": event, "release_id": self.release_id,
                  "detail": message, **fields}
        with (folder / "rollout.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    # -- gh --
    def gh(self, *args: str) -> str:
        code, out, err = self._gh(["gh", *args])
        if code != 0:
            detail = (err.strip().splitlines() or ["no output"])[-1]
            raise PublishError(f"gh {args[0]} {args[1] if len(args) > 1 else ''} failed (exit {code}): {detail}")
        return out

    def tag_exists(self) -> bool:
        refs = json.loads(self.gh("api", f"repos/{self.repo}/git/matching-refs/tags/{self.tag}") or "[]")
        return any(item.get("ref") == f"refs/tags/{self.tag}" for item in refs)

    def write_signed(self, rollout: dict) -> tuple[bytes, list[Path]]:
        data = rollout_bytes(rollout)
        signature = sign_rollout(data, self.private_key, self.public_key, key_name=self.key_name)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        path, sig = self.work_dir / "rollout.json", self.work_dir / "rollout.json.sig"
        path.write_bytes(data)
        sig.write_bytes(signature.encode("ascii"))
        return data, [path, sig]

    def create(self, rollout: dict, tarball: Path, canary: str) -> None:
        data, files = self.write_signed(rollout)
        notes = (f"ROSY native payload {self.release_id} from {rollout['source_revision'][:12]}. "
                 f"Signed rollout (D-410): canary {canary} first, the rest after canary_ok.")
        self.gh("release", "create", self.tag, "--repo", self.repo, "--target", rollout["source_revision"],
                "--title", self.tag, "--notes", notes, str(tarball), *map(str, files))
        self.last_uploaded = data
        self.log("release-created", f"{self.tag} on {self.repo} at {rollout['source_revision']}",
                 tarball_sha256=rollout["tarball_sha256"], canary=canary)

    def upload(self, rollout: dict) -> bytes:
        data, files = self.write_signed(rollout)
        self.gh("release", "upload", self.tag, "--repo", self.repo, "--clobber", *map(str, files))
        return data

    def upload_or_explain(self, rollout: dict, out_dir: Path) -> bytes:
        """Upload; on failure print the exact commands that finish the job, then re-raise."""
        try:
            return self.upload(rollout)
        except PublishError:
            state = "withdrawn=true" if rollout["withdrawn"] else "canary_ok=true"
            print(f"recovery: {self.work_dir} holds rollout.json signed with {state}. Upload it with\n"
                  f"  {self.upload_command()}", file=sys.stderr)
            if rollout["withdrawn"]:
                print(f"or withdraw again:\n  {SCRIPT} --release-id {self.release_id} --out-dir \"{out_dir}\" "
                      f"--withdraw --reason \"{rollout['reason']}\"", file=sys.stderr)
            raise

    def upload_command(self) -> str:
        files = " ".join(f'"{self.work_dir / name}"' for name in ("rollout.json", "rollout.json.sig"))
        return f"gh release upload {self.tag} --repo {self.repo} --clobber {files}"

    def _verified(self, data: bytes, signature: str, where: str) -> dict:
        rejections = signing.verify_signature(data, signature, self.public_key)
        if rejections:
            raise RolloutUnverified(f"{where} rollout.json does not verify: {_rejections(rejections)}")
        rollout = json.loads(data.decode("utf-8"))
        if not isinstance(rollout, dict) or rollout.get("schema") != 1 or rollout.get("release_id") != self.release_id:
            raise PublishError(f"{where} rollout.json is not schema 1 for {self.release_id}")
        return rollout

    def download(self) -> tuple[dict, bytes]:
        """GitHub's rollout, signature checked. A missing asset is RolloutUnverified, like a bad signature."""
        target = self.work_dir / "downloaded"
        if target.exists():
            prepare._remove_tree(target)  # never verify against a file an earlier download left
        try:
            self.gh("release", "download", self.tag, "--repo", self.repo, "--pattern", "rollout.json",
                    "--pattern", "rollout.json.sig", "--dir", str(target), "--clobber")
        except PublishError as error:
            if "no assets match" in str(error):
                raise RolloutUnverified(f"{self.tag} has neither rollout.json nor rollout.json.sig on GitHub") from None
            raise
        missing = [name for name in ("rollout.json", "rollout.json.sig") if not (target / name).is_file()]
        if missing:
            raise RolloutUnverified(f"{self.tag} on GitHub has no {' or '.join(missing)}")
        data = (target / "rollout.json").read_bytes()
        signature = (target / "rollout.json.sig").read_text(encoding="ascii")
        return self._verified(data, signature, f"{self.tag} (GitHub)"), data

    def local_copy(self) -> tuple[dict, bytes]:
        data = (self.work_dir / "rollout.json").read_bytes()
        signature = (self.work_dir / "rollout.json.sig").read_text(encoding="ascii")
        return self._verified(data, signature, f"local {self.work_dir}"), data

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
                    if outcome in ("rolled_back", "refused"):
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
                return False, f"canary {name} did not commit within {timeout_min} min (last phase: {phase})"
            self.sleep(POLL_S)

    def finish(self, ok: bool, reason: str, robots: list[str], out_dir: Path) -> int:
        """Re-read the remote rollout first: never undo a withdraw, never overwrite a change made meanwhile."""
        remote, data = self.download()
        if remote["withdrawn"]:
            self.log("withdrawn", f"{self.tag} was withdrawn meanwhile ({remote['reason']}); left as it is",
                     reason=remote["reason"])
            return 3
        if data != self.last_uploaded:
            raise PublishError(f"{self.tag} rollout.json changed on GitHub since this process uploaded it; "
                               "not overwriting it. Read it, then rerun with --resume or --withdraw")
        if ok:
            target = {**remote, "canary_ok": True}
        else:
            target = {**remote, "withdrawn": True, "reason": reason}
        uploaded = self.upload_or_explain(target, out_dir)
        # A withdraw that raced this upload must win: look once more.
        try:
            after, after_data = self.download()
        except RolloutUnverified:
            after, after_data = None, None
        if after_data != uploaded:
            if after is not None and after["withdrawn"]:
                self.log("withdrawn", f"{self.tag} was withdrawn during the final upload ({after['reason']}); "
                                      "left withdrawn", reason=after["reason"])
                return 3
            again = target["reason"] if target["withdrawn"] else \
                "rollout.json changed during the final upload; withdrawn to be safe"
            self.upload_or_explain({**target, "withdrawn": True, "reason": again}, out_dir)
            self.log("withdrawn", f"{again}; rollout.json withdrawn=true uploaded again", reason=again)
            return 3
        if ok:
            self.log("canary-ok", f"{reason}; rollout.json canary_ok=true uploaded")
            self.show_others(target, robots)
            return 0
        self.log("withdrawn", f"{reason}; rollout.json withdrawn=true uploaded", reason=reason)
        return 3

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


# --- lock --------------------------------------------------------------------------

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


# --- main ------------------------------------------------------------------------

def _positive_wave(text: str) -> int:
    value = int(text)
    if value < 60:
        raise argparse.ArgumentTypeError("must be at least 60")
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


def main(argv: list[str] | None = None, *, gh_runner: Runner = run_gh, ssh_runner: Runner | None = None,
         now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.timezone.utc),
         monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--tarball", type=Path, help="the signed <id>.tar.gz from prepare_payload_release.py")
    source.add_argument("--release-id", help="YYYY.MM.DD-NNN; the tarball is <out-dir>/<id>.tar.gz")
    parser.add_argument("--out-dir", type=Path, help=r"prepare's work folder (default X:\DevTemp\rosy-release-<id>)")
    parser.add_argument("--canary", help="IP or host of the canary robot")
    parser.add_argument("--robot", action="append", default=[], help="other robots, only shown after canary_ok")
    parser.add_argument("--resume", action="store_true", help="re-attach to an existing release")
    parser.add_argument("--withdraw", action="store_true", help="withdraw an existing release (needs --reason)")
    parser.add_argument("--reason", help="why, for --withdraw")
    parser.add_argument("--repo", type=_matching(REPO_NAME, "OWNER/NAME"), default=REPO)
    parser.add_argument("--key-name", type=_matching(KEY_NAME, "a key name"), default="rosy-release-2026-01")
    parser.add_argument("--public-key", type=Path, help="default deploy/robot/pinky_pro/release/public-keys/<key>.pem")
    parser.add_argument("--wave-delay-s", type=_positive_wave, default=600)
    parser.add_argument("--canary-timeout-min", type=_positive_minutes, default=30)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args(argv)

    if args.withdraw:
        if not args.reason or not args.reason.strip() or "\n" in args.reason or len(args.reason) > 300:
            parser.error("--withdraw needs --reason <one line, at most 300 characters>")
        if args.resume:
            parser.error("--withdraw and --resume are separate actions")
    elif args.reason is not None:
        parser.error("--reason is only for --withdraw")
    elif not args.canary:
        parser.error("pass --canary <robot-ip>")
    for host in [args.canary, *args.robot]:
        if host is not None and not prepare.HOST.fullmatch(host):
            parser.error(f"{host!r} is not a host name or address")

    if args.tarball is not None:
        release_id = args.tarball.name.removesuffix(".tar.gz")
        out_dir = args.out_dir or args.tarball.parent
        tarball = args.tarball
    else:
        release_id = args.release_id
        out_dir = args.out_dir or prepare.default_out_dir(release_id)
        tarball = out_dir / f"{release_id}.tar.gz"
    if not prepare.RELEASE_ID.fullmatch(release_id):
        parser.error(f"release id {release_id!r} is not YYYY.MM.DD-NNN")

    local_appdata = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    publisher = Publisher(
        release_id=release_id, repo=args.repo, work_dir=out_dir / f"publish-{release_id}", key_name=args.key_name,
        private_key=local_appdata / "Rosy" / "signing" / f"{args.key_name}.private.pem",
        public_key=args.public_key or RELEASE_TOOLS / "public-keys" / f"{args.key_name}.pem",
        local_appdata=local_appdata, evidence_dir=args.evidence_dir, gh=gh_runner,
        ssh=ssh_runner or prepare.run_ssh, now=now, monotonic=monotonic, sleep=sleep)
    lock = None
    try:
        lock = take_lock(publisher.work_dir)
        if not publisher.private_key.is_file():
            raise PublishError(f"private signing key {args.key_name} not found in the operator signing folder")
        if not publisher.public_key.is_file():
            raise PublishError(f"public key not found: {publisher.public_key}")
        if args.withdraw:
            return withdraw(publisher, args.reason.strip(), out_dir)

        if args.resume:
            rollout, publisher.last_uploaded = publisher.download()
            publisher.log("resume", f"re-attached to {publisher.tag}: canary_ok={rollout['canary_ok']} "
                                    f"withdrawn={rollout['withdrawn']}")
            if rollout["withdrawn"]:
                print(f"error: {publisher.tag} is withdrawn ({rollout['reason']}); publish a new release",
                      file=sys.stderr)
                return 3
            if rollout["canary_ok"]:
                publisher.show_others(rollout, args.robot)
                return 0
            canary = publisher.hostname(args.canary)
            if canary not in rollout["canary"]:
                raise PublishError(f"{args.canary} is {canary}, not a canary of this rollout {rollout['canary']}")
            baseline = None  # unknown after a restart; published_at alone bounds what counts
        else:
            if not tarball.is_file():
                raise PublishError(f"signed tarball not found: {tarball}")
            tarball_id, revision = read_tarball_identity(tarball)
            verify_tarball(tarball, publisher.public_key, publisher.work_dir)
            if publisher.tag_exists():
                raise PublishError(f"tag {publisher.tag} already exists on {args.repo}; "
                                   "pass --resume to re-attach, or use a new release id")
            canary = publisher.hostname(args.canary)
            before = publisher.status(args.canary)
            baseline = publisher.last_result(before) if (before or {}).get("hostname") == canary else None
            rollout = build_rollout(tarball_id, signing.sha256_file(tarball), revision,
                                    utc_stamp(now()), canary, args.wave_delay_s)
            publisher.log("rollout", f"{rollout['tarball']} sha256 {rollout['tarball_sha256']}, "
                                     f"canary {canary}, wave delay {args.wave_delay_s}s, "
                                     f"canary last result before: {baseline}")
            publisher.create(rollout, tarball, canary)

        publisher.log("canary-watch", f"watching {canary} ({args.canary}) every {POLL_S}s "
                                      f"for up to {args.canary_timeout_min} min")
        ok, reason = publisher.watch_canary(args.canary, canary, args.canary_timeout_min,
                                            rollout["published_at"], baseline)
        return publisher.finish(ok, reason, args.robot, out_dir)
    except KeyboardInterrupt:
        print(f"\ninterrupted. {publisher.tag} is left as it is on GitHub; robots other than the canary wait.\n"
              f"continue watching:\n  {SCRIPT} --release-id {release_id} --out-dir \"{out_dir}\" "
              f"--canary {args.canary or '<canary-ip>'} --resume\n"
              f"or withdraw it:\n  {SCRIPT} --release-id {release_id} --out-dir \"{out_dir}\" "
              "--withdraw --reason \"<why>\"", file=sys.stderr)
        return 130
    # ValueError covers json.JSONDecodeError and UnicodeDecodeError; EOFError is a truncated gzip.
    except (PublishError, signing.SigningToolMissing, RuntimeError, OSError, EOFError, ValueError,
            KeyError, tarfile.TarError) as error:
        print(f"error: {error}", file=sys.stderr)
        try:
            publisher.log("error", str(error))
        except OSError:
            pass
        return 1
    finally:
        if lock is not None:
            lock.unlink(missing_ok=True)


def withdraw(publisher: Publisher, reason: str, out_dir: Path) -> int:
    """Withdraw by hand. A remote rollout that does not verify or is missing (a half-finished --clobber
    upload) falls back to the copy this PC signed last in the work folder, and then always uploads:
    only a verified GitHub copy that is already withdrawn needs nothing."""
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


if __name__ == "__main__":
    sys.exit(main())
