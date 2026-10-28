"""tools/doctor.py against a throwaway git repo: no network, no lab host, nothing written outside tmp."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import doctor  # noqa: E402

HOOK = "#!/usr/bin/env bash\necho gate\n"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    repo = tmp_path / "main"
    (repo / "tools/hooks").mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.name", "t"), ("user.email", "t@t"), ("core.autocrlf", "false")):
        git(repo, "config", key, value)
    (repo / "tools/hooks/pre-push").write_text(HOOK, encoding="utf-8")
    git(repo, "add", "tools/hooks/pre-push")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    (repo / ".git/hooks").mkdir(exist_ok=True)
    (repo / ".git/hooks/pre-push").write_bytes(HOOK.replace("\n", "\r\n").encode())  # CR is ignored
    (repo / ".git/FETCH_HEAD").write_text("", encoding="utf-8")  # fetched just now
    monkeypatch.delenv("CI", raising=False)
    return repo


def lines(repo: Path, **kwargs) -> tuple[int, str]:
    out: list[str] = []
    code = doctor.run(repo, out=out.append, **kwargs)
    return code, "\n".join(out)


def test_clean_repo_is_all_ok(repo):
    code, text = lines(repo)
    assert code == 0, text
    assert "FAIL" not in text and "WARN" not in text, text
    assert "OK   pre-push: installed hook matches HEAD" in text
    assert "rosy.publishOnly: unset" in text
    assert "worktrees: 1 of 15 slots" in text
    assert "main: 0 ahead, 0 behind origin/main" in text
    assert "land queue: 0 ticket(s), holder none" in text


def test_hook_drift_or_absence_fails_with_the_install_command(repo):
    hook = repo / ".git/hooks/pre-push"
    hook.write_text(HOOK + "echo extra\n", encoding="utf-8")
    code, text = lines(repo)
    assert code == 1 and "FAIL pre-push: installed hook differs" in text
    assert "fix: bash tools/hooks/install.sh" in text
    hook.unlink()
    code, text = lines(repo)
    assert code == 1 and "FAIL pre-push: not installed" in text


def test_publish_only_is_reported(repo):
    git(repo, "config", "rosy.publishOnly", "true")
    assert "rosy.publishOnly: true" in lines(repo)[1]


def test_main_behind_origin_and_old_fetch_warn(repo):
    upstream = git(repo, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "b")
    git(repo, "update-ref", "refs/remotes/origin/main", upstream)  # origin one commit past local main
    code, text = lines(repo)
    assert code == 0, "behind is a warning, not a failure"
    assert "WARN main: 0 ahead, 1 behind origin/main" in text and "merge --ff-only origin/main" in text
    old = time.time() - 24 * 3600
    for mark in (repo / ".git/FETCH_HEAD", repo / ".git/logs/refs/remotes/origin/main"):
        if mark.exists():
            os.utime(mark, (old, old))
    assert "fix: git fetch origin" in lines(repo)[1]


def test_over_slot_rule_warns_with_the_prune_command(repo, monkeypatch):
    monkeypatch.setattr(doctor, "SLOTS", 1)
    git(repo, "worktree", "add", "-q", "-b", "feat/x", str(repo / ".worktrees/x"))
    code, text = lines(repo)
    assert code == 0 and "WARN worktrees: 2 of 1 slots (main included)" in text


def test_land_queue_counts_holder_and_dead_tickets_without_removing_them(repo):
    qdir = repo / ".git/rosy-land-queue"
    qdir.mkdir()
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    me = socket.gethostname()
    (qdir / "00000000000000000001-1.json").write_text(json.dumps(
        {"pid": os.getpid(), "host": me, "branch": "fix/alive"}), encoding="utf-8")
    dead = qdir / "00000000000000000002-2.json"
    dead.write_text(json.dumps({"pid": gone.pid, "host": me, "branch": "fix/dead"}), encoding="utf-8")
    code, text = lines(repo)
    assert code == 0
    assert "land queue: 2 ticket(s), holder fix/alive, 1 dead or stale" in text
    assert "fix/dead: pid" in text
    assert dead.exists(), "doctor is read-only"


def test_land_queue_warns_on_a_run_that_keeps_preparing_or_went_quiet(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_LAND_TMP", str(tmp_path / "land-tmp"))
    qdir = repo / ".git/rosy-land-queue"
    qdir.mkdir()
    me, start = socket.gethostname(), time.time() - 3600
    ticket = qdir / "00000000000000000001-1.json"
    ticket.write_text(json.dumps({"pid": os.getpid(), "host": me, "branch": "fix/loop", "start": start,
                                  "status": "pending"}), encoding="utf-8")
    events = [{"t": start - 60, "event": "prepared", "pid": os.getpid()}]  # an earlier run with the same pid
    events += [{"t": start + 60 * n, "event": "prepared", "pid": os.getpid()} for n in (1, 2, 3)]
    (repo / ".git/rosy-land-events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    code, text = lines(repo)
    assert code == 0
    assert f"WARN land queue: fix/loop (pid {os.getpid()}, pending) prepared 3 times in this run" in text
    assert "no activity" not in text

    os.utime(ticket, (time.time() - 40 * 60,) * 2)
    (repo / ".git/rosy-land-events.jsonl").write_text("", encoding="utf-8")
    code, text = lines(repo)
    assert "shows no activity for 40 min" in text and "prepared" not in text
    logs = tmp_path / "land-tmp/fix-loop"
    logs.mkdir(parents=True)
    (logs / "run-pre-1.txt").write_text("streaming\n", encoding="utf-8")  # a remote log still growing
    assert "no activity" not in lines(repo)[1]


def test_hosts_reads_report_and_disk_low_over_ssh(repo, monkeypatch):
    monkeypatch.setattr(doctor.lab_hosts, "test_hosts", lambda: ["pc-a", "pc-b", "pc-c"])
    replies = {"pc-a": (0, '{"free_after_GiB": 88.5}\nROSY-DISK-LOW=0\n'),
               "pc-b": (0, '{"free_after_GiB": 12.0}\nROSY-DISK-LOW=1\n'),
               "pc-c": (255, "")}

    real_run = subprocess.run

    def fake_run(argv, **kw):
        if argv[0] != "ssh":
            return real_run(argv, **kw)
        code, out = replies[argv[-2]]
        return subprocess.CompletedProcess(argv, code, out, "")

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)
    code, text = lines(repo, hosts=True)
    assert code == 0, text
    assert "OK   host pc-a: 88.5 GiB free at last maintenance, disk-low absent" in text
    assert "WARN host pc-b: 12.0 GiB free at last maintenance, disk-low present" in text
    assert "WARN host pc-c: unreachable over ssh" in text
    monkeypatch.setattr(doctor.subprocess, "run", real_run)
    assert "host pc" not in lines(repo)[1], "--hosts is off by default"


def test_capacity_warns_on_a_refusal_the_hosts_raw_numbers_do_not_explain(monkeypatch):
    """2026-10-27: 3 GB locks for 0.3 GB jobs showed the model PC (20 GB available) as -5.2 GB free."""
    monkeypatch.setattr(doctor.remote_pytest, "SITES", set())
    base = {"nproc": 24, "load1": 4.0, "total_gb": 30.0, "pytest": True, "sim": True, "busy": False,
            "lock_cores": 4, "site": False, "disk_free_gb": 99.0, "disk_use": 78}
    probes = {"booked": {**base, "avail_gb": 20.0, "lock_gb": 35},  # reservations only
              "full": {**base, "avail_gb": 2.0, "lock_gb": 6},  # really out of memory
              "free": {**base, "avail_gb": 20.0, "lock_gb": 6}, "gone": None}
    found = doctor.check_capacity(list(probes), probe=probes.get)
    levels = {text.split(":")[0].split()[-1]: level for level, text, _ in found}
    assert levels == {"booked": "WARN", "full": "OK", "free": "OK", "gone": "WARN"}
    assert "refused by bookkeeping" in found[0][1] and "locks 35 GB" in found[0][1]
    assert "no probe answer" in found[3][1]
