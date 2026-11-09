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
    python tools/land_async.py orphans [--resume]                    # after a reboot: landings that died unstopped

One live landing per branch (2026-10-31/11-01: the same change was queued twice and ran two pretests; 11-09 report:
322 re-queues). Queueing a HEAD the live landing already holds reuses it; a newer HEAD stops that older lander and
queues this one (``--replace`` is still accepted). A full queue is polled for FULL_WAIT_S before it stops. When a
landing ends, older snapshots of its branch that it covers go (land_gc's lossless rules).
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
QUEUE_FULL = "landing queue full"
ROOM_WAIT_S = 3 * 3600  # a landing refused only by the queue cap waits this long for room, then stops as before
FULL_WAIT_S, FULL_POLL_S = 30 * 60, 60  # D-889 addendum 32: a full queue at queue time waits, then stops
# Laptop commit exhaustion ended four landings at once on 2026-11-06 with these as land.py's last line.
RESOURCE_SHORTAGE = ("WinError 1450", "WinError 1455", "Out of memory", "MemoryError")
RESOURCE_RETRIES = 3
RESOURCE_WAIT_S = 300


class Busy(SystemExit):
    """Another supervisor or launch admission owns this OS lock."""


class Full(Exception):
    """The queue cap refused a new ticket; ``start`` polls outside the launch lock."""


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
    # resume without args reuses these: 11-03 a resumed explicit FULL fell back to --tests auto and landed untested
    (tree.parent / (tree.name + ".args.json")).write_text(json.dumps(args), encoding="utf-8")
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


def where(row: dict) -> str:
    return f"{row['ticket']} ({row.get('branch')}, {row.get('status')}, pid {row.get('pid')})"


def stop(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    elif os.getpgid(pid) == pid:  # detach made this supervisor the group leader: stop its land.py too
        os.killpg(pid, 15)
    else:
        os.kill(pid, 15)


def start(cwd: Path, land_args: list[str], now: datetime, launch) -> tuple[str, Path]:
    """Create the snapshot branch and hidden worktree, hand them to ``launch``; (snapshot, log path)."""
    deadline = time.monotonic() + FULL_WAIT_S
    while True:
        try:
            with locked(holder(cwd).parent / "rosy-land-async.lock", wait=True):
                return _start(cwd, land_args, now, launch)
        except Full as exc:  # polled outside the lock: resumes and rollups go on meanwhile
            if time.monotonic() >= deadline:
                raise SystemExit(f"[land-async] {exc} (waited {FULL_WAIT_S // 60} min)") from exc
            print(f"[land-async] {exc}; checking again every {FULL_POLL_S} s for up to {FULL_WAIT_S // 60} min",
                  flush=True)
            time.sleep(FULL_POLL_S)


def _start(cwd: Path, land_args: list[str], now: datetime, launch) -> tuple[str, Path]:
    branch = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if branch in ("HEAD", "main") or branch.startswith(PREFIX):
        raise SystemExit(f"[land-async] run it from a topic branch's worktree, not {branch!r}")
    if git(cwd, "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("[land-async] uncommitted changes: commit them first (a landing takes only commits)")
    land_args = [a for a in land_args if a != "--replace"]  # replacing a live landing is the default now
    replacements, rows = [], holders(cwd, branch)
    for row in rows:  # every owner is checked before any reuse or stop
        carried = row.get("branch") not in (branch,) and not row.get("branch", "").startswith(PREFIX + branch + "-")
        if carried or row.get("status") == "starting":
            raise SystemExit(f"[land-async] {branch} is already landing in {where(row)}"
                             + ("; it rides in that batch" if carried else "; its supervisor is still starting"))
    for row in rows:  # one landing per change: a second one only doubled the pretest
        if subprocess.run(["git", "-C", str(cwd), "merge-base", "--is-ancestor", "HEAD", row["branch"]],
                          capture_output=True).returncode == 0:  # its snapshot (with main merged in) holds HEAD
            print(f"[land-async] this HEAD is already landing in {where(row)}; nothing new queued", flush=True)
            return row["branch"], holder(cwd) / (row["branch"].replace("/", "-") + ".log")
        replacements.append((int(row["pid"]), where(row)))
    for pid, said in replacements:
        print(f"[land-async] a newer HEAD replaces {said}", flush=True)
        stop(pid)
    land_queue = _queue()
    # refused before a snapshot exists; a replacement or a rollup adopting a member's ticket adds none
    if not ("--urgent" in land_args or replacements or os.environ.get(land_queue.TICKET_ENV)):
        if why := land_queue.full(land_queue.queue_dir(cwd)):
            raise Full(why)
    snap = snapshot_name(branch, now)
    place = holder(cwd)
    place.mkdir(exist_ok=True)
    tree = place / snap.replace("/", "-")
    git(cwd, "branch", snap, "HEAD")
    git(cwd, "worktree", "add", "-q", str(tree), snap)
    import land_events  # tools/ is on sys.path (_queue); D-889 addendum 32: how far behind main it was queued
    land_events.bind(cwd, snap)
    land_events.emit("async", source=branch, behind=int(git(cwd, "rev-list", "--count", "HEAD..main", check=False) or 0))
    log = tree.parent / (tree.name + ".log")
    # The supervisor runs a copy beside the log, never the caller's file: Windows keeps a running script's
    # folder from being deleted, and the caller's worktree must be free (2026-10-28).
    spawn(tree, snap, land_args, log, launch)
    return snap, log


def wait_for_room(tree: Path, deadline: float) -> bool:
    """Poll until the queue takes an ordinary ticket again; False once ``deadline`` (monotonic) passes."""
    sys.path.insert(0, str(tree / "tools"))  # the snapshot's land_queue: this copy runs beside the log
    import land_queue
    while time.monotonic() < deadline:
        if not land_queue.full(land_queue.queue_dir(tree)):
            return True
        time.sleep(60)
    return False


def supervise(tree: Path, snap: str, land_args: list[str], run=subprocess.call, room=wait_for_room) -> int:
    """Run land.py in ``tree``; clean up when the snapshot landed, keep it and mark it stopped otherwise."""
    # shortcut: parent-only force kills can orphan pre-ticket children; use stop(), add OS job ownership if needed.
    with locked(tree.parent / (tree.name + ".supervisor.lock")):
        return _supervise(tree, snap, land_args, run, room)


def _supervise(tree: Path, snap: str, land_args: list[str], run, room) -> int:
    path = tree.parent / (tree.name + ".log")
    deadline = time.monotonic() + ROOM_WAIT_S
    shortages = 0
    while True:
        seen = path.stat().st_size if path.exists() else 0
        # land.py's own lines (the STOP reason) into the .log, appended: the inherited handle lost them (2026-10-28)
        with open(path, "a", encoding="utf-8") as log:
            # CREATE_NO_WINDOW: under the detached supervisor land.py got a new console, a tab of the default
            # terminal; closing that window killed every lander at once (exit 0xC000013A: 8 on 10-28, 12 on 10-30).
            code = run([sys.executable, "-X", "utf8", "tools/land.py", *land_args], cwd=str(tree), stdout=log,
                       stderr=subprocess.STDOUT, **({"creationflags": NO_WINDOW} if os.name == "nt" else {}))
        # start() saw room, but another session took the last slot before land.py did (2026-10-31: twice in a row)
        output = path.read_bytes()[seen:].decode("utf-8", "replace").rstrip().splitlines()
        reason = output[-1] if output else ""
        if code != 0 and shortages < RESOURCE_RETRIES and any(mark in reason for mark in RESOURCE_SHORTAGE):
            shortages += 1
            print(f"[land-async] {snap}: laptop out of resources ({reason}); land.py again in {RESOURCE_WAIT_S}s"
                  f" ({shortages}/{RESOURCE_RETRIES})", flush=True)
            time.sleep(RESOURCE_WAIT_S)
            continue
        full = code != 0 and reason.startswith(f"[land] STOP: {QUEUE_FULL} (")
        if not (full and time.monotonic() < deadline and room(tree, deadline)
                and time.monotonic() < deadline):
            break
        print(f"[land-async] {snap}: the queue has room again; land.py once more", flush=True)
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
    superseded(tree, snap)
    return code


def superseded(tree: Path, snap: str) -> list[str]:
    """Remove the older snapshots of ``snap``'s branch that land_gc finds nothing unique in (this one covers them);
    the names removed. 2026-11-08: 149 superseded snapshots (22 GB) waited for a person."""
    repo = tree.parent.parent.parent  # <main checkout>/.git/rosy-land-wt/<tree>; the tree itself may be gone
    sys.path[:0] = [str(repo / "tools"), str(Path(__file__).resolve().parent)]  # main's land_gc (this is a copy)
    try:
        import land_gc
        src = land_gc.source(snap)
        older = {ref.split("-batch")[0].replace("/", "-") for ref in git(
            repo, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{PREFIX}{src}-*").splitlines()
            if land_gc.SNAPSHOT.search(ref) and land_gc.source(ref) == src and ref < snap}
        gone = []
        for name in sorted(older):
            rows = land_gc.plan(repo, time.time(), 7, only=name)
            if any(row[0] == "remove" for row in rows) and not land_gc.apply(repo, rows):
                gone.append(name)
        if gone:
            print(f"[land-async] removed superseded snapshots of {src}: {gone}", flush=True)
        return gone
    except Exception as exc:  # cleanup must never change the landing's own outcome
        print(f"[land-async] superseded snapshot cleanup skipped: {exc}", flush=True)
        return []


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
    try:
        saved = json.loads((place / (name + ".args.json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = None
    args = land_args or saved or ["--tests", "auto"]
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


def orphans(cwd: Path, hours: float = 24, now: float | None = None) -> list[str]:
    """Hidden landings whose supervisor died without landing or stopping (11-03 20:44 a reboot killed the whole
    queue): no ``.stopped`` marker, no live supervisor or ticket, not in main, and the newest snapshot of its branch."""
    place, now = holder(cwd), now or time.time()
    if not place.is_dir():
        return []
    held = {r.get("branch") for r in live_owners(cwd)}
    newest: dict[str, Path] = {}
    for tree in place.iterdir():
        if tree.is_dir() and (place / (tree.name + ".land_async.py")).exists():
            key = tree.name.rsplit("-", 1)[0]
            if key not in newest or tree.name > newest[key].name:
                newest[key] = tree
    found = []
    for tree in newest.values():
        if ((place / (tree.name + ".stopped")).exists() or now - tree.stat().st_mtime > hours * 3600
                or running(tree)):
            continue
        snaps = [s for s in git(cwd, "for-each-ref", "--format=%(refname:short)", "refs/heads/land/").splitlines()
                 if s.replace("/", "-") == tree.name]
        if not snaps or snaps[0] in held or subprocess.run(
                ["git", "-C", str(cwd), "merge-base", "--is-ancestor", snaps[0], "main"]).returncode == 0:
            continue
        found.append(tree.name)
    return sorted(found)


def main(argv: list[str]) -> int:
    if any(arg in ("-h", "--help") for arg in argv):
        print(__doc__)
        return 0
    if argv[:1] == ["orphans"]:
        names = orphans(Path.cwd())
        print("\n".join(f"[land-async] orphan {n}" for n in names) or "[land-async] no orphaned landings")
        if "--resume" in argv:
            for name in names:
                main(["resume", name])
        return 0
    if argv[:1] == ["--supervise"]:
        return supervise(Path(argv[1]), argv[2], argv[3:])
    if argv[:1] == ["resume"] and len(argv) > 1:
        status = resume(Path.cwd(), argv[1], argv[2:], detach)
        note = ("starting (supervisor alive; ticket pending)" if status == "starting" else
                "landed" if status == "landed" else f"ticket {status}" if status else
                "supervisor exited without a ticket or landing; read its .log")
        print(f"[land-async] resumed {argv[1]}: {note}")
        return 0 if status else 1
    words = argv[argv.index("--mixed"):][:2] if "--mixed" in argv else []
    if subprocess.call(  # cheap gates fail here, before a snapshot or ticket exists
            [sys.executable, str(Path(__file__).with_name("land.py")), "--precheck", *words], cwd=Path.cwd()):
        return 1
    snap, log = start(Path.cwd(), argv, datetime.now(timezone.utc), detach)
    print(f"[land-async] queued {snap}; this worktree is free now. Log: {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
