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
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

HOLDER = "rosy-land-wt"
PREFIX = "land/"
ROLLUP = re.compile(r"land/fix/land-rollup-\d{14}-\d{14}")
NO_WINDOW = 0x08000000  # subprocess.CREATE_NO_WINDOW, named here so the module imports off Windows too


class Busy(SystemExit):
    """Another supervisor or launch admission owns this OS lock."""


@contextmanager
def locked(path: Path, wait: bool = False):
    """A process-owned lock; closing it, including on process death, releases ownership."""
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK if wait else msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            raise Busy(f"[land-async] another supervisor owns {path.name}") from exc
        yield


def running(tree: Path) -> bool:
    if not tree.parent.is_dir():
        return False
    try:
        with locked(tree.parent / (tree.name + ".supervisor.lock")):
            return False
    except Busy:
        return True


def spawn(tree: Path, snap: str, args: list[str], log: Path, launch):
    """Under launch admission, wait only until the child's lifetime lock is held or it exits."""
    if running(tree):
        raise SystemExit(f"[land-async] {snap} already has a live supervisor")
    script = tree.parent / (tree.name + ".land_async.py")
    script.write_bytes(Path(__file__).read_bytes())
    process = launch([sys.executable, "-X", "utf8", str(script), "--supervise", str(tree), snap, *args], log)
    if process is not None:
        while process.poll() is None and not running(tree):
            time.sleep(.02)
    return process


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


def live_owners(cwd: Path) -> list[dict]:
    """A rollup's lifetime lease owns its members even before its land.py takes a queue ticket."""
    rows, place = live_tickets(cwd), holder(cwd)
    for ref in git(cwd, "for-each-ref", "--format=%(refname:short)", "refs/heads/land/fix/land-rollup-*").splitlines():
        if ROLLUP.fullmatch(ref) and not any(r.get("branch") == ref for r in rows):
            if running(place / ref.replace("/", "-")):
                rows.append({"branch": ref, "status": "starting", "ticket": "supervisor"})
    return rows


def member_branches(place: Path, row: dict) -> list[str]:
    """Existing batch fields and land_rollup.build's .members record, without rewriting the queue ticket."""
    branch = row.get("branch") or ""
    path = place / (branch.replace("/", "-") + ".members")
    try:
        members = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(members, list) or not members or any(
                not isinstance(m, dict) or not isinstance(m.get("branch"), str) or not m["branch"] for m in members):
            raise ValueError("expected member branches")
    except FileNotFoundError as exc:
        if ROLLUP.fullmatch(branch):
            raise SystemExit(f"[land-async] unknown live rollup membership: {path.name}") from exc
        return row.get("batch") or []
    except (OSError, ValueError) as exc:
        raise SystemExit(f"[land-async] unreadable live rollup membership: {path.name}") from exc
    return [*(row.get("batch") or []), *(m["branch"] for m in members)]


def holders(cwd: Path, branch: str) -> list[dict]:
    """Tickets, rollups or supervisors landing ``branch``, including startup before its ticket exists."""
    snap = re.compile(rf"^{re.escape(PREFIX + branch)}-\d{{14}}")
    place = holder(cwd)
    rows = [r for r in live_owners(cwd) if r.get("branch") == branch or snap.match(r.get("branch") or "")
            or any(snap.match(b) for b in member_branches(place, r))]
    for ref in git(cwd, "for-each-ref", "--format=%(refname:short)", "refs/heads/land/").splitlines():
        if snap.match(ref) and not any(r.get("branch") == ref or ref in (r.get("batch") or []) for r in rows):
            if running(holder(cwd) / ref.replace("/", "-")):
                rows.append({"branch": ref, "status": "starting", "ticket": "supervisor"})
    return rows


