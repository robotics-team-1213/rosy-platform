"""tools/land_async.py: a landing runs from a hidden snapshot worktree, so the branch's worktree is free at once."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from test_land_gc import supervisor_lease

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("land_async", ROOT / "tools" / "land_async.py")
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)
NOW = datetime(2026, 10, 28, 4, 40, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("argv", [
    ["-h"], ["--help"], ["--tests", "full", "--help"],
    ["resume", "stopped-tree", "-h"], ["resume", "--help"],
    ["orphans", "--resume", "--help"],
    ["--supervise", "hidden-tree", "snapshot", "--help"],
])
def test_help_returns_before_any_landing_or_git_access(argv, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("help accessed the landing pipeline")

    for name in ("start", "resume", "supervise", "orphans", "detach", "git", "holder", "_queue"):
        monkeypatch.setattr(tool, name, forbidden)
    assert tool.main(argv) == 0
    output = capsys.readouterr().out
    assert "python tools/land_async.py" in output
    assert "resume <tree-name>" in output


@pytest.mark.parametrize("argv", [["-h"], ["--help"], ["resume", "missing", "--help"]])
def test_help_script_works_outside_a_repository_without_writing(tmp_path, argv):
    result = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "land_async.py"), *argv],
                            cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "python tools/land_async.py" in result.stdout
    assert not result.stderr
    assert list(tmp_path.iterdir()) == []


def test_help_text_inside_a_forwarded_value_is_not_a_help_request(monkeypatch):
    argv = ["--tests", "test/example.py --help"]
    calls = []
    monkeypatch.setattr(tool.subprocess, "call", lambda *a, **k: 0)  # land.py --precheck has its own tests
    monkeypatch.setattr(tool, "start", lambda cwd, args, now, launch: (
        calls.append(args) or ("snapshot", Path("log"))))
    assert tool.main(argv) == 0
    assert calls == [argv]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "user.email", "t@example.invalid")
    _git(main, "config", "user.name", "t")
    (main / "a.txt").write_text("1\n")
    _git(main, "add", "a.txt")
    _git(main, "commit", "-q", "-m", "base")
    dev = tmp_path / "dev"
    _git(main, "worktree", "add", "-q", "-b", "feat/x", str(dev))
    (dev / "a.txt").write_text("2\n")
    _git(dev, "commit", "-qam", "change")
    return main, dev


def test_start_snapshots_head_into_a_hidden_worktree_and_frees_the_branch(repo):
    main, dev = repo
    launched = []
    snap, log = tool.start(dev, ["--tests", "auto"], NOW, lambda argv, log: launched.append((argv, log)))
    assert snap == "land/feat/x-20261028044000"
    tree = log.parent / log.name.removesuffix(".log")
    assert tree.parent.name == tool.HOLDER and tree.parent.parent.name == ".git"  # not under .worktrees
    assert _git(tree, "rev-parse", "HEAD") == _git(dev, "rev-parse", "HEAD")
    assert _git(dev, "rev-parse", "--abbrev-ref", "HEAD") == "feat/x"  # the owner's worktree is untouched
    (argv, _), = launched
    assert argv[-4:] == [str(tree), snap, "--tests", "auto"] and "--supervise" in argv
    assert Path(argv[3]).parent == tree.parent and str(dev) not in argv[3]  # never the caller's file


@pytest.mark.parametrize("dirty", [True, False])
def test_uncommitted_changes_are_refused_never_carried(repo, dirty):
    _, dev = repo
    if dirty:
        (dev / "a.txt").write_text("3\n")
        with pytest.raises(SystemExit, match="uncommitted"):
            tool.start(dev, [], NOW, lambda *a: None)
    else:
        assert tool.start(dev, [], NOW, lambda *a: None)[0].startswith("land/feat/x-")


def test_main_and_snapshot_branches_are_refused(repo):
    main, _ = repo
    with pytest.raises(SystemExit, match="topic branch"):
        tool.start(main, [], NOW, lambda *a: None)


@pytest.mark.parametrize("lands", [True, False])
def test_supervise_cleans_up_only_a_landed_snapshot(repo, lands):
    main, dev = repo
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")

    def fake_land(argv, cwd, stdout, stderr, **kw):
        assert kw == ({"creationflags": tool.NO_WINDOW} if os.name == "nt" else {})  # no window to close
        stdout.write("[land] STOP: merge aborted\n")  # what the owner must find in the .log
        if lands:
            _git(main, "merge", "-q", "--ff-only", snap)
        return 0 if lands else 1
    code = tool.supervise(tree, snap, [], run=fake_land)
    assert "[land] STOP: merge aborted" in log.read_text(encoding="utf-8")
    assert code == (0 if lands else 1)
    assert tree.exists() is not lands
    assert bool(_git(main, "branch", "--list", snap)) is not lands
    assert (tree.parent / (tree.name + ".stopped")).exists() is not lands


@pytest.mark.parametrize("room", [True, False])
def test_a_landing_refused_only_by_a_full_queue_waits_for_room(repo, room):
    """start() saw room, another session took the last slot first: wait and run land.py again, not stop."""
    main, dev = repo
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")
    runs = []

    def fake_land(argv, cwd, stdout, stderr, **kw):
        assert tool.running(tree), "the supervisor owns every queue-admission attempt"
        runs.append(argv)
        if len(runs) == 1:
            stdout.write(f"[land] STOP: {tool.QUEUE_FULL} (12/12 tickets)\n")
            return 1
        _git(main, "merge", "-q", "--ff-only", snap)
        return 0
    def wait_for_room(kept, deadline):
        assert kept == tree and tool.running(tree), "queue-full backoff must retain lifetime ownership"
        with pytest.raises(tool.Busy):
            tool.supervise(tree, snap, [], run=lambda *a, **kw: pytest.fail("duplicate land.py ran during backoff"))
        assert not (tree.parent / (tree.name + ".stopped")).exists()
        return room

    code = tool.supervise(tree, snap, [], run=fake_land, room=wait_for_room)
    assert len(runs) == (2 if room else 1)
    assert code == (0 if room else 1)
    assert (tree.parent / (tree.name + ".stopped")).exists() is not room


@pytest.mark.parametrize("last_line,attempts,stopped", [
    ("OSError: [WinError 1450] Insufficient system resources", 4, True),
    ("fatal: Out of memory, malloc failed (tried to allocate 1884142 bytes)", 4, True),
    ("[land] STOP: 1 new failure(s): test_x", 1, True),
])
def test_only_a_laptop_resource_shortage_reruns_land_and_only_a_few_times(repo, monkeypatch, last_line, attempts, stopped):
    _, dev = repo
    monkeypatch.setattr(tool, "RESOURCE_WAIT_S", 0)
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")
    runs = []

    def fake_land(argv, cwd, stdout, stderr, **kw):
        runs.append(argv)
        stdout.write(last_line + "\n")
        return 1

    assert tool.supervise(tree, snap, [], run=fake_land) == 1
    assert len(runs) == attempts
    assert (tree.parent / (tree.name + ".stopped")).exists() is stopped


def test_a_landing_recovers_after_a_resource_shortage(repo, monkeypatch):
    main, dev = repo
    monkeypatch.setattr(tool, "RESOURCE_WAIT_S", 0)
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")
    runs = []

    def fake_land(argv, cwd, stdout, stderr, **kw):
        runs.append(argv)
        if len(runs) == 1:
            stdout.write("MemoryError\n")
            return 1
        _git(main, "merge", "-q", "--ff-only", snap)
        return 0

    assert tool.supervise(tree, snap, [], run=fake_land) == 0
    assert len(runs) == 2
    assert not (tree.parent / (tree.name + ".stopped")).exists()


def test_expired_room_deadline_refuses_even_a_free_queue(repo, monkeypatch):
    _, dev = repo
    monkeypatch.setattr(tool.time, "monotonic", lambda: 11)
    monkeypatch.setattr(tool._queue(), "full", lambda qdir: None)
    assert not tool.wait_for_room(dev, 10)


@pytest.mark.parametrize("room_returns_late", [False, True])
def test_supervisor_retry_deadline_is_authoritative(repo, monkeypatch, room_returns_late):
    _, dev = repo
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")
    now, runs, waits = [0], [], []
    monkeypatch.setattr(tool.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(tool, "ROOM_WAIT_S", 10)

    def failed(argv, cwd, stdout, stderr, **kw):
        runs.append(argv)
        stdout.write(f"[land] STOP: {tool.QUEUE_FULL} (12/12 tickets)\n" if len(runs) == 1
                     else "[land] STOP: unrelated failure\n")
        if not room_returns_late:
            now[0] = 11
        return 1

    def room(*args):
        waits.append(args)
        now[0] = 11
        return True

    assert tool.supervise(tree, snap, [], run=failed, room=room) == 1
    assert len(runs) == 1, "an expired supervisor must not retry even if the room callback returns True"
    assert len(waits) == int(room_returns_late)
    assert (tree.parent / (tree.name + ".stopped")).exists()


def test_captured_queue_full_inside_a_new_failure_is_not_an_admission_refusal(repo):
    _, dev = repo
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")

    def failed(argv, cwd, stdout, stderr, **kw):
        stdout.write(f"FAILED test_queue_full\nCaptured stdout call\n[land] STOP: {tool.QUEUE_FULL} (12/12 tickets)\n"
                     "[land] STOP: NEW failure in test_queue_full; not landing\n")
        return 1

    assert tool.supervise(tree, snap, [], run=failed,
                          room=lambda *args: pytest.fail("a confirmed NEW failure must not retry")) == 1
    assert (tree.parent / (tree.name + ".stopped")).exists()


def test_the_supervisor_never_holds_the_callers_worktree(tmp_path, monkeypatch):
    """Windows cannot delete a folder that a live process has as its cwd (2026-10-28: freed worktrees stayed)."""
    caller = tmp_path / "worktree"
    caller.mkdir()
    monkeypatch.chdir(caller)
    log = tmp_path / "holder" / "snap.log"
    log.parent.mkdir()
    tool.detach([sys.executable, "-c", "import os; print(os.getcwd())"], log).wait(timeout=60)
    assert Path(log.read_text(encoding="utf-8").strip()) == log.parent


def _ticket(main: Path, name: str, **row) -> Path:
    qdir = main / ".git" / "rosy-land-queue"
    qdir.mkdir(exist_ok=True)
    path = qdir / f"{name}-1.json"
    path.write_text(json.dumps({"pid": os.getpid(), "status": "pending", **row}), encoding="utf-8")
    return path


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_a_branch_already_landing_is_refused_and_replace_stops_that_lander(repo, monkeypatch):
    """2026-10-31/11-01: the same change was queued twice and ran two pretests on the shared test PCs."""
    main, dev = repo
    _ticket(main, "0001", branch="land/feat/x-20261027000000")
    with pytest.raises(SystemExit, match="already landing in 0001-1.json"):
        tool.start(dev, ["--tests", "auto"], NOW, lambda *a: None)
    stopped, launched = [], []
    monkeypatch.setattr(tool, "stop", stopped.append)
    tool.start(dev, ["--replace", "--tests", "auto"], NOW, lambda argv, log: launched.append(argv))
    assert stopped == [os.getpid()] and "--replace" not in launched[0] and launched[0][-2:] == ["--tests", "auto"]


def test_a_branch_carried_in_a_batch_is_refused_even_with_replace_and_a_dead_ticket_is_not(repo, monkeypatch):
    main, dev = repo
    carrier = _ticket(main, "0002", branch="land/feat/y-20261027000000", batch=["land/feat/x-20261027000000"])
    monkeypatch.setattr(tool, "stop", lambda pid: pytest.fail("never stops another branch's leader"))
    with pytest.raises(SystemExit, match="rides in that batch"):
        tool.start(dev, ["--replace"], NOW, lambda *a: None)
    carrier.write_text(json.dumps({"pid": _dead_pid(), "branch": "land/feat/x-20261027000000"}), encoding="utf-8")
    assert tool.start(dev, [], NOW, lambda *a: None)[0] == "land/feat/x-20261028044000"


def test_resume_relaunches_a_stopped_snapshot_and_reports_its_ticket(repo):
    main, dev = repo
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")
    (tree.parent / (tree.name + ".stopped")).write_text("land.py exit 1\n")
    launched = []

    def lander(argv, log_):  # the relaunched land.py takes a ticket on its snapshot
        launched.append(argv)
        _ticket(main, "0003", branch=snap)
    assert tool.resume(dev, tree.name, [], lander, wait=5, sleep=lambda s: None) == "pending"
    assert launched[0][-4:] == [str(tree), snap, "--tests", "auto"]
    assert not (tree.parent / (tree.name + ".stopped")).exists()
    with pytest.raises(SystemExit, match="held by live ticket"):
        tool.resume(dev, tree.name, [], lander, wait=5, sleep=lambda s: None)


def test_resume_without_args_keeps_the_queued_land_args(repo):
    main, dev = repo
    snap, log = tool.start(dev, ["--tests", "full", "--no-cache"], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")
    (tree.parent / (tree.name + ".stopped")).write_text("land.py exit 1\n")
    launched = []
    tool.resume(dev, tree.name, [], lambda argv, log_: launched.append(argv), wait=5, sleep=lambda s: None)
    assert launched[0][-5:] == [str(tree), snap, "--tests", "full", "--no-cache"]


def test_resume_refuses_a_landed_snapshot_and_reports_a_relaunch_without_ticket(repo):
    main, dev = repo
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")
    assert tool.resume(dev, tree.name, [], lambda *a: None, wait=5, sleep=lambda s: None) is None
    _git(main, "merge", "-q", "--ff-only", snap)
    with pytest.raises(SystemExit, match="already in main"):
        tool.resume(dev, tree.name, [], lambda *a: None, wait=5, sleep=lambda s: None)


@pytest.fixture
def live_rollup(repo):
    main, dev = repo
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")
    rollup = "land/fix/land-rollup-20261102045038-20261102045038"
    _git(main, "branch", rollup, snap)
    ticket = _ticket(main, "0004", branch=rollup, status="waiting")
    metadata = log.parent / (rollup.replace("/", "-") + ".members")
    metadata.write_text(json.dumps([{"branch": snap, "worktree": str(tree)}]), encoding="utf-8")
    (tree.parent / (tree.name + ".stopped")).write_text("previous stop")
    return main, dev, snap, tree, ticket, metadata


@pytest.mark.parametrize("action", ["start", "replace", "resume"])
def test_live_one_ticket_rollup_owns_members_without_batch_state(live_rollup, monkeypatch, action):
    _, dev, _, tree, ticket, _ = live_rollup
    before = ticket.read_bytes()
    monkeypatch.setattr(tool, "stop", lambda pid: pytest.fail("a member cannot stop the rollup leader"))
    with pytest.raises(SystemExit, match="rides in that batch|held by live ticket"):
        if action == "resume":
            tool.resume(dev, tree.name, [], lambda *a: pytest.fail("duplicate member resumed"), wait=0)
        else:
            tool.start(dev, ["--replace"] if action == "replace" else [], NOW.replace(second=1),
                       lambda *a: pytest.fail("duplicate member started"))
    assert ticket.read_bytes() == before and "batch" not in json.loads(before)
    assert (tree.parent / (tree.name + ".stopped")).exists()


@pytest.mark.parametrize("dead", [False, True])
@pytest.mark.parametrize("action", ["start", "resume"])
def test_unrelated_or_dead_rollup_does_not_own_the_member(live_rollup, action, dead):
    _, dev, _, tree, ticket, metadata = live_rollup
    if dead:
        row = json.loads(ticket.read_text())
        ticket.write_text(json.dumps({**row, "pid": _dead_pid()}))
        metadata.write_text("malformed dead metadata")
    else:
        metadata.write_text(json.dumps([{"branch": "land/feat/unrelated-20261102045038", "worktree": "other"}]))
    launched = []
    launch = lambda *args: launched.append(args)  # noqa: E731
    if action == "start":
        tool.start(dev, [], NOW.replace(second=1), launch)
    else:
        tool.resume(dev, tree.name, [], launch, wait=0, sleep=lambda s: None)
    assert len(launched) == 1


@pytest.mark.parametrize("content", [None, "{", "{}", "[]", '[{"worktree":"x"}]', '[{"branch":null}]'])
@pytest.mark.parametrize("action", ["start", "resume"])
def test_live_rollup_unknown_membership_fails_closed(live_rollup, content, action):
    _, dev, _, tree, _, metadata = live_rollup
    if content is None:
        metadata.unlink()
    else:
        metadata.write_text(content)
    launched = []
    with pytest.raises(SystemExit, match="membership"):
        if action == "start":
            tool.start(dev, [], NOW.replace(second=1), lambda *args: launched.append(args))
        else:
            tool.resume(dev, tree.name, [], lambda *args: launched.append(args), wait=0, sleep=lambda s: None)
    assert not launched


@pytest.mark.parametrize("action", ["start", "resume"])
def test_ordinary_rollup_code_branch_needs_no_members_file(live_rollup, action):
    _, dev, _, tree, ticket, metadata = live_rollup
    metadata.unlink()
    row = json.loads(ticket.read_text())
    ticket.write_text(json.dumps({**row, "branch": "land/fix/land-rollup-member-ownership-20261102045038"}))
    launched = []
    if action == "start":
        tool.start(dev, [], NOW.replace(second=1), lambda *args: launched.append(args))
    else:
        tool.resume(dev, tree.name, [], lambda *args: launched.append(args), wait=0, sleep=lambda s: None)
    assert len(launched) == 1


@pytest.fixture
def pre_ticket_rollup(live_rollup):
    main, dev, _, tree, ticket, metadata = live_rollup
    branch = json.loads(ticket.read_text())["branch"]
    ticket.unlink()
    leader = metadata.parent / metadata.name.removesuffix(".members")
    _git(main, "worktree", "add", "-q", str(leader), branch)
    return dev, tree, leader, metadata


@pytest.mark.parametrize("action", ["start", "replace", "resume"])
@pytest.mark.parametrize("alive", [False, True])
def test_rollup_lease_owns_members_before_its_ticket(pre_ticket_rollup, monkeypatch, action, alive):
    dev, tree, leader, metadata = pre_ticket_rollup
    monkeypatch.setattr(tool, "stop", lambda pid: pytest.fail("a member cannot stop its rollup supervisor"))
    launched = []

    def attempt():
        if action == "resume":
            return tool.resume(dev, tree.name, [], lambda *args: launched.append(args), wait=0, sleep=lambda s: None)
        return tool.start(dev, ["--replace"] if action == "replace" else [], NOW.replace(second=1),
                          lambda *args: launched.append(args))

    if alive:
        with supervisor_lease(leader):
            with pytest.raises(SystemExit, match="supervisor"):
                attempt()
        assert not launched
    else:
        with supervisor_lease(leader):
            pass
        metadata.write_text("stale malformed metadata")
        attempt()
        assert len(launched) == 1


@pytest.mark.parametrize("content", [None, "{"])
@pytest.mark.parametrize("action", ["start", "resume"])
def test_pre_ticket_rollup_unknown_membership_fails_closed(pre_ticket_rollup, content, action):
    dev, tree, leader, metadata = pre_ticket_rollup
    if content is None:
        metadata.unlink()
    else:
        metadata.write_text(content)
    with supervisor_lease(leader):
        with pytest.raises(SystemExit, match="membership"):
            if action == "start":
                tool.start(dev, [], NOW.replace(second=1), lambda *args: None)
            else:
                tool.resume(dev, tree.name, [], lambda *args: None, wait=0, sleep=lambda s: None)


def test_replace_validates_all_owners_before_stopping_a_direct_member(pre_ticket_rollup, monkeypatch):
    dev, tree, leader, _ = pre_ticket_rollup
    main = tool.holder(dev).parent.parent
    _ticket(main, "0001", branch=_git(tree, "rev-parse", "--abbrev-ref", "HEAD"))
    stopped = []
    monkeypatch.setattr(tool, "stop", stopped.append)
    with supervisor_lease(leader):
        with pytest.raises(SystemExit, match="rides in that batch"):
            tool.start(dev, ["--replace"], NOW.replace(second=1), lambda *args: pytest.fail("duplicate started"))
    assert not stopped, "a later rollup owner must prevent every destructive replacement step"


@pytest.fixture
def starting_lander(repo, tmp_path):
    main, dev = repo
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")
    stop, admit, calls = (tmp_path / name for name in ("stop", "admit", "calls"))
    script = tree / "tools" / "land.py"
    script.parent.mkdir()
    qdir = main / ".git" / "rosy-land-queue"
    script.write_text(
        "import json,os,time\nfrom pathlib import Path\n"
        f"Path({str(calls.with_suffix('.pid'))!r}).write_text(str(os.getpid()))\n"
        f"with Path({str(calls)!r}).open('a') as stream: stream.write('run\\n')\n"
        f"while not Path({str(stop)!r}).exists():\n"
        f" if Path({str(admit)!r}).exists():\n"
        f"  q = Path({str(qdir)!r}); q.mkdir(exist_ok=True)\n"
        f"  pending = q/'0001-1.tmp'; pending.write_text(json.dumps(dict(pid=os.getpid(),branch={snap!r},status='pending')))\n"
        "  os.replace(pending, q/'0001-1.json')\n"
        " time.sleep(.02)\n"
        "raise SystemExit(7)\n", encoding="utf-8")
    processes = []

    def launch(argv, path):
        process = tool.detach(argv, path)
        processes.append(process)
        return process

    yield main, dev, snap, tree, admit, calls, launch
    stop.touch()
    for process in processes:
        process.wait(timeout=10)


def test_live_startup_is_successful_and_cannot_be_resumed_twice(starting_lander):
    main, dev, snap, tree, admit, calls, launch = starting_lander
    assert tool.resume(dev, tree.name, [], launch, wait=0, sleep=lambda s: None) == "starting"
    bootstrap = tree.parent / (tree.name + ".land_async.py")
    bootstrap.write_text(bootstrap.read_text(encoding="utf-8") + "\n# keep running bootstrap\n", encoding="utf-8")
    before = bootstrap.read_bytes()
    with pytest.raises(SystemExit, match="supervisor"):
        tool.resume(dev, tree.name, [], launch, wait=0, sleep=lambda s: None)
    assert bootstrap.read_bytes() == before
    admit.touch()
    until = time.monotonic() + 5
    while not tool.live_tickets(dev) and time.monotonic() < until:
        time.sleep(.02)
    assert tool.live_tickets(dev)[0]["branch"] == snap
    assert calls.read_text() == "run\n", "only one land.py may drive the hidden tree"


def test_exited_supervisor_without_ticket_is_a_failure(repo):
    _, dev = repo
    _, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")
    processes = []

    def launch(*a):
        process = subprocess.Popen([sys.executable, "-c", "raise SystemExit(7)"])
        processes.append(process)
        return process

    assert tool.resume(dev, tree.name, [], launch, wait=0, sleep=lambda s: processes[0].wait(timeout=5)) is None
    assert processes[0].wait(timeout=5) == 7


def test_direct_duplicate_supervisor_does_not_run_or_mark_the_owner_stopped(starting_lander):
    _, dev, snap, tree, _, calls, launch = starting_lander
    tool.resume(dev, tree.name, [], launch, wait=0, sleep=lambda s: None)
    duplicate = subprocess.run([sys.executable, str(ROOT / "tools/land_async.py"), "--supervise", str(tree), snap],
                               capture_output=True, text=True, timeout=5)
    assert duplicate.returncode != 0 and "supervisor" in duplicate.stdout + duplicate.stderr
    assert not (tree.parent / (tree.name + ".stopped")).exists()
    until = time.monotonic() + 5
    while not calls.exists() and time.monotonic() < until:
        time.sleep(.02)
    assert calls.read_text() == "run\n"


def test_start_refuses_the_same_change_while_its_supervisor_has_no_ticket(starting_lander):
    _, dev, _, tree, _, _, launch = starting_lander
    tool.resume(dev, tree.name, [], launch, wait=0, sleep=lambda s: None)
    with pytest.raises(SystemExit, match="supervisor"):
        tool.start(dev, [], NOW.replace(second=1), launch)


def test_concurrent_resumes_admit_only_one_supervisor(starting_lander):
    _, dev, _, tree, _, calls, _ = starting_lander
    code = (f"import sys;sys.path.insert(0,{str(ROOT / 'tools')!r});import land_async as a;from pathlib import Path;"
            f"print(a.resume(Path({str(dev)!r}),{tree.name!r},[],a.detach,wait=0,sleep=lambda s:None))")
    parents = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True) for _ in range(2)]
    results = [process.communicate(timeout=10) for process in parents]
    assert sorted(process.returncode for process in parents) == [0, 1]
    assert sum("starting" in stdout for stdout, _ in results) == 1
    assert any("supervisor" in stderr for _, stderr in results)
    until = time.monotonic() + 5
    while not calls.exists() and time.monotonic() < until:
        time.sleep(.02)
    assert calls.read_text() == "run\n"


def test_quick_success_without_a_ticket_reports_landed(repo):
    main, dev = repo
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")

    def finish(*a):
        process = subprocess.Popen(["git", "-C", str(main), "merge", "-q", "--ff-only", snap])
        assert process.wait(timeout=5) == 0
        return process

    assert tool.resume(dev, tree.name, [], finish, wait=0, sleep=lambda s: None) == "landed"


def test_official_stop_ends_starting_supervisors_child_and_releases_ownership(starting_lander):
    _, dev, _, tree, _, calls, launch = starting_lander
    processes = []

    def capture(*args):
        process = launch(*args)
        processes.append(process)
        return process

    tool.resume(dev, tree.name, [], capture, wait=0, sleep=lambda s: None)
    until = time.monotonic() + 5
    pidfile = calls.with_suffix(".pid")
    while not pidfile.exists() and time.monotonic() < until:
        time.sleep(.02)
    child = int(pidfile.read_text())
    tool.stop(processes[0].pid)
    processes[0].wait(timeout=5)

    def child_exited():
        if not tool._queue().pid_alive(child):
            return True
        state = Path(f"/proc/{child}/stat")
        try:
            return state.is_file() and state.read_text().split()[2] == "Z"  # killed orphan awaiting OS reaping
        except (FileNotFoundError, ProcessLookupError):
            return True

    until = time.monotonic() + 5
    while not child_exited() and time.monotonic() < until:
        time.sleep(.02)
    assert child_exited(), "stop must end the child as well as its detached supervisor"
    assert tool.resume(dev, tree.name, [], capture, wait=0, sleep=lambda s: None) == "starting"


def test_orphans_lists_a_snapshot_whose_supervisor_died_unstopped(repo):
    """11-03 20:44 a reboot killed every lander; nothing wrote .stopped, and the dead tickets were swept."""
    main, dev = repo
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")
    assert tool.orphans(dev, now=tree.stat().st_mtime) == [tree.name]
    stopped = tree.parent / (tree.name + ".stopped")
    stopped.write_text("land.py exit 1\n")
    assert tool.orphans(dev, now=tree.stat().st_mtime) == []  # a stopped landing waits for its owner
    stopped.unlink()
    assert tool.orphans(dev, now=tree.stat().st_mtime + 25 * 3600) == []  # older than a day: not a recovery
    _ticket(main, "0004", branch=snap)
    assert tool.orphans(dev, now=tree.stat().st_mtime) == []  # a live ticket still owns it
