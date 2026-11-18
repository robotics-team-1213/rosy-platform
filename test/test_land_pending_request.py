"""A landing request refused for a full queue (NOT QUEUED) is kept, and land_tick's requeue pass relaunches it."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import pytest  # noqa: E402

import land_queue  # noqa: E402
import land_tick  # noqa: E402


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
    _git(work, "checkout", "-q", "-b", "feat/x")
    return work


def _tick(monkeypatch, launched, full=None, holders=()):
    monkeypatch.setattr(land_tick.land_queue, "full", lambda qdir, lane="": full)
    monkeypatch.setattr(land_tick.land_async, "holders", lambda repo, branch: list(holders))
    monkeypatch.setattr(land_tick.land_async, "detach", lambda argv, log, cwd=None: launched.append(argv))


def _kept(repo):
    return sorted(land_queue.queue_dir(repo).glob("pending-*.json"))


def test_not_queued_request_leaves_one_pending_request(repo):
    said = land_queue.keep_pending(repo, ["--tests", "auto"])
    land_queue.keep_pending(repo, ["--tests", "auto"])  # the same branch again supersedes, not duplicates
    (path,) = _kept(repo)
    row = json.loads(path.read_text(encoding="utf-8"))
    assert str(path) in said
    assert (row["branch"], row["args"], row["cwd"]) == ("feat/x", ["--tests", "auto"], str(repo))
    assert row["ref"] == _git(repo, "rev-parse", "feat/x")


def test_pending_request_is_launched_once_when_the_queue_has_room(repo, monkeypatch):
    land_queue.keep_pending(repo, ["--tests", "auto"])
    launched = []
    _tick(monkeypatch, launched)
    assert land_tick.requeue(repo) == "relaunched pending feat/x"
    assert len(launched) == 1 and launched[0][-4:] == ["--branch", "feat/x", "--tests", "auto"][-4:]
    assert not _kept(repo)


def test_pending_request_is_kept_while_the_queue_is_full(repo, monkeypatch):
    land_queue.keep_pending(repo, [])
    launched = []
    _tick(monkeypatch, launched, full="landing queue full (12/12 tickets)")
    assert land_tick.requeue(repo) == "queue full"
    assert not launched and len(_kept(repo)) == 1


def test_pending_request_is_dropped_when_the_branch_already_lands(repo, monkeypatch):
    land_queue.keep_pending(repo, [])
    launched = []
    _tick(monkeypatch, launched, holders=[{"ticket": "0001"}])
    land_tick.requeue(repo)
    assert not launched and not _kept(repo)


def test_pending_request_is_dropped_when_the_branch_moved_past_it(repo, monkeypatch):
    land_queue.keep_pending(repo, [])
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "newer")
    launched = []
    _tick(monkeypatch, launched)
    land_tick.requeue(repo)
    assert not launched and not _kept(repo)


def test_pending_requests_are_requeued_oldest_first_one_per_tick(repo, monkeypatch):
    _git(repo, "checkout", "-q", "-b", "feat/y")
    land_queue.keep_pending(repo, [])
    time.sleep(0.01)  # Windows time.time() resolution: keep the start stamps apart (else names order feat/x first)
    _git(repo, "checkout", "-q", "feat/x")
    land_queue.keep_pending(repo, [])
    launched = []
    _tick(monkeypatch, launched)
    assert land_tick.requeue(repo) == "relaunched pending feat/y"  # kept earlier, though y sorts after x
    assert len(launched) == 1 and launched[0][-2:] == ["--branch", "feat/y"]
    assert land_tick.requeue(repo) == "relaunched pending feat/x"  # at most one launch per tick
    assert not _kept(repo)


def test_pending_request_file_that_is_unreadable_is_cleaned(repo, monkeypatch):
    land_queue.keep_pending(repo, [])
    path = _kept(repo)[0]
    path.write_text("{oops", encoding="utf-8")
    launched = []
    _tick(monkeypatch, launched)
    assert land_tick.requeue(repo) == "nothing to requeue" and not path.exists() and not launched


def test_not_queued_start_keeps_one_pending_request_and_exits_3(async_repo, monkeypatch, capsys):
    """The real NOT QUEUED path: 30 min of polling, exit 3, and the request durable for land_tick's pass."""
    from test_land_async import NOW, tool  # its importlib-loaded land_async instance
    _, dev = async_repo
    clock = [0.0]
    monkeypatch.setattr(tool._queue(), "full", lambda qdir, lane="": "landing queue full (12/12 tickets)")
    monkeypatch.setattr(tool.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(tool.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    with pytest.raises(SystemExit) as stop:
        tool.start(dev, ["--tests", "auto"], NOW, lambda *a: None)
    assert stop.value.code == 3  # not 0: a caller's background command must not read it as queued
    err = capsys.readouterr().err
    assert "[land-async] NOT QUEUED: feat/x" in err and "after 30 min" in err
    assert "run land_async.py again" not in err and "kept as" in err
    (path,) = _kept(dev)
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["branch"] == "feat/x" and row["ref"] == _git(dev, "rev-parse", "feat/x")
    assert row["args"] == ["--tests", "auto"] and row["cwd"] == str(dev)
    assert not _git(dev, "branch", "--list", "land/*")  # no snapshot was taken for a refused request


@pytest.fixture
def async_repo(tmp_path):  # the shape of test_land_async.repo: main checkout plus a feat/x worktree
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
