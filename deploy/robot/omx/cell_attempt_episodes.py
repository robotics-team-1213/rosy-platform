#!/usr/bin/env python3
"""Read-only join of attempts.jsonl rows with their recorded episodes (the sweep's ingest, the twin's batch).

An attempt row's "episode" {id, path, sha} names the folder episode_recorder wrote; the folder's task.json
names the attempt_id back (cell_auto_safety.episode_binding), which joins rows written before the field.
Nothing is written. A row with no episode, a missing folder or a changed digest is reported, never dropped.

  cell_attempt_episodes.py attempts.jsonl [--episodes ROOT] > joined.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PARTS = ("ticks.jsonl", "result.json")


def episode_ref(folder) -> dict:
    """{id, path, sha}: sha covers ticks.jsonl and result.json as they are now (None when neither exists)."""
    folder = Path(folder)
    digest, seen = hashlib.sha256(), False
    for name in PARTS:
        if (folder / name).is_file():
            digest.update(name.encode() + (folder / name).read_bytes())
            seen = True
    return {"id": folder.name, "path": str(folder), "sha": digest.hexdigest()[:12] if seen else None}


def load_rows(path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def join(rows: list[dict], episodes_root=None) -> dict:
    """{"joined": [{attempt, episode, status}], "counts": {status: n}}. status: ok, no_episode, missing_folder,
    sha_changed (the folder differs from what the row digested), unlinked (an episode no row claims, if a root)."""
    root = None if episodes_root is None else Path(episodes_root)
    by_attempt = {}
    if root is not None and root.is_dir():
        for task in root.glob("*/task.json"):
            try:
                by_attempt.setdefault(json.loads(task.read_text(encoding="utf-8")).get("attempt_id"), task.parent)
            except (OSError, ValueError):
                continue
    joined, claimed = [], set()
    for row in rows:
        ref = row.get("episode")
        folder = None
        if ref:
            folder = Path(ref["path"])
            if not folder.is_dir() and root is not None:
                folder = root / ref["id"]
        elif row.get("attempt_id") in by_attempt:
            folder = by_attempt[row["attempt_id"]]
        if folder is None:
            status, now = "no_episode", None
        elif not folder.is_dir():
            status, now = "missing_folder", None
        else:
            now = episode_ref(folder)
            claimed.add(folder.name)
            status = "sha_changed" if ref and ref.get("sha") and ref["sha"] != now["sha"] else "ok"
        joined.append({"attempt": row, "episode": now, "status": status})
    for name in sorted({f.name for f in by_attempt.values()} - claimed):
        joined.append({"attempt": None, "episode": episode_ref(root / name), "status": "unlinked"})
    counts: dict = {}
    for item in joined:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {"joined": joined, "counts": counts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("attempts", type=Path, nargs="+")
    parser.add_argument("--episodes", type=Path, help="episodes root, for rows without a usable path")
    args = parser.parse_args(argv)
    json.dump(join([r for p in args.attempts for r in load_rows(p)], args.episodes), sys.stdout, indent=1)


if __name__ == "__main__":
    main()
