"""Queue a landing and free the worktree at once (D-889): land a snapshot of HEAD from a hidden worktree.

land.py runs in the branch's own worktree until the landing ends, and a landing took 3 h 39 min at the median on
2026-10-27/28, so worktrees waiting to land filled the 15-slot cap and new work stopped. Here the committed HEAD
becomes branch ``land/<branch>-<UTC stamp>``, checked out under ``<git-common-dir>/rosy-land-wt/`` (outside
``.worktrees``, so not a slot), and a detached supervisor runs ``land.py`` there. The caller's worktree is free
the moment this returns: keep working on the branch (later commits go into the next landing) or remove it.

The supervisor logs to ``<git-common-dir>/rosy-land-wt/<name>.log``. When the snapshot is in main afterwards it
removes the hidden worktree and the snapshot branch; otherwise it keeps both and writes ``<name>.stopped``, so the
owner can read the STOP, fix it on the branch and queue again. Uncommitted changes are refused, never carried.

    python tools/land_async.py [land.py args]      # from the branch's worktree; prints the log path
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys

HOLDER = "rosy-land-wt"
PREFIX = "land/"
NO_WINDOW = 0x08000000  # subprocess.CREATE_NO_WINDOW, named here so the module imports off Windows too


def git(cwd: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode != 0:
        raise SystemExit(f"[land-async] git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def holder(cwd: Path) -> Path:
    return Path(git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")) / HOLDER


def snapshot_name(branch: str, now: datetime) -> str:
    return f"{PREFIX}{branch}-{now:%Y%m%d%H%M%S}"


def start(cwd: Path, land_args: list[str], now: datetime, launch) -> tuple[str, Path]:
    """Create the snapshot branch and hidden worktree, hand them to ``launch``; (snapshot, log path)."""
    branch = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if branch in ("HEAD", "main") or branch.startswith(PREFIX):
        raise SystemExit(f"[land-async] run it from a topic branch's worktree, not {branch!r}")
    if git(cwd, "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("[land-async] uncommitted changes: commit them first (a landing takes only commits)")
    snap = snapshot_name(branch, now)
    place = holder(cwd)
    place.mkdir(exist_ok=True)
    tree = place / snap.replace("/", "-")
    git(cwd, "branch", snap, "HEAD")
    git(cwd, "worktree", "add", "-q", str(tree), snap)
    log = tree.parent / (tree.name + ".log")
    # The supervisor runs a copy beside the log, never the caller's file: Windows keeps a running script's
    # folder from being deleted, and the caller's worktree must be free (2026-10-28).
    script = place / (tree.name + ".land_async.py")  # one per landing: a running copy cannot be rewritten
    script.write_bytes(Path(__file__).read_bytes())
    launch([sys.executable, "-X", "utf8", str(script), "--supervise", str(tree), snap, *land_args], log)
    return snap, log


def supervise(tree: Path, snap: str, land_args: list[str], run=subprocess.call) -> int:
    """Run land.py in ``tree``; clean up when the snapshot landed, keep it and mark it stopped otherwise."""
    # land.py's own lines (the STOP reason) into the .log, appended: the inherited handle lost them (2026-10-28)
    with open(tree.parent / (tree.name + ".log"), "a", encoding="utf-8") as log:
        # CREATE_NO_WINDOW: under the detached supervisor land.py got a new console, a tab of the default terminal;
        # closing that window killed every lander at once (exit 0xC000013A: 8 on 10-28, 12 on 10-30 18:58).
        code = run([sys.executable, "-X", "utf8", "tools/land.py", *land_args], cwd=str(tree), stdout=log,
                   stderr=subprocess.STDOUT, **({"creationflags": NO_WINDOW} if os.name == "nt" else {}))
    landed = subprocess.run(["git", "-C", str(tree), "merge-base", "--is-ancestor", snap, "main"]).returncode == 0
    if landed:
        main = git(tree, "rev-parse", "--path-format=absolute", "--git-common-dir")
        git(Path(main).parent, "worktree", "remove", "--force", str(tree), check=False)
        git(Path(main).parent, "branch", "-D", snap, check=False)
        print(f"[land-async] {snap} landed; hidden worktree and snapshot branch removed", flush=True)
    else:
        (tree.parent / (tree.name + ".stopped")).write_text(f"land.py exit {code}; read {tree.name}.log\n",
                                                            encoding="utf-8")
        print(f"[land-async] {snap} did not land (exit {code}); kept {tree} for the owner", flush=True)
    return code


def detach(argv: list[str], log: Path) -> subprocess.Popen:
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    # cwd: the holder, never the caller's worktree, which Windows then cannot delete while the landing runs
    with open(log, "w", encoding="utf-8") as out:
        return subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=log.parent,
                                creationflags=flags, start_new_session=os.name != "nt")


def main(argv: list[str]) -> int:
    if argv[:1] == ["--supervise"]:
        return supervise(Path(argv[1]), argv[2], argv[3:])
    snap, log = start(Path.cwd(), argv, datetime.now(timezone.utc), detach)
    print(f"[land-async] queued {snap}; this worktree is free now. Log: {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
