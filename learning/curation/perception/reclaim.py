"""Report raw sessions that a checked learning video can replace, and delete only those.

Usage: reclaim.py [--root data/perception] [--video-dir data/teleop/learning]
                  [--make-video] [--shrink] [--apply]

Scans <root>/raw in both layouts (raw/<stamp>_<device>/ and
raw/<device>/<stamp>_<device>/). A session is reclaimable when
teleop_<device>_<stamp>.mp4, .jsonl and .json agree: schema
rosy.teleop.video/1, the meta frame count, the sidecar line count, the mp4
byte size, and ffprobe's packet count. Both raw copies of that session are
candidates. Folders ending in .compact or .compact.partial are never
candidates.

--make-video runs bag_to_video once per stem that has no video yet.
--shrink compacts sessions that still have no video; a compact that verifies
becomes a candidate and the .compact folder stays.
--apply deletes the candidate raw directories after every path is checked.
A verified video also removes that session's .compact sibling, including a
compact left behind after the raw directory is already gone. A compact with
no checked video stays. Without --apply nothing is deleted.
Unmatched videos stay. The robot copy and recording_job are untouched.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import bag_to_video

REPO = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = REPO / "data/perception"
DEFAULT_VIDEO = REPO / "data/teleop/learning"
DERIVATIVE_SUFFIXES = (".compact", ".compact.partial")
RECLAIM_STATUS = frozenset({"ok", "compact_ok"})


def is_derivative(path: Path) -> bool:
    return path.name.endswith(DERIVATIVE_SUFFIXES)


def _is_session(path: Path) -> bool:
    if (path / "session.json").is_file():
        return True
    bag = path / "bag"
    return bag.is_dir() and any(bag.glob("*.mcap"))


def iter_sessions(raw: Path) -> list[Path]:
    """Session folders in the flat layout and the per-device layout. Derivatives skipped."""
    found = []
    if not raw.is_dir():
        return found
    for child in sorted(p for p in raw.iterdir() if p.is_dir()):
        if is_derivative(child):
            continue
        if _is_session(child):
            found.append(child)
            continue
        for grand in sorted(p for p in child.iterdir() if p.is_dir() and not is_derivative(p)):
            if _is_session(grand):
                found.append(grand)
    return found


def tree_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def session_stem(session: Path) -> str:
    meta_path = session / "session.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    return bag_to_video.output_stem(session, meta)


def _sidecar_lines(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def verify_video(video_dir: Path, stem: str, probe) -> dict:
    """ok only when meta, sidecar and probed mp4 all name the same frame count."""
    video = video_dir / f"{stem}.mp4"
    rows = video_dir / f"{stem}.jsonl"
    meta_path = video_dir / f"{stem}.json"
    blank = {"frames": None, "detail": "video sidecar or meta absent"}
    if not video.is_file() or not rows.is_file() or not meta_path.is_file():
        return {"status": "missing", **blank}
    try:
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
        declared = int(doc["video"]["frames"])
        named = doc["video"]["file"]
        size = int(doc["video"]["bytes"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return {"status": "mismatch", "frames": None, "detail": f"meta: {exc}"}
    if doc.get("schema") != bag_to_video.SCHEMA or named != video.name or size != video.stat().st_size:
        return {"status": "mismatch", "frames": declared, "detail": "meta does not describe this mp4"}
    sidecar = _sidecar_lines(rows)
    if sidecar != declared:
        return {"status": "mismatch", "frames": declared,
                "detail": f"sidecar {sidecar} != meta {declared}"}
    try:
        probed = int(probe(video))
    except Exception as exc:
        return {"status": "probe_error", "frames": declared, "detail": str(exc)}
    if probed != declared:
        return {"status": "mismatch", "frames": declared, "detail": f"probe {probed} != meta {declared}"}
    return {"status": "ok", "frames": declared, "detail": ""}


def plan(sessions: list[Path], video_dir: Path, probe) -> list[dict]:
    rows = []
    grouped: dict[str, list[Path]] = {}
    for session in sessions:
        try:
            stem = session_stem(session)
        except (OSError, json.JSONDecodeError) as exc:
            rows.append({"status": "mismatch", "stem": "", "path": str(session),
                         "bytes": tree_bytes(session), "frames": None, "detail": f"session: {exc}"})
            continue
        grouped.setdefault(stem, []).append(session)
    checks = {stem: verify_video(video_dir, stem, probe) for stem in grouped}
    for stem, copies in grouped.items():
        check = checks[stem]
        for session in copies:
            rows.append({"status": check["status"], "stem": stem, "path": str(session),
                         "bytes": tree_bytes(session), "frames": check["frames"],
                         "detail": check["detail"]})
    return rows


def unmatched_videos(video_dir: Path, stems: set[str]) -> int:
    if not video_dir.is_dir():
        return 0
    return sum(1 for path in video_dir.glob("*.mp4") if path.stem not in stems)


def guard(path: Path, raw: Path) -> Path:
    """A raw session directory under raw/, never the raw root and never a compact sibling."""
    raw_resolved = raw.resolve()
    path_resolved = path.resolve()
    if path_resolved == raw_resolved or raw_resolved not in path_resolved.parents:
        raise ValueError(f"not under raw: {path}")
    if is_derivative(path_resolved):
        raise ValueError(f"derivative: {path}")
    if not _is_session(path_resolved):
        raise ValueError(f"not a session: {path}")
    return path_resolved


def compact_sibling(session: Path) -> Path:
    return session.with_name(session.name + ".compact")


def iter_compacts(raw: Path) -> list[Path]:
    """Finished .compact directories in either layout. Partials are left alone."""
    found = []
    if not raw.is_dir():
        return found

    def take(path: Path) -> None:
        if (path.is_dir() and path.name.endswith(".compact")
                and not path.name.endswith(".compact.partial")):
            found.append(path)

    for child in sorted(p for p in raw.iterdir() if p.is_dir()):
        take(child)
        if _is_session(child) or is_derivative(child):
            continue
        for grand in sorted(p for p in child.iterdir() if p.is_dir()):
            take(grand)
    return found


def compacts_with_video(raw: Path, video_dir: Path, probe) -> list[Path]:
    """Compact bags whose learning video already checks out. These can go."""
    ready = []
    for path in iter_compacts(raw):
        try:
            stem = session_stem(path)
        except (OSError, json.JSONDecodeError):
            continue
        if verify_video(video_dir, stem, probe)["status"] == "ok":
            ready.append(path)
    return ready


def guard_compact(path: Path, raw: Path) -> Path:
    """A .compact directory under raw/. Partials and ordinary sessions are refused."""
    raw_resolved = raw.resolve()
    path_resolved = path.resolve()
    if path_resolved == raw_resolved or raw_resolved not in path_resolved.parents:
        raise ValueError(f"not under raw: {path}")
    if path_resolved.name.endswith(".compact.partial") or not path_resolved.name.endswith(".compact"):
        raise ValueError(f"not a compact sibling: {path}")
    if not path_resolved.is_dir():
        raise ValueError(f"not a compact directory: {path}")
    return path_resolved


def delete_targets(rows: list[dict], raw: Path, compacts: list[Path] | None = None) -> list[Path]:
    """Delete reclaimable raw sessions. A verified video also drops its .compact sibling."""
    chosen = [Path(row["path"]) for row in rows if row["status"] in RECLAIM_STATUS]
    compacts = list(compacts or [])
    compacts += [compact_sibling(Path(row["path"])) for row in rows
                 if row["status"] == "ok" and compact_sibling(Path(row["path"])).is_dir()]
    checked = []
    seen = set()
    for path in (guard(path, raw) for path in chosen):
        if path not in seen:
            seen.add(path)
            checked.append(path)
    for path in (guard_compact(path, raw) for path in compacts):
        if path not in seen:
            seen.add(path)
            checked.append(path)
    for path in checked:
        shutil.rmtree(path)
    return checked


def encode_missing(rows: list[dict], video_dir: Path, encode) -> bool:
    """Encode one session per stem. Returns True when any encode fails."""
    failed = False
    seen = set()
    for row in rows:
        if row["status"] != "missing" or row["stem"] in seen or not row["stem"]:
            continue
        seen.add(row["stem"])
        if encode(Path(row["path"]), video_dir) != 0:
            failed = True
    return failed


def shrink_missing(rows: list[dict], compact) -> bool:
    """Compact sessions that still have no video. A verified compact becomes reclaimable."""
    failed = False
    for row in rows:
        if row["status"] != "missing":
            continue
        try:
            ok, dest = compact(Path(row["path"]))
        except (Exception, SystemExit) as exc:
            row["detail"] = f"shrink: {exc}"
            failed = True
            continue
        if ok:
            row["status"] = "compact_ok"
            row["detail"] = str(dest)
        else:
            row["detail"] = "compact verify failed"
            failed = True
    return failed


def format_report(rows: list[dict], unmatched: int, applied: bool) -> str:
    lines = [f"{row['status']}\t{row['bytes']}\t{row['stem']}\t{row['path']}" for row in rows]
    reclaim = [row for row in rows if row["status"] in RECLAIM_STATUS]
    lines.append(f"reclaim {len(reclaim)} sessions {sum(row['bytes'] for row in reclaim)} bytes")
    lines.append(f"unmatched videos {unmatched}")
    lines.append("apply" if applied else "dry-run")
    return "\n".join(lines) + "\n"


def _encode(session: Path, video_dir: Path) -> int:
    try:
        code = bag_to_video.main([str(session), "--out", str(video_dir)])
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    return code


def _compact(session: Path):
    import shrink_session
    dest = session.with_name(session.name + ".compact")
    if not dest.exists():
        shrink_session.shrink_session(session)
    report = shrink_session.verify_session(session, dest)
    return bool(report["counts_equal"] and report["timestamps_equal"]), dest


def main(argv=None, probe=None, encode=None, compact=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--video-dir", default=str(DEFAULT_VIDEO))
    ap.add_argument("--make-video", action="store_true",
                    help="run bag_to_video for stems that have no video yet")
    ap.add_argument("--shrink", action="store_true",
                    help="compact sessions that still have no video; verified compacts are candidates")
    ap.add_argument("--apply", action="store_true",
                    help="delete candidate raw session directories")
    args = ap.parse_args(argv)
    root = Path(args.root)
    raw = root / "raw"
    video_dir = Path(args.video_dir)
    probe = bag_to_video.count_frames if probe is None else probe
    encode = _encode if encode is None else encode
    compact = _compact if compact is None else compact

    failed = False
    rows = plan(iter_sessions(raw), video_dir, probe)
    if args.make_video and encode_missing(rows, video_dir, encode):
        failed = True
        rows = plan(iter_sessions(raw), video_dir, probe)
    elif args.make_video:
        rows = plan(iter_sessions(raw), video_dir, probe)
    if args.shrink and shrink_missing(rows, compact):
        failed = True
    stems = {row["stem"] for row in rows if row["stem"]}
    print(format_report(rows, unmatched_videos(video_dir, stems), args.apply), end="")
    if not args.apply:
        return 1 if failed else 0
    try:
        removed = delete_targets(rows, raw)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    for path in removed:
        print(f"removed {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
