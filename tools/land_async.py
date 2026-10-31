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
    python tools/land_async.py resume <tree-name> [land.py args]   # relaunch a stopped landing on its snapshot

A branch already held by a live ticket is refused; ``--replace`` stops that older lander first (2026-10-31/11-01: the
same change was queued twice and ran two pretests).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

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


def _queue():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import land_queue
    return land_queue


def live_tickets(cwd: Path) -> list[dict]:
    """Queue tickets whose land.py is alive (read only: land_queue.ahead would delete stale ones)."""
    land_queue, rows = _queue(), []
    for path in sorted(land_queue.queue_dir(cwd).glob("[0-9]*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if land_queue.pid_alive(int(row.get("pid") or 0)):
            rows.append({**row, "ticket": path.name})
    return rows


def holders(cwd: Path, branch: str) -> list[dict]:
    """Live tickets landing ``branch``: its own ticket, a snapshot of it, or a batch carrying a snapshot of it."""
    snap = re.compile(rf"^{re.escape(PREFIX + branch)}-\d{{14}}")
    return [r for r in live_tickets(cwd) if r.get("branch") == branch or snap.match(r.get("branch") or "")
            or any(snap.match(b) for b in r.get("batch") or [])]


def stop(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        os.kill(pid, 15)


def start(cwd: Path, land_args: list[str], now: datetime, launch) -> tuple[str, Path]:
    """Create the snapshot branch and hidden worktree, hand them to ``launch``; (snapshot, log path)."""
    branch = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if branch in ("HEAD", "main") or branch.startswith(PREFIX):
        raise SystemExit(f"[land-async] run it from a topic branch's worktree, not {branch!r}")
    if git(cwd, "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("[land-async] uncommitted changes: commit them first (a landing takes only commits)")
    replace = "--replace" in land_args
    land_args = [a for a in land_args if a != "--replace"]
    for row in holders(cwd, branch):  # one landing per change: a second one only doubled the pretest
        carried = row.get("branch") not in (branch,) and not row.get("branch", "").startswith(PREFIX + branch + "-")
        where = f"{row['ticket']} ({row.get('branch')}, {row.get('status')}, pid {row.get('pid')})"
        if not replace or carried:
            raise SystemExit(f"[land-async] {branch} is already landing in {where}"
                             + ("; it rides in that batch" if carried else "; --replace stops it and queues this HEAD"))
        print(f"[land-async] --replace: stopping {where}", flush=True)
        stop(int(row["pid"]))
    if "--urgent" not in land_args:  # refused before a snapshot or hidden worktree exists
        land_queue = _queue()
        if why := land_queue.full(land_queue.queue_dir(cwd)):
            raise SystemExit(f"[land-async] {why}")
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


def resume(cwd: Path, name: str, land_args: list[str], launch, wait: float = 60, sleep=time.sleep) -> str | None:
    """Relaunch a stopped landing on its kept hidden tree and snapshot; the queue status its ticket reached, or None.

    The recovery used after console kills, reboots and paused queues (2026-10-30/31); a relaunch that never took a
    ticket once went unnoticed, so this waits for the ticket."""
    place = holder(cwd)
    tree = place / name
    if not tree.is_dir():
        raise SystemExit(f"[land-async] no hidden tree {tree}")
    if git(tree, "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit(f"[land-async] {tree} has uncommitted changes")
    snaps = [s for s in git(cwd, "for-each-ref", "--format=%(refname:short)", "refs/heads/land/").splitlines()
             if s.replace("/", "-") == name]
    if not snaps:
        raise SystemExit(f"[land-async] no snapshot branch for {name}")
    snap = snaps[0]
    if subprocess.run(["git", "-C", str(cwd), "merge-base", "--is-ancestor", snap, "main"]).returncode == 0:
        raise SystemExit(f"[land-async] {snap} is already in main")
    if held := [r for r in live_tickets(cwd) if r.get("branch") == snap or snap in (r.get("batch") or [])]:
        raise SystemExit(f"[land-async] {snap} is held by live ticket {held[0]['ticket']} ({held[0].get('branch')})")
    if git(tree, "rev-parse", "--abbrev-ref", "HEAD") != snap:  # land.py had moved it onto a batch candidate
        git(tree, "checkout", "-q", snap)
    (place / (name + ".stopped")).unlink(missing_ok=True)
    script = place / (name + ".land_async.py")
    script.write_bytes(Path(__file__).read_bytes())
    args = land_args or ["--tests", "auto"]
    launch([sys.executable, "-X", "utf8", str(script), "--supervise", str(tree), snap, *args],
           place / (name + ".resume.log"))
    for _ in range(max(1, int(wait / 5))):
        if mine := [r for r in live_tickets(cwd) if r.get("branch") == snap]:
            return mine[0].get("status")
        sleep(5)
    return None


def main(argv: list[str]) -> int:
    if argv[:1] == ["--supervise"]:
        return supervise(Path(argv[1]), argv[2], argv[3:])
    if argv[:1] == ["resume"] and len(argv) > 1:
        status = resume(Path.cwd(), argv[1], argv[2:], detach)
        note = f"ticket {status}" if status else "NO ticket after 60 s; read its .log"
        print(f"[land-async] resumed {argv[1]}: {note}")
        return 0 if status else 1
    snap, log = start(Path.cwd(), argv, datetime.now(timezone.utc), detach)
    print(f"[land-async] queued {snap}; this worktree is free now. Log: {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
