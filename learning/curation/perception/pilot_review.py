"""Recover local Pilot originals and prepare immutable inputs for Learning review.

pilot_review.py --raw-root DIR --video-dir DIR --out DIR --classes classes.yaml
                [--state EXISTING_REVIEW_STATE] [--only RECORDING_ID] [--since-id ID]

No robot access, inferred human driver, labels, training request or model activation.
Without --state, register the printed prepared folder in Learning's existing catalog.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

import fetch_http


def _files(folder):
    paths = list(folder.rglob("*"))
    if folder.is_symlink() or any(p.is_symlink() for p in paths):
        raise ValueError("prepared inputs must not contain links")
    return {p.relative_to(folder).as_posix(): fetch_http._sha256(p)
            for p in paths if p.is_file() and p != folder / "pilot-inputs.json"}


def prepare(session: Path, video_dir: Path, out: Path, classes: Path) -> Path:
    """Reuse the existing PNG/video snapshot preparer; never overwrite an output."""
    import bag_to_video
    import build
    import extract
    import pixel_label_job

    session, video_dir, out, classes = map(Path, (session, video_dir, out, classes))
    if not fetch_http._id_ok(session.name):
        raise ValueError("safe Pilot recording ID required")
    fetch_http.verify(session, session.name)
    if not fetch_http._paired_receipt_valid(session.parent, session.name):
        raise ValueError("verified paired video receipt required")
    meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    video = video_dir / (bag_to_video.output_stem(session, meta) + ".mp4")
    receipt = json.loads(fetch_http._receipt_path(session.parent, session.name).read_text(encoding="utf-8"))
    if Path(receipt["sidecar"]).resolve() != video.with_suffix(".jsonl").resolve():
        raise ValueError("paired video does not belong to the selected recording")
    # Legacy receipts pinned only the sidecar; snapshot the video's current digest without granting source proof.
    receipt.setdefault("video_sha256", fetch_http._sha256(video))
    side, video_meta = extract._sidecar(video)
    if not video_meta or (video_meta.get("source") or {}).get("session") != session.name:
        raise ValueError("converted video source session differs")
    extract._check_sidecar(video, side, video_meta)
    build.load_classes(classes)
    frames, last = [], -math.inf
    for index, row in enumerate(side):
        stamp, evidence = row.get("t"), row.get("side") or {}
        intent = evidence.get(fetch_http.INTENT_TOPIC)
        if (isinstance(stamp, (int, float)) and math.isfinite(stamp) and stamp >= last + 0.5
                and evidence.get("cmd_vel") is not None and isinstance(intent, dict)
                and intent.get("accepted") is True):
            frames.append(index)
            last = stamp
    if not 1 <= len(frames) <= 2000:
        raise ValueError("1..2000 sampled frames with accepted controls required")
    expected = {"schema": "rosy.pilot.review-inputs/1", "recording_id": session.name,
                "manifest_sha256": fetch_http._sha256(session / "manifest.json"),
                "sidecar_sha256": receipt["sidecar_sha256"], "video_sha256": receipt["video_sha256"],
                "classes_sha256": fetch_http._sha256(classes), "frames": frames}
    final = out / session.name
    if final.exists():
        old = json.loads((final / "pilot-inputs.json").read_text(encoding="utf-8"))
        if old != {**expected, "files": _files(final)}:
            raise ValueError("prepared inputs changed; preserve them and choose a new output root")
        return final / "verified-inputs.jsonl"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{session.name}-", dir=out) as temporary:
        stage = Path(temporary) / "inputs"
        pixel_label_job.prepare_sources({"sources": [{"video": str(video.resolve()),
            "sha256": receipt["video_sha256"], "frames": frames,
            "capture_group": "pilot-" + session.name, "source_session": session.name}]}, stage)
        shutil.copyfile(classes, stage / "classes.yaml")
        catalog = stage / "verified-inputs.jsonl"
        rows = [json.loads(line) for line in catalog.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            row.update(video_time_s=side[row["video_frame"]]["t"] - side[0]["t"],
                       timestamp_basis="camera_header_stamp", collection="pilot")
        catalog.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
        if (fetch_http._sha256(video.with_suffix(".jsonl")) != expected["sidecar_sha256"]
                or fetch_http._sha256(classes) != expected["classes_sha256"]):
            raise ValueError("source inputs changed during preparation")
        (stage / "pilot-inputs.json").write_text(json.dumps({**expected, "files": _files(stage)},
                                                          sort_keys=True), encoding="utf-8")
        os.rename(stage, final)
    return final / "verified-inputs.jsonl"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--video-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--classes", type=Path, required=True)
    parser.add_argument("--state", type=Path, help="existing Learning workspace; import as pending only")
    parser.add_argument("--only")
    parser.add_argument("--since-id")
    args = parser.parse_args(argv)
    if any(value and not fetch_http._id_ok(value) for value in (args.only, args.since_id)):
        print("refused: --only and --since-id must be recording IDs", file=sys.stderr)
        return 2
    if (not args.raw_root.is_dir() or not args.classes.is_file()
            or (args.state and not (args.state / "reviews.sqlite3").is_file())):
        print("refused: existing raw root, classes and selected review workspace required", file=sys.stderr)
        return 2
    selection = [part for flag, value in (("--only", args.only), ("--since-id", args.since_id))
                 if value for part in (flag, value)]
    rc = fetch_http.main(["--local-only", "--dest", str(args.raw_root),
                          "--video-out", str(args.video_dir), "--codec", "h264", *selection])
    store = None
    if args.state:
        import review_ingest
        from review_store import ReviewStore
        store = ReviewStore(args.state)
    for session in sorted(args.raw_root.iterdir()):
        if (not session.is_dir() or not fetch_http._id_ok(session.name)
                or (args.only and session.name != args.only)
                or (args.since_id and session.name < args.since_id)):
            continue
        try:
            catalog = prepare(session, args.video_dir, args.out, args.classes)
            result = {"recording_id": session.name, "prepared": str(catalog)}
            if store:
                imported = review_ingest.import_frames(store, {"path": str(catalog.resolve()),
                                                               "catalog_relative": True})
                result.update(added=imported["added"], status="pending human review")
            print(json.dumps(result))
        except (OSError, ValueError, fetch_http.FetchError, SystemExit) as exc:
            print(f"{session.name}: FAILED preparation: {exc}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
