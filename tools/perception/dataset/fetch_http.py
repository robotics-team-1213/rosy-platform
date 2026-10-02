"""D-411 A: pull finished Pilot recordings over CORE HTTP (no SSH), verify every byte against
the robot's sha256 manifest, convert with bag_to_video and check frame/action pairing.

Usage: fetch_http.py http://<robot>:8080 [--token-file FILE] [--dest data/perception/raw]
                     [--video-out data/teleop/learning] [--codec hevc|h264] [--only ID]

Only while CORE says the robot is stopped (D-136 §6, API Ref §5.10): the listing names the
blocker and the tool exits 4. The token is an Operator token read from a file (or the file
named by ROSY_CORE_TOKEN_FILE), never argv.

Per recording: <dest>/.part-<id>.tar -> safe extract into <dest>/.staging-<id>/ -> sha256 and
size check against manifest.json -> <dest>/<id>/ -> bag_to_video -> pair check (frames with
both cmd_vel and teleop/intent). A body shorter than Content-Length means CORE aborted the
download (the robot moved or a recording started): the partial is deleted and the recording
is fetched again from zero on a later run. A recording already in <dest>/<id> is skipped.

Exit codes: 0 all fetched, 1 some recording failed, 2 bad arguments, 4 robot not idle.
"""
import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harvest import TOKEN_ENV  # noqa: E402

EXIT_NOT_IDLE = 4
# core_common.protocol.recording (not imported: this tool runs without the robot tree).
MANIFEST_SCHEMA = "rosy.pilot.recording.manifest/1"
MANIFEST_NAME = "manifest.json"
INTENT_TOPIC = "teleop/intent"
RECORDING_ID = re.compile(r"\d{8}T\d{6}Z_[A-Za-z0-9_.-]{1,64}")
CHUNK = 1 << 20
DEFAULT_DEST = "data/perception/raw"


class FetchError(Exception):
    pass


class NotIdle(FetchError):
    """CORE refused or cut the transfer because the robot is not idle (or busy)."""


def _id_ok(value) -> bool:
    return isinstance(value, str) and RECORDING_ID.fullmatch(value) is not None \
        and not value.endswith("_")


def _safe_path(path) -> bool:
    """Relative POSIX, no '.', '..', empty part or backslash (core_common safe_member)."""
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path or path.startswith("/"):
        return False
    return all(part not in ("", ".", "..") for part in path.split("/")) \
        and PurePosixPath(path).as_posix() == path


def _request(base: str, path: str, token: str):
    return urllib.request.Request(base.rstrip("/") + path, headers={"Authorization": f"Bearer {token}"})


def _error_code(exc: urllib.error.HTTPError) -> str:
    try:
        return str(json.loads(exc.read() or b"{}").get("error", {}).get("code") or "")
    except (ValueError, AttributeError, OSError):
        return ""


def list_recordings(base: str, token: str, timeout: float) -> dict:
    try:
        with urllib.request.urlopen(_request(base, "/api/v1/recordings", token), timeout=timeout) as resp:
            listing = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise FetchError(f"listing: HTTP {exc.code} {_error_code(exc)}".rstrip()) from exc
    except (OSError, ValueError) as exc:
        raise FetchError(f"listing: {exc}") from exc
    if not isinstance(listing, dict) or not isinstance(listing.get("items"), list):
        raise FetchError("listing: not a recordings listing")
    return listing


def download(base: str, token: str, recording_id: str, part: Path, timeout: float) -> None:
    path = f"/api/v1/recordings/{urllib.parse.quote(recording_id, safe='')}/archive"
    try:
        resp = urllib.request.urlopen(_request(base, path, token), timeout=timeout)
    except urllib.error.HTTPError as exc:
        code = _error_code(exc)
        if exc.code == 409:   # RECORDING_BUSY / ROBOT_MOVING: try again later
            raise NotIdle(f"{recording_id}: robot not idle ({code or 'HTTP 409'})") from exc
        raise FetchError(f"{recording_id}: HTTP {exc.code} {code}".rstrip()) from exc
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
        target = folder / path
        if not target.is_file() or target.stat().st_size != entry.get("bytes") \
                or _sha256(target) != entry.get("sha256"):
            raise FetchError(f"{recording_id}: {path} does not match the manifest (size or sha256)")
    present = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    extra = present - listed - {MANIFEST_NAME}
    if extra:
        raise FetchError(f"{recording_id}: files not in the manifest: {sorted(extra)}")
    return manifest


def pair_counts(rows) -> dict:
    out = {"frames": 0, "with_cmd_vel": 0, "with_intent": 0, "paired": 0}
    for row in rows:
        side = row.get("side") or {}
        cmd, intent = side.get("cmd_vel") is not None, side.get(INTENT_TOPIC) is not None
        out["frames"] += 1
        out["with_cmd_vel"] += cmd
        out["with_intent"] += intent
        out["paired"] += cmd and intent
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
    try:
        download(args.base, token, recording_id, part, args.timeout)
        manifest = verify(safe_extract(part, staging, recording_id), recording_id)
        os.replace(staging / recording_id, final)
    except NotIdle:
        _remove(final)
        raise
    except (FetchError, OSError, tarfile.TarError) as exc:
        _remove(final)
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
    print(f"{recording_id}: {counts['frames']} frames, {counts['paired']} paired cmd_vel+intent")
    if counts["paired"] == 0:
        print(f"{recording_id}: FAILED no frame has both cmd_vel and {INTENT_TOPIC}; "
              f"raw copy kept in {final}", file=sys.stderr)
        return 1
    return 0


def main(argv=None, *, convert=default_convert) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", help="CORE base URL, e.g. http://rosy-01.local:8080")
    ap.add_argument("--token-file", help=f"Operator token file (env {TOKEN_ENV})")
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--video-out", help="bag_to_video --out (default data/teleop/learning)")
    ap.add_argument("--codec", choices=("hevc", "h264"), default="hevc")
    ap.add_argument("--only", metavar="ID")
    ap.add_argument("--timeout", type=float, default=600.0)
    args = ap.parse_args(argv)
    token_file = args.token_file or os.environ.get(TOKEN_ENV)
    token = Path(token_file).read_text(encoding="utf-8").strip() \
        if token_file and Path(token_file).is_file() else ""
    if not token:
        print(f"refused: needs an Operator token in --token-file or {TOKEN_ENV}", file=sys.stderr)
        return 2
    if args.video_out is None:
        import bag_to_video
        args.video_out = str(bag_to_video.DEFAULT_OUT)
    try:
        listing = list_recordings(args.base, token, args.timeout)
    except FetchError as exc:
        print(f"FAILED {exc}", file=sys.stderr)
        return 1
    if not listing.get("download_allowed"):
        print(f"robot not idle: {listing.get('download_blocker') or 'download not allowed'}; "
              "nothing fetched", file=sys.stderr)
        return EXIT_NOT_IDLE
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    rc = 0
    for item in listing["items"]:
        if not isinstance(item, dict) or item.get("status") != "complete":
            continue
        recording_id = item.get("id")
        if args.only and recording_id != args.only:
            continue
        if not _id_ok(recording_id):
            print(f"skipped: invalid recording id {recording_id!r}", file=sys.stderr)
            rc = 1
            continue
        if (dest / recording_id).exists():
            print(f"{recording_id}: already in {dest}")
            continue
        try:
            rc = max(rc, _fetch_one(args, token, dest, recording_id, convert))
        except NotIdle as exc:
            print(f"stopped: {exc}; nothing further fetched", file=sys.stderr)
            return EXIT_NOT_IDLE
    return rc


if __name__ == "__main__":
    sys.exit(main())
