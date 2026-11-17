"""Publish a signed payload as a GitHub Release, let one canary robot take it, then open it to the rest (D-412).

Takes the signed tarball prepare_payload_release.py made and does what the robots' updater reads:

    python tools/release/publish_payload_release.py --tarball $ROSY_SCRATCH/rosy-release-<id>/<id>.tar.gz --canary <robot-ip>
    python tools/release/publish_payload_release.py --release-id <id> --canary <robot-ip> --resume
    python tools/release/publish_payload_release.py --release-id <id> --withdraw --reason "canary drove badly"

1. check: the tarball's own release signature (signing.verify_release_files on a temporary extract),
   `manifest.json` and `source-revision.txt`.
2. rollout: tarball sha256, source revision, the canary's hostname (`ssh rosy@<ip> hostname`, must match
   ^rosy-[a-z0-9-]+$). `rollout.json` is sorted-key LF UTF-8 JSON
   (docs/plans/2026-10-01-d412-robot-auto-update.md, schema 1).
3. sign: `signing.sign_checksums` with the operator's private key <key-name>, then verified against the
   repo public key before anything is uploaded.
4. release: create `payload-<id>` for bridges or `payload-v2-<id>` for verified boot catalogs, with the tarball,
   rollout.json.sig. An existing tag is refused unless --resume.
5. canary: `rosy_auto_update.py status --json` over ssh every 30 s for --canary-timeout-min. Only a result
   newer than the one the canary reported before the release (and not older than published_at) counts.
   A commit of this id sets canary_ok=true; a rollback or refusal of this id, a "failed" phase for it
   ("error" is transient and keeps the watch going), or a timeout after it may have started sets withdrawn=true; a timeout
   before it started exits 4 and changes nothing. The remote rollout is reread before upload: withdrawn stays, changed is refused.

New releases add no wave delay after canary success; --wave-delay-s opts into a delay.
--resume --open-wave-now removes only the delay from an already approved signed rollout.
--resume re-attaches to an existing release (its rollout.json, signature checked). --withdraw withdraws
one by hand. One process per release id (a lock file in the work folder). Every phase is printed and
appended to <evidence-dir>/<YYYY-MM-DD>/rollout.jsonl. Standard library plus the repo's signing.py.
No token, key or private-key path is ever printed.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import sys
import tarfile
import time
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
RELEASE_TOOLS = ROOT / "deploy" / "robot" / "pinky_pro" / "release"
for _p in (Path(__file__).resolve().parent, RELEASE_TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import signing  # noqa: E402
from publish_payload_release_helpers import (  # noqa: E402, F401
    CANARY_HOSTNAME,
    CANARY_NOT_STARTED,
    CLOCK_SKEW_S,
    DEFAULT_EVIDENCE,
    KEY_NAME,
    POLL_S,
    REPO,
    REPO_NAME,
    REVISION,
    SCRIPT,
    STATUS_COMMAND,
    PublishError,
    PublisherCanaryMixin,
    RolloutUnverified,
    Runner,
    _load_inspection,
    _matching,
    _nonnegative_wave,
    _positive_minutes,
    _rejections,
    build_parser,
    build_rollout,
    inspection,
    parse_stamp,
    pid_alive,
    prepare,
    read_tarball_identity,
    rollout_bytes,
    run_gh,
    sign_rollout,
    take_lock,
    utc_stamp,
    verify_tarball,
    withdraw,
)


class Publisher(PublisherCanaryMixin):
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

    def tag_exists(self, tag: str | None = None) -> bool:
        tag = tag or self.tag
        refs = json.loads(self.gh("api", f"repos/{self.repo}/git/matching-refs/tags/{tag}") or "[]")
        return any(item.get("ref") == f"refs/tags/{tag}" for item in refs)

    def existing_tag(self) -> str | None:
        tags = [tag for tag in (f"payload-{self.release_id}", f"payload-v2-{self.release_id}") if self.tag_exists(tag)]
        if len(tags) > 1:
            raise PublishError(f"release id {self.release_id} exists under both legacy and feature tags")
        return tags[0] if tags else None

    def write_signed(self, rollout: dict) -> tuple[bytes, list[Path]]:
        data = rollout_bytes(rollout)
        signature = sign_rollout(data, self.private_key, self.public_key, key_name=self.key_name)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        path, sig = self.work_dir / "rollout.json", self.work_dir / "rollout.json.sig"
        path.write_bytes(data)
        sig.write_bytes(signature.encode("ascii"))
        return data, [path, sig]

    def create(self, rollout: dict, tarball: Path, canary: str, *, delta_asset: Path | None = None) -> None:
        if delta_asset is not None:
            self.work_dir.mkdir(parents=True, exist_ok=True)
            inspection.verify_transport_delta(tarball, delta_asset, rollout["delta"], self.public_key, self.work_dir)
        data, files = self.write_signed(rollout)
        if delta_asset is not None:
            files.append(delta_asset)
        notes = (f"ROSY native payload {self.release_id} from {rollout['source_revision'][:12]}. "
                 f"Signed rollout (D-412): canary {canary} first, the rest after canary_ok.")
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
        return (f'gh release upload {self.tag} --repo {self.repo} --clobber '
                f'"{self.work_dir / "rollout.json"}" "{self.work_dir / "rollout.json.sig"}"')

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

    def finish(self, ok: bool | None, reason: str, robots: list[str], out_dir: Path) -> int:
        """Re-read the remote rollout first: never undo a withdraw, never overwrite a change made meanwhile."""
        if ok is None:
            self.log("canary-waiting", f"{reason}; rollout.json left as it is")
            return CANARY_NOT_STARTED
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

    def open_wave_now(self, robots: list[str], out_dir: Path) -> int:
        """Re-sign only the delay after canary approval, checking for concurrent edits."""
        remote, data = self.download()
        if remote["withdrawn"]:
            self.log("withdrawn", f"{self.tag} is withdrawn; left unchanged")
            return 3
        if data != self.last_uploaded:
            raise PublishError(f"{self.tag} rollout.json changed since resume; not overwriting it")
        if remote.get("canary_ok") is not True:
            raise PublishError("--open-wave-now requires canary_ok=true")
        if remote["wave_delay_s"] == 0:
            self.show_others(remote, robots)
            return 0
        target = {**remote, "wave_delay_s": 0}
        uploaded = self.upload_or_explain(target, out_dir)
        after, after_data = self.download()
        if after["withdrawn"]:
            self.log("withdrawn", f"{self.tag} was withdrawn during upload; left withdrawn")
            return 3
        if after_data != uploaded:
            raise PublishError(f"{self.tag} rollout.json changed during upload; left unchanged")
        self.last_uploaded = uploaded
        self.log("wave-open", f"{self.tag} wave_delay_s=0 uploaded; all other rollout fields preserved")
        self.show_others(target, robots)
        return 0


# --- main ------------------------------------------------------------------------

def main(argv: list[str] | None = None, *, gh_runner: Runner = run_gh, ssh_runner: Runner | None = None,
         now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.timezone.utc),
         monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
         transport_delta: tuple[Path, dict] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser(__doc__.split("\n\n")[0])
    args = parser.parse_args(argv)
    if args.open_wave_now and (not args.resume or args.withdraw):
        parser.error("--open-wave-now requires --resume and cannot be combined with --withdraw")

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
        if args.resume or args.withdraw:
            publisher.tag = publisher.existing_tag() or publisher.tag
        if args.withdraw:
            return withdraw(publisher, args.reason.strip(), out_dir)

        if args.resume:
            rollout, publisher.last_uploaded = publisher.download()
            publisher.log("resume", f"re-attached to {publisher.tag}: canary_ok={rollout['canary_ok']} withdrawn={rollout['withdrawn']}")
            if rollout["withdrawn"]:
                print(f"error: {publisher.tag} is withdrawn ({rollout['reason']}); publish a new release", file=sys.stderr)
                return 3
            if args.open_wave_now:
                return publisher.open_wave_now(args.robot, out_dir)
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
            feature = verify_tarball(tarball, publisher.public_key, publisher.work_dir)
            publisher.tag = f"payload-{'v2-' if feature else ''}{release_id}"
            existing = publisher.existing_tag()
            if existing:
                raise PublishError(f"tag {existing} already exists on {args.repo}; "
                                   "pass --resume to re-attach, or use a new release id")
            canary = publisher.hostname(args.canary)
            before = publisher.status(args.canary)
            baseline = publisher.last_result(before) if (before or {}).get("hostname") == canary else None
            rollout = build_rollout(tarball_id, signing.sha256_file(tarball), revision,
                                    utc_stamp(now()), canary, args.wave_delay_s)
            if transport_delta is not None:
                rollout["delta"] = transport_delta[1]
            publisher.log("rollout", f"{rollout['tarball']} sha256 {rollout['tarball_sha256']}, canary {canary}, "
                                     f"wave delay {args.wave_delay_s}s, canary last result before: {baseline}")
            if transport_delta is None:
                publisher.create(rollout, tarball, canary)
            else:
                publisher.create(rollout, tarball, canary, delta_asset=transport_delta[0])

        publisher.log("canary-watch", f"watching {canary} ({args.canary}) every {POLL_S}s for up to {args.canary_timeout_min} min")
        ok, reason = publisher.watch_canary(args.canary, canary, args.canary_timeout_min, rollout["published_at"], baseline)
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


if __name__ == "__main__":
    sys.exit(main())
