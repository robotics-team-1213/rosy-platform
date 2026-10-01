"""Publish a signed payload as a GitHub Release, let one canary robot take it, then open it to the rest (D-406).

Takes the signed tarball prepare_payload_release.py made and does what the robots' updater reads:

    python tools/release/publish_payload_release.py --tarball X:/DevTemp/rosy-release-<id>/<id>.tar.gz --canary 192.168.1.202
    python tools/release/publish_payload_release.py --release-id <id> --canary 192.168.1.202 --resume
    python tools/release/publish_payload_release.py --release-id <id> --withdraw --reason "canary drove badly"

1. rollout: tarball sha256, `source-revision.txt` and `manifest.json` from the tarball, the canary's
   hostname (`ssh rosy@<ip> hostname`, must match ^rosy-[a-z0-9-]+$). `rollout.json` is sorted-key
   LF UTF-8 JSON (docs/plans/2026-10-01-d406-robot-auto-update.md, schema 1).
2. sign: `signing.sign_checksums` with %LOCALAPPDATA%/Rosy/signing/<key>.private.pem, then verified
   against the repo public key before anything is uploaded.
3. release: `gh release create payload-<id> --target <source_revision>` with the tarball, rollout.json and
   rollout.json.sig. An existing tag is refused unless --resume.
4. canary: `rosy_auto_update.py status --json` over ssh every 30 s for --canary-timeout-min. A commit of
   this id sets canary_ok=true; a rollback or refusal of this id, or the timeout, sets withdrawn=true.
   Either way rollout.json is re-signed and re-uploaded (`gh release upload --clobber`).

--resume re-attaches to an existing release (its rollout.json, signature checked). --withdraw withdraws
one by hand. Every phase is printed and appended to <evidence-dir>/<YYYY-MM-DD>/rollout.jsonl.
Standard library plus the repo's signing.py. No token or key is ever printed.
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
import time
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
RELEASE_TOOLS = ROOT / "deploy" / "robot" / "pinky_pro" / "release"
if str(RELEASE_TOOLS) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOLS))
import signing  # noqa: E402

REPO = "livsbittt/rosy-os"
CANARY_HOSTNAME = re.compile(r"rosy-[a-z0-9-]+")
REVISION = re.compile(r"[0-9a-f]{40}")
STATUS_COMMAND = "sudo -n python3 /opt/rosy/native-runtime/rosy_auto_update.py status --json"
POLL_S = 30
DEFAULT_EVIDENCE = Path("X:/DevTemp/rosy-rollout-evidence")

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


# --- rollout.json --------------------------------------------------------------

def utc_stamp(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_rollout(release_id: str, tarball_sha256: str, source_revision: str, published_at: str,
                  canary: str, wave_delay_s: int) -> dict:
    return {"schema": 1, "release_id": release_id, "tarball": f"{release_id}.tar.gz",
            "tarball_sha256": tarball_sha256, "source_revision": source_revision,
            "published_at": published_at, "canary": [canary], "canary_ok": False,
            "wave_delay_s": wave_delay_s, "withdrawn": False, "reason": ""}


def rollout_bytes(rollout: dict) -> bytes:
    """The exact bytes that are signed: sorted keys, LF, UTF-8, no BOM."""
    return (json.dumps(rollout, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def sign_rollout(data: bytes, private_key: Path, public_key: Path,
                 signer: Callable[[bytes, Path], str] = signing.sign_checksums) -> str:
    """Sign, then verify against the public key the robots trust before anything leaves this PC."""
    signature = signer(data, private_key)
    rejections = signing.verify_signature(data, signature, public_key)
    if rejections:
        raise PublishError("rollout.json self-verify failed: " + "; ".join(f"{r.code}: {r.detail}" for r in rejections))
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


# --- runners ---------------------------------------------------------------------

def run_gh(argv: list[str]) -> tuple[int, str, str]:
    try:
        done = subprocess.run(argv, capture_output=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, "", f"{type(error).__name__}: {error}"
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


class Publisher:
    # Plain class, not @dataclass: the tests load this file by path without a sys.modules entry.
    def __init__(self, *, release_id: str, repo: str, work_dir: Path, private_key: Path, public_key: Path,
                 local_appdata: Path, evidence_dir: Path, gh: Runner, ssh: Runner,
                 now: Callable[[], dt.datetime], monotonic: Callable[[], float], sleep: Callable[[float], None]):
        self.release_id = release_id
        self.tag = f"payload-{release_id}"
        self.repo = repo
        self.work_dir = work_dir
        self.private_key = private_key
        self.public_key = public_key
        self.local_appdata = local_appdata
        self.evidence_dir = evidence_dir
        self._gh, self._ssh = gh, ssh
        self.now, self.monotonic, self.sleep = now, monotonic, sleep

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

    def write_signed(self, rollout: dict) -> list[Path]:
        data = rollout_bytes(rollout)
        signature = sign_rollout(data, self.private_key, self.public_key)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        path, sig = self.work_dir / "rollout.json", self.work_dir / "rollout.json.sig"
        path.write_bytes(data)
        sig.write_bytes(signature.encode("ascii"))
        return [path, sig]

    def create(self, rollout: dict, tarball: Path, canary: str) -> None:
        files = self.write_signed(rollout)
        notes = (f"ROSY native payload {self.release_id} from {rollout['source_revision'][:12]}. "
                 f"Signed rollout (D-406): canary {canary} first, the rest after canary_ok.")
        self.gh("release", "create", self.tag, "--repo", self.repo, "--target", rollout["source_revision"],
                "--title", self.tag, "--notes", notes, str(tarball), *map(str, files))
        self.log("release-created", f"{self.tag} on {self.repo} at {rollout['source_revision']}",
                 tarball_sha256=rollout["tarball_sha256"], canary=canary)

    def upload(self, rollout: dict) -> None:
        files = self.write_signed(rollout)
        self.gh("release", "upload", self.tag, "--repo", self.repo, "--clobber", *map(str, files))

    def download(self) -> dict:
        target = self.work_dir / "downloaded"
        self.gh("release", "download", self.tag, "--repo", self.repo, "--pattern", "rollout.json",
                "--pattern", "rollout.json.sig", "--dir", str(target), "--clobber")
        data = (target / "rollout.json").read_bytes()
        signature = (target / "rollout.json.sig").read_text(encoding="ascii")
        rejections = signing.verify_signature(data, signature, self.public_key)
        if rejections:
            raise PublishError(f"{self.tag} rollout.json does not verify: "
                               + "; ".join(f"{r.code}: {r.detail}" for r in rejections))
        rollout = json.loads(data.decode("utf-8"))
        if rollout.get("schema") != 1 or rollout.get("release_id") != self.release_id:
            raise PublishError(f"{self.tag} rollout.json is not schema 1 for {self.release_id}")
        return rollout

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
    def watch_canary(self, host: str, name: str, timeout_min: int) -> tuple[bool, str]:
        deadline = self.monotonic() + timeout_min * 60
        seen = None
        phase = "unreachable"
        while True:
            state = self.status(host)
            if state is None:
                phase, key, line = "unreachable", ("unreachable",), f"{name} ({host}) unreachable or status unreadable"
            else:
                phase = str(state.get("phase"))
                last = state.get("last_result") if isinstance(state.get("last_result"), dict) else {}
                key = (phase, state.get("current_release"), state.get("candidate"),
                       last.get("release_id"), last.get("outcome"))
                line = (f"{name} phase={phase} current={state.get('current_release')} "
                        f"candidate={state.get('candidate')} reason={state.get('reason') or '-'}")
                if last:
                    line += f" last={last.get('release_id')}:{last.get('outcome')}"
                if last.get("release_id") == self.release_id:
                    outcome = last.get("outcome")
                    if outcome == "committed" and state.get("current_release") == self.release_id:
                        self.log("canary-phase", line, phase=phase)
                        return True, f"canary {name} committed {self.release_id}"
                    if outcome in ("rolled_back", "refused"):
                        self.log("canary-phase", line, phase=phase)
                        return False, f"canary {name} {outcome} {self.release_id}: {last.get('detail') or '-'}"
            if key != seen:
                self.log("canary-phase", line, phase=phase)
                seen = key
            if self.monotonic() >= deadline:
                return False, f"canary {name} did not commit within {timeout_min} min (last phase: {phase})"
            self.sleep(POLL_S)

    def finish(self, rollout: dict, ok: bool, reason: str, robots: list[str]) -> int:
        if ok:
            rollout = {**rollout, "canary_ok": True}
            self.upload(rollout)
            self.log("canary-ok", f"{reason}; rollout.json canary_ok=true uploaded")
            self.show_others(rollout, robots)
            return 0
        rollout = {**rollout, "withdrawn": True, "reason": reason}
        self.upload(rollout)
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
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--key-name", default="rosy-release-2026-01")
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
        release_id=release_id, repo=args.repo, work_dir=out_dir / f"publish-{release_id}",
        private_key=local_appdata / "Rosy" / "signing" / f"{args.key_name}.private.pem",
        public_key=args.public_key or RELEASE_TOOLS / "public-keys" / f"{args.key_name}.pem",
        local_appdata=local_appdata, evidence_dir=args.evidence_dir, gh=gh_runner,
        ssh=ssh_runner or prepare.run_ssh, now=now, monotonic=monotonic, sleep=sleep)
    try:
        for key in (publisher.private_key, publisher.public_key):
            if not key.is_file():
                raise PublishError(f"signing key not found: {key}")
        if args.withdraw:
            rollout = publisher.download()
            if rollout["withdrawn"]:
                print(f"{publisher.tag} is already withdrawn: {rollout['reason']}")
                return 0
            publisher.upload({**rollout, "withdrawn": True, "reason": args.reason.strip()})
            publisher.log("withdrawn", f"withdrawn by hand: {args.reason.strip()}", reason=args.reason.strip())
            return 0

        if args.resume:
            rollout = publisher.download()
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
        else:
            if not tarball.is_file():
                raise PublishError(f"signed tarball not found: {tarball}")
            tarball_id, revision = read_tarball_identity(tarball)
            if publisher.tag_exists():
                raise PublishError(f"tag {publisher.tag} already exists on {args.repo}; "
                                   "pass --resume to re-attach, or use a new release id")
            canary = publisher.hostname(args.canary)
            rollout = build_rollout(tarball_id, signing.sha256_file(tarball), revision,
                                    utc_stamp(now()), canary, args.wave_delay_s)
            publisher.log("rollout", f"{rollout['tarball']} sha256 {rollout['tarball_sha256']}, "
                                     f"canary {canary}, wave delay {args.wave_delay_s}s")
            publisher.create(rollout, tarball, canary)

        publisher.log("canary-watch", f"watching {canary} ({args.canary}) every {POLL_S}s "
                                      f"for up to {args.canary_timeout_min} min")
        ok, reason = publisher.watch_canary(args.canary, canary, args.canary_timeout_min)
        return publisher.finish(rollout, ok, reason, args.robot)
    # ValueError covers json.JSONDecodeError and UnicodeDecodeError; EOFError is a truncated gzip.
    except (PublishError, signing.SigningToolMissing, RuntimeError, OSError, EOFError, ValueError,
            KeyError, tarfile.TarError) as error:
        print(f"error: {error}", file=sys.stderr)
        try:
            publisher.log("error", str(error))
        except OSError:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
