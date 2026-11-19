"""Land a topic branch through a GitHub PR + Merge Queue (D-762 / D-1052).

Usage::

    python tools/pr_land.py [--title "..."] [--self-review "<reason>"] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    res = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise SystemExit(f"{' '.join(cmd[:3])} failed ({res.returncode}): {(res.stderr or res.stdout).strip()}")
    return res.stdout.strip()


def build_body(summary: str, self_review: str) -> str:
    lines = [summary.strip() or "PR landing via Merge Queue (D-1052)."]
    if self_review.strip():
        lines += ["", f"Overlap-Review: self ({self_review.strip()})"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, repo: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", default="", help="PR title (default: tip commit subject)")
    parser.add_argument("--body", default="", help="PR description summary")
    parser.add_argument("--self-review", default="", metavar="REASON",
                        help="include Overlap-Review: self (<REASON>) for self-reviewable overlap ack")
    parser.add_argument("--remote-prepush", action="store_true", help="keep remote pre-push tests enabled")
    parser.add_argument("--dry-run", action="store_true", help="print commands without pushing/merging")
    args = parser.parse_args(argv)
    cwd = (repo or Path.cwd()).resolve()

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if branch in ("main", "HEAD"):
        raise SystemExit(f"[pr-land] checkout a topic branch first (got {branch})")
    if _run(["git", "status", "--porcelain"], cwd):
        raise SystemExit("[pr-land] working tree is dirty; commit explicit files first")

    title = args.title or _run(["git", "log", "-1", "--format=%s", "HEAD"], cwd)
    body = build_body(args.body, args.self_review)
    if args.dry_run:
        print(f"[pr-land] dry-run branch={branch} title={title!r}")
        return 0

    env = dict(os.environ)
    if not args.remote_prepush:
        env["ROSY_STATIC_PRE_PUSH"] = "1"
    _run(["git", "push", "-u", "origin", branch], cwd, env=env)
    existing = json.loads(_run(["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number"], cwd) or "[]")
    if existing:
        pr = str(existing[0]["number"])
        if args.self_review:
            _run(["gh", "pr", "edit", pr, "--body", body], cwd)
    else:
        url = _run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", title, "--body", body], cwd)
        pr = url.rstrip("/").rsplit("/", 1)[-1]
    _run(["gh", "pr", "merge", pr, "--auto", "--merge"], cwd)
    print(f"[pr-land] queued PR #{pr} ({branch}) in Merge Queue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
