"""Read-only cutover watch (verdict 2026-11-20, item 2).

Reads `<git-common-dir>/rosy-cutover.json` (land_freeze.py schema: {"phase": str, "allow": [{"branch", "sha"}], "owner": str}; bare sha strings also accepted), fetches, checks that
every allowed sha is an ancestor of origin/main, and lists live landing trees (`rosy-land-wt/<name>` without
`<name>.stopped`) whose HEAD is not in allow. Writes a status json and appends ONE board line only when the state
content hash changes. It never lands, publishes, kills or edits git state (only `git fetch`).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path

STATUS = Path("D:/DevTemp/ghmig/cutover-status.json")
BOARD = Path("D:/DevTemp/landing-blockers-1120/board.md")


def git(cwd, *args, check=True):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r


def common_dir(cwd) -> Path:
    return Path(git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())


def listed(sha: str, allow) -> bool:
    return any(a and sha.startswith(a) or a.startswith(sha) for a in allow if sha)


def live_trees(holder: Path) -> list[Path]:
    if not holder.is_dir():
        return []
    return sorted(t for t in holder.iterdir() if t.is_dir() and not (holder / (t.name + ".stopped")).exists())


def collect(cwd, fetch=True) -> dict:
    common = common_dir(cwd)
    cfg_path = common / "rosy-cutover.json"
    if not cfg_path.is_file():
        return {"phase": "none", "owner": "", "allow": [], "not_in_main": [], "outside_allow": [], "error": ""}
    try:
        cfg = json.loads(cfg_path.read_text("utf-8"))
        phase, owner, allow = str(cfg["phase"]), str(cfg.get("owner", "")), [str(s["sha"]) if isinstance(s, dict) else str(s) for s in cfg["allow"]]
    except (ValueError, KeyError, TypeError) as e:
        return {"phase": "invalid", "owner": "", "allow": [], "not_in_main": [], "outside_allow": [], "error": f"bad rosy-cutover.json: {e}"}
    error = ""
    if fetch:
        f = git(cwd, "fetch", "origin", check=False)
        if f.returncode:
            error = "fetch failed: " + f.stderr.strip()[:200]
    not_in_main = [s for s in allow if git(cwd, "merge-base", "--is-ancestor", s, "origin/main", check=False).returncode]
    outside = []
    for t in live_trees(common / "rosy-land-wt"):
        head = git(t, "rev-parse", "HEAD", check=False).stdout.strip()
        if not listed(head, allow):
            outside.append(t.name)
    return {"phase": phase, "owner": owner, "allow": allow, "not_in_main": not_in_main, "outside_allow": outside, "error": error}


def digest(state: dict) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()[:12]


def record(state: dict, status: Path, board: Path, now=None) -> bool:
    """Write status; append one board line iff the content hash changed. Returns True when a line was appended."""
    h = digest(state)
    try:
        old = json.loads(status.read_text("utf-8")).get("hash")
    except (OSError, ValueError):
        old = None
    now = now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(json.dumps({**state, "hash": h, "checked": now}, indent=2, ensure_ascii=False), "utf-8")
    if h == old:
        return False
    board.parent.mkdir(parents=True, exist_ok=True)
    line = (f"- {now} cutover-watch [{h}] phase={state['phase']} owner={state['owner']} "
            f"not_in_main={','.join(s[:10] for s in state['not_in_main']) or '-'} "
            f"live_outside_allow={','.join(state['outside_allow']) or '-'}"
            + (f" error={state['error']}" if state["error"] else "") + "\n")
    with board.open("a", encoding="utf-8") as f:
        f.write(line)
    return True


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", default=".")
    p.add_argument("--status", type=Path, default=STATUS)
    p.add_argument("--board", type=Path, default=BOARD)
    a = p.parse_args(argv)
    state = collect(a.repo)
    changed = record(state, a.status, a.board)
    print(json.dumps({**state, "board_line_added": changed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
