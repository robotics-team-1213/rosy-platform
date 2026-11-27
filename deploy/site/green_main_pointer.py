#!/usr/bin/env python3
"""Sign the "green main" pointer the OMX cell updaters read instead of the GitHub REST API (D-805 7).

Runs on the D-441 signing PC next to auto_sign_candidates.py, with its authenticated `gh` (5000/h) and a
pointer key of its own (never the site candidate key). One run:

1. walks main's first-parent line from the tip (`gh api repos/<repo>/commits?sha=main`, at most --depth);
2. takes the first commit whose every --check has a newest GitHub Actions check run that completed with
   success (the condition omx_autoupdate.trusted() applied to the check-runs API; other apps are ignored);
3. writes `<out-dir>/green-main.json` (+ `.sig`, candidate_signing envelope) and copies both to every
   --push target with scp. The bytes are deterministic, so an unchanged main rewrites the same files.

    python green_main_pointer.py --repo <owner>/rosy-platform --key-id rosy-green-main-v1 \
        --private-key <outside-repo>.pem --public-key <outside-repo>.pub.pem --out-dir <dir> [--push user@host:dir]
    python green_main_pointer.py --repo <owner>/rosy-platform --dry-run   # print the pointer, sign nothing

Exit codes: 0 written (or dry run), 3 no green commit within --depth, 2 gh or signing failed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from candidate_signing import sign_manifest_bytes  # noqa: E402

SCHEMA = "rosy-green-main/1"
NAME = "green-main.json"


def gh_json(gh: str, path: str, runner=subprocess.run):
    done = runner([gh, "api", path], capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
    return json.loads(done.stdout)


def green(runs: list, name: str) -> bool:
    ours = [r for r in runs if r.get("name") == name and (r.get("app") or {}).get("slug") == "github-actions"]
    newest = max(ours, key=lambda r: r.get("id", 0), default=None)  # a rerun replaces an older result
    return bool(newest) and newest.get("status") == "completed" and newest.get("conclusion") == "success"


def newest_green(repo: str, branch: str, checks: list[str], depth: int, fetch) -> dict | None:
    """The pointer for the newest first-parent commit of branch whose required checks are green."""
    listed = fetch(f"repos/{repo}/commits?sha={branch}&per_page=100")
    by_sha = {c["sha"]: c for c in listed}
    commit = listed[0] if listed else None
    for _ in range(depth):
        if commit is None:
            return None
        runs = fetch(f"repos/{repo}/commits/{commit['sha']}/check-runs?per_page=100")["check_runs"]
        if all(green(runs, name) for name in checks):
            return {"schema": SCHEMA, "repository": repo, "branch": branch, "source_commit": commit["sha"],
                    "required_checks": sorted(checks),
                    "commit_verified": bool(commit["commit"]["verification"]["verified"])}
        parents = commit.get("parents") or []
        commit = by_sha.get(parents[0]["sha"]) if parents else None
    return None


def encode(pointer: dict) -> bytes:
    return (json.dumps(pointer, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--branch", default="main")
    ap.add_argument("--check", action="append", dest="checks", help="required check name (default ci-result)")
    ap.add_argument("--depth", type=int, default=20, help="first-parent commits to look back")
    ap.add_argument("--gh", default="gh")
    ap.add_argument("--key-id")
    ap.add_argument("--private-key", type=Path)
    ap.add_argument("--public-key", type=Path)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--push", action="append", default=[], help="scp target user@host:dir (repeatable)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not a.dry_run and not (a.key_id and a.private_key and a.public_key and a.out_dir):
        ap.error("--key-id, --private-key, --public-key and --out-dir are required unless --dry-run")
    try:
        pointer = newest_green(a.repo, a.branch, a.checks or ["ci-result"], a.depth, lambda p: gh_json(a.gh, p))
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"step": "gh_failed", "error": type(exc).__name__}), flush=True)
        return 2
    if pointer is None:
        print(json.dumps({"step": "no_green_commit", "depth": a.depth}), flush=True)
        return 3
    data = encode(pointer)
    if a.dry_run:
        sys.stdout.write(data.decode("ascii"))
        return 0
    try:
        sig = sign_manifest_bytes(data, key_id=a.key_id, private_key=a.private_key, public_key=a.public_key)
    except ValueError as exc:  # CandidateSignatureError
        print(json.dumps({"step": "sign_failed", "error": str(exc)}), flush=True)
        return 2
    a.out_dir.mkdir(parents=True, exist_ok=True)
    write_atomic(a.out_dir / (NAME + ".sig"), sig)
    write_atomic(a.out_dir / NAME, data)
    failed = [t for t in a.push if subprocess.run(
        ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
         str(a.out_dir / NAME), str(a.out_dir / (NAME + ".sig")), t], timeout=120).returncode != 0]
    print(json.dumps({"step": "written", "source_commit": pointer["source_commit"], "push_failed": failed}), flush=True)
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
