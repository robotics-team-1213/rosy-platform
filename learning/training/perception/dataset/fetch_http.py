"""D-411 A: pull finished Pilot recordings over CORE HTTP (no SSH), verify every byte against
the robot's sha256 manifest, convert with bag_to_video and check frame/action pairing.

Usage: fetch_http.py <base> [--token-file FILE] [--dest data/perception/raw]
                     [--video-out data/teleop/learning] [--codec hevc|h264] [--only ID]
                     [--ca-file DEVICE-CA.pem]

`rosy_ml fetch` fills <base> from the robot's `_rosy._tcp` advertisement
(`https://<tls_host>:<port>` when it says tls=required, with --ca-file).
http:// stays for a bench that already has a URL.

Only while CORE says the robot is stopped (D-136 §6, API Ref §5.10): the listing names the
blocker and the tool exits 4. The archive needs an Operator token (harvest's viewer token is
not enough) read from a file, or the file named by ROSY_CORE_OPERATOR_TOKEN_FILE, never argv.
A 401/403 stops the run at once with exit 2. Redirects are refused: the bearer token goes only
to the URL given.

Per recording: <dest>/.part-<id>.tar -> safe extract into <dest>/.staging-<id>/ -> sha256 and
size check against manifest.json -> <dest>/<id>/ -> bag_to_video -> pair check (frames with
both cmd_vel and teleop/intent). The tar and its extraction sit side by side, so the PC needs
about twice the recording's size free in <dest>. Leftovers of an earlier interrupted run are
removed first. A body shorter than Content-Length means CORE aborted the download (the robot
moved or a recording started): the partial is deleted and the recording is fetched again from
zero on a later run. A recording already in <dest>/<id> is skipped.

Exit codes: 0 all fetched, 1 some recording failed, 2 bad arguments or token refused,
4 robot not idle.
"""
import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import ssl
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