def stop(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    elif os.getpgid(pid) == pid:  # detach made this supervisor the group leader: stop its land.py too
        os.killpg(pid, 15)
    else:
        os.kill(pid, 15)


def start(cwd: Path, land_args: list[str], now: datetime, launch) -> tuple[str, Path]:
    """Create the snapshot branch and hidden worktree, hand them to ``launch``; (snapshot, log path)."""
    with locked(holder(cwd).parent / "rosy-land-async.lock", wait=True):
        return _start(cwd, land_args, now, launch)


def _start(cwd: Path, land_args: list[str], now: datetime, launch) -> tuple[str, Path]:
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
        if not replace or carried or row.get("status") == "starting":
            raise SystemExit(f"[land-async] {branch} is already landing in {where}"
                             + ("; it rides in that batch" if carried else "; its supervisor is still starting"
                                if row.get("status") == "starting" else "; --replace stops it and queues this HEAD"))
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
    spawn(tree, snap, land_args, log, launch)
    return snap, log


def supervise(tree: Path, snap: str, land_args: list[str], run=subprocess.call) -> int:
    """Run land.py in ``tree``; clean up when the snapshot landed, keep it and mark it stopped otherwise."""
    # shortcut: parent-only force kills can orphan pre-ticket children; use stop(), add OS job ownership if needed.
    with locked(tree.parent / (tree.name + ".supervisor.lock")):
        return _supervise(tree, snap, land_args, run)


def _supervise(tree: Path, snap: str, land_args: list[str], run) -> int:
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


def _resume_start(cwd: Path, name: str, land_args: list[str], launch):
    place = holder(cwd)
    tree = place / name
    if not tree.is_dir():
        raise SystemExit(f"[land-async] no hidden tree {tree}")
    if running(tree):
        raise SystemExit(f"[land-async] {name} already has a live supervisor")
    if git(tree, "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit(f"[land-async] {tree} has uncommitted changes")
    snaps = [s for s in git(cwd, "for-each-ref", "--format=%(refname:short)", "refs/heads/land/").splitlines()
             if s.replace("/", "-") == name]
    if not snaps:
        raise SystemExit(f"[land-async] no snapshot branch for {name}")
    snap = snaps[0]
    if subprocess.run(["git", "-C", str(cwd), "merge-base", "--is-ancestor", snap, "main"]).returncode == 0:
        raise SystemExit(f"[land-async] {snap} is already in main")
    if held := [r for r in live_owners(cwd) if r.get("branch") == snap or snap in member_branches(place, r)]:
        owner = "live supervisor" if held[0]["ticket"] == "supervisor" else f"live ticket {held[0]['ticket']}"
        raise SystemExit(f"[land-async] {snap} is held by {owner} ({held[0].get('branch')})")
    if git(tree, "rev-parse", "--abbrev-ref", "HEAD") != snap:  # land.py had moved it onto a batch candidate
        git(tree, "checkout", "-q", snap)
    (place / (name + ".stopped")).unlink(missing_ok=True)
    args = land_args or ["--tests", "auto"]
    head = git(tree, "rev-parse", "HEAD")
    process = spawn(tree, snap, args, place / (name + ".resume.log"), launch)
    return snap, head, process


def resume(cwd: Path, name: str, land_args: list[str], launch, wait: float = 60, sleep=time.sleep) -> str | None:
    """Return ticket status, starting while its supervisor lives, landed after a quick success, or None on failure."""
    with locked(holder(cwd).parent / "rosy-land-async.lock", wait=True):
        snap, head, process = _resume_start(cwd, name, land_args, launch)
    for _ in range(max(1, int(wait / 5))):
        if mine := [r for r in live_tickets(cwd) if r.get("branch") == snap]:
            return mine[0].get("status")
        if process is not None and process.poll() is not None:
            break
        sleep(5)
    if process is not None and process.poll() is None:
        return "starting"
    if process is not None and process.poll() == 0 and subprocess.run(
            ["git", "-C", str(cwd), "merge-base", "--is-ancestor", head, "main"]).returncode == 0:
        return "landed"
    return None


def main(argv: list[str]) -> int:
    if argv[:1] == ["--supervise"]:
        return supervise(Path(argv[1]), argv[2], argv[3:])
    if argv[:1] == ["resume"] and len(argv) > 1:
        status = resume(Path.cwd(), argv[1], argv[2:], detach)
        note = ("starting (supervisor alive; ticket pending)" if status == "starting" else
                "landed" if status == "landed" else f"ticket {status}" if status else
                "supervisor exited without a ticket or landing; read its .log")
        print(f"[land-async] resumed {argv[1]}: {note}")
        return 0 if status else 1
    snap, log = start(Path.cwd(), argv, datetime.now(timezone.utc), detach)
    print(f"[land-async] queued {snap}; this worktree is free now. Log: {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