EXIT_NOT_IDLE = 4
EXIT_TOKEN = 2
TOKEN_ENV = "ROSY_CORE_OPERATOR_TOKEN_FILE"
# core_common.protocol.recording (not imported: this tool runs without the robot tree).
MANIFEST_SCHEMA = "rosy.pilot.recording.manifest/1"
MANIFEST_NAME = "manifest.json"
INTENT_TOPIC = "teleop/intent"
RECORDING_ID = re.compile(r"\d{8}T\d{6}Z_[A-Za-z0-9_.-]{1,64}")
CHUNK = 1 << 20
DEFAULT_DEST = "data/perception/raw"
LIST_TIMEOUT_S = 15.0
# A member must also land as a plain file on Windows: no reserved characters or device names.
_WINDOWS_CHARS = set(':<>"|?*')
_WINDOWS_NAMES = re.compile(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", re.I)
_TOKEN_HELP = "needs an Operator token (rosy_ml init --core-operator-token-file <file>)"


class FetchError(Exception):
    pass


class NotIdle(FetchError):
    """CORE refused or cut the transfer because the robot is not idle (or busy)."""


class TokenRefused(FetchError):
    """401/403: the token is wrong or not an Operator's — every further request fails too."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None          # urllib then raises the 3xx as an HTTPError


_OPENER = urllib.request.build_opener(_NoRedirect)


def build_opener(ca_file=None):
    """HTTP opener. A device CA pins HTTPS to that robot and still refuses redirects."""
    if not ca_file:
        return _OPENER
    context = ssl.create_default_context(cafile=str(ca_file))
    return urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=context))


def _id_ok(value) -> bool:
    return isinstance(value, str) and RECORDING_ID.fullmatch(value) is not None \
        and not value.endswith("_")


def _safe_path(path) -> bool:
    """Relative POSIX (core_common safe_member) that is also a portable Windows file name."""
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path or path.startswith("/"):
        return False
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts) or PurePosixPath(path).as_posix() != path:
        return False
    return not any(_WINDOWS_CHARS & set(part) or _WINDOWS_NAMES.fullmatch(part)
                   or part[-1] in ". " or any(ord(c) < 32 for c in part) for part in parts)


def _request(base: str, path: str, token: str):
    return urllib.request.Request(base.rstrip("/") + path, headers={"Authorization": f"Bearer {token}"})


def _error_code(exc: urllib.error.HTTPError) -> str:
    try:
        return str(json.loads(exc.read() or b"{}").get("error", {}).get("code") or "")
    except (ValueError, AttributeError, OSError):
        return ""


def _http_error(what: str, exc: urllib.error.HTTPError) -> FetchError:
    code = _error_code(exc)
    if exc.code in (401, 403):
        return TokenRefused(f"{what}: HTTP {exc.code} {code} — {_TOKEN_HELP}")
    if exc.code == 409:   # RECORDING_BUSY / ROBOT_MOVING: try again later
        return NotIdle(f"{what}: robot not idle ({code or 'HTTP 409'})")
    if 300 <= exc.code < 400:
        return FetchError(f"{what}: redirect refused (HTTP {exc.code})")
    return FetchError(f"{what}: HTTP {exc.code} {code}".rstrip())


def list_recordings(base: str, token: str, timeout: float, opener=None) -> dict:
    try:
        with (opener or _OPENER).open(_request(base, "/api/v1/recordings", token), timeout=timeout) as resp:
            listing = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise _http_error("listing", exc) from exc
    except (OSError, ValueError) as exc:
        raise FetchError(f"listing: {exc}") from exc
    if not isinstance(listing, dict) or not isinstance(listing.get("items"), list):
        raise FetchError("listing: not a recordings listing")
    return listing


def download(base: str, token: str, recording_id: str, part: Path, timeout: float,
             opener=None) -> None:
    path = f"/api/v1/recordings/{urllib.parse.quote(recording_id, safe='')}/archive"
    try:
        resp = (opener or _OPENER).open(_request(base, path, token), timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise _http_error(recording_id, exc) from exc
    except OSError as exc:
        raise FetchError(f"{recording_id}: {exc}") from exc
    with resp:
        length = resp.headers.get("Content-Length")
        if length is None or not length.isdigit():
            raise FetchError(f"{recording_id}: no Content-Length, cannot tell a whole download")
        expected, got = int(length), 0
        with part.open("wb") as handle:
            while True:
                try:
                    chunk = resp.read(CHUNK)
                except http.client.IncompleteRead as exc:
                    handle.write(exc.partial)
                    got += len(exc.partial)
                    break
                except OSError as exc:
                    raise FetchError(f"{recording_id}: download broke after {got} bytes: {exc}") from exc
                if not chunk:
                    break
                handle.write(chunk)
                got += len(chunk)
    if got != expected:
        raise FetchError(f"{recording_id}: short body {got}/{expected} bytes — CORE aborted the "
                         "download (robot moved or recording started); fetch again later")


def safe_extract(tar_path: Path, staging: Path, recording_id: str) -> Path:
    with tarfile.open(tar_path, "r:") as archive:
        members, seen = archive.getmembers(), set()
        for member in members:
            name = member.name
            parts = PurePosixPath(name).parts if isinstance(name, str) else ()
            if not member.isfile() or not _safe_path(name) or len(parts) < 2 \
                    or parts[0] != recording_id or name in seen:
                raise FetchError(f"{recording_id}: refused tar member {name!r}")
            seen.add(name)
        archive.extractall(staging, members=members, filter="data")
    return staging / recording_id


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(folder: Path, recording_id: str) -> dict:
    try:
        manifest = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FetchError(f"{recording_id}: no readable manifest ({exc})") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA \
            or manifest.get("id") != recording_id or not isinstance(manifest.get("files"), list):
        raise FetchError(f"{recording_id}: manifest schema or id mismatch")
    listed = set()
    for entry in manifest["files"]:
        path = entry.get("path") if isinstance(entry, dict) else None
        if not _safe_path(path) or path == MANIFEST_NAME or path in listed:
            raise FetchError(f"{recording_id}: unsafe manifest path {path!r}")
        listed.add(path)
        target, want = folder / path, str(entry.get("sha256") or "").lower()
        if not target.is_file() or target.stat().st_size != entry.get("bytes") or _sha256(target) != want:
            raise FetchError(f"{recording_id}: {path} does not match the manifest (size or sha256)")
    present = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    extra = present - listed - {MANIFEST_NAME}
    if extra:
        raise FetchError(f"{recording_id}: files not in the manifest: {sorted(extra)}")
    return manifest


def pair_counts(rows) -> dict:
    """Frames with cmd_vel and an intent; paired_accepted counts only intents CORE accepted."""
    out = {"frames": 0, "with_cmd_vel": 0, "with_intent": 0, "paired": 0, "paired_accepted": 0}
    for row in rows:
        side = row.get("side") or {}
        intent = side.get(INTENT_TOPIC)
        cmd, has_intent = side.get("cmd_vel") is not None, intent is not None
        out["frames"] += 1
        out["with_cmd_vel"] += cmd
        out["with_intent"] += has_intent
        out["paired"] += cmd and has_intent
        out["paired_accepted"] += cmd and isinstance(intent, dict) and intent.get("accepted") is True
    return out


def default_convert(folder: Path, out: Path, codec: str) -> tuple[int, Path | None]:
    import bag_to_video
    try:
        rc = bag_to_video.main([str(folder), "--out", str(out), "--codec", codec])
    except SystemExit as exc:   # bag_to_video stops on ffmpeg or session faults
        print(f"{folder.name}: bag_to_video: {exc}", file=sys.stderr)
        return 1, None
    meta_path = folder / "session.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    return rc, out / f"{bag_to_video.output_stem(folder, meta)}.jsonl"


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


def _read_rows(path: Path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _fetch_one(args, token: str, dest: Path, recording_id: str, convert) -> int:
    part, staging, final = dest / f".part-{recording_id}.tar", dest / f".staging-{recording_id}", \
        dest / recording_id
    _remove(part)         # an earlier run's leftovers: never extract into an old tree
    _remove(staging)
    try:
        download(args.base, token, recording_id, part, args.timeout, getattr(args, "opener", None))
        manifest = verify(safe_extract(part, staging, recording_id), recording_id)
        os.replace(staging / recording_id, final)     # the last step: final exists only verified
    except (NotIdle, TokenRefused):
        raise
    except (FetchError, OSError, tarfile.TarError) as exc:
        print(f"FAILED {exc}", file=sys.stderr)
        return 1
    finally:
        _remove(part)
        _remove(staging)
    if manifest.get("writer_killed") or manifest.get("bag_returncode") not in (0, None):
        print(f"{recording_id}: warning: rosbag2 ended badly (returncode "
              f"{manifest.get('bag_returncode')}, killed {manifest.get('writer_killed')}); "
              "the last split may be unindexed", file=sys.stderr)
    # The raw copy is verified and the robot may now reclaim its own, so a conversion or
    # pairing failure keeps it: rerun bag_to_video on <dest>/<id> by hand.
    rc, rows_path = convert(final, Path(args.video_out), args.codec)
    if rc != 0 or rows_path is None or not Path(rows_path).is_file():
        print(f"{recording_id}: FAILED conversion (rc {rc}); raw copy kept in {final}", file=sys.stderr)
        return 1
    counts = pair_counts(_read_rows(Path(rows_path)))
    print(f"{recording_id}: {counts['frames']} frames, {counts['paired']} paired cmd_vel+intent "
          f"({counts['paired_accepted']} accepted)")
    if counts["paired"] == 0:
        print(f"{recording_id}: FAILED no frame has both cmd_vel and {INTENT_TOPIC}; "
              f"raw copy kept in {final}", file=sys.stderr)
        return 1
    return 0


def main(argv=None, *, convert=default_convert) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", help="CORE base URL from the robot's _rosy._tcp advertisement")
    ap.add_argument("--token-file", help=f"Operator token file (env {TOKEN_ENV})")
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--video-out", help="bag_to_video --out (default data/teleop/learning)")
    ap.add_argument("--codec", choices=("hevc", "h264"), default="hevc")
    ap.add_argument("--only", metavar="ID")
    ap.add_argument("--ca-file", help="device CA for an https base (the URL name must match the certificate)")
    ap.add_argument("--timeout", type=float, default=600.0, help="per download socket timeout (s)")
    ap.add_argument("--list-timeout", type=float, default=LIST_TIMEOUT_S)
    args = ap.parse_args(argv)
    token_file = args.token_file or os.environ.get(TOKEN_ENV)
    token = Path(token_file).read_text(encoding="utf-8").strip() \
        if token_file and Path(token_file).is_file() else ""
    if not token:
        print(f"refused: needs an Operator token in --token-file or {TOKEN_ENV}", file=sys.stderr)
        return 2
    https = args.base.startswith("https://")
    if https and not args.ca_file:
        print("refused: https needs --ca-file (the robot device CA)", file=sys.stderr)
        return 2
    if args.ca_file and not https:
        print("refused: --ca-file applies only to an https base", file=sys.stderr)
        return 2
    if args.ca_file and not Path(args.ca_file).is_file():
        print(f"refused: cannot read device CA {args.ca_file}", file=sys.stderr)
        return 2
    args.opener = build_opener(args.ca_file)
    if args.video_out is None:
        import bag_to_video
        args.video_out = str(bag_to_video.DEFAULT_OUT)
    try:
        listing = list_recordings(args.base, token, args.list_timeout, args.opener)
    except TokenRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_TOKEN
    except FetchError as exc:
        print(f"FAILED {exc}", file=sys.stderr)
        return 1
    if not listing.get("download_allowed"):
        print(f"robot not idle: {listing.get('download_blocker') or 'download not allowed'}; "
              "nothing fetched", file=sys.stderr)
        return EXIT_NOT_IDLE
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    items = [item for item in listing["items"] if isinstance(item, dict) and item.get("status") == "complete"
             and (not args.only or item.get("id") == args.only)]
    if args.only and not items:
        print(f"no complete recording {args.only} on the robot", file=sys.stderr)
        return 1
    rc, failed = 0, 0
    for item in items:
        recording_id = item.get("id")
        if not _id_ok(recording_id):
            print(f"skipped: invalid recording id {recording_id!r}", file=sys.stderr)
            rc, failed = 1, failed + 1
            continue
        if (dest / recording_id).exists():
            print(f"{recording_id}: already in {dest}")
            continue
        try:
            one = _fetch_one(args, token, dest, recording_id, convert)
        except TokenRefused as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return EXIT_TOKEN
        except NotIdle as exc:
            earlier = f"; {failed} earlier recording(s) failed" if failed else ""
            print(f"stopped: {exc}{earlier}; nothing further fetched", file=sys.stderr)
            return EXIT_NOT_IDLE
        rc, failed = max(rc, one), failed + (one != 0)
    return rc


if __name__ == "__main__":
    sys.exit(main())
