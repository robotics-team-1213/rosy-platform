"""tools/land_bottlenecks.py: daily bottleneck scan and safe remediation."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools" / "remote")]

import land_bottlenecks as lb  # noqa: E402
import memory_history as mh  # noqa: E402


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@t")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_trim_memory_history_keeps_recent_tail_only(tmp_path):
    mem = tmp_path / mh.FILE
    mem.write_text("\n".join(json.dumps({"i": i}) for i in range(10)) + "\n", encoding="utf-8")
    assert lb._trim_memory_history(mem, max_rows=10, keep_rows=4) == 0
    assert lb._trim_memory_history(mem, max_rows=5, keep_rows=4) == 6
    assert [json.loads(line)["i"] for line in mem.read_text(encoding="utf-8").splitlines()] == [6, 7, 8, 9]


def test_memory_summary_flags_slow_and_overhead_invocations(tmp_path):
    now = time.time()
    recent = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 60))
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 200000))
    mem = tmp_path / mh.FILE
    rows = [
        {"key": "old/test.py", "pytest_s": 500, "job_s": 500, "wait_s": 0, "time": old},
        {"key": "pkg/test_slow.py", "host": "ai", "pytest_s": 180, "job_s": 190, "wait_s": 5, "time": recent},
        {"key": "pkg/test_wait.py", "host": "rosy", "pytest_s": 20, "job_s": 90, "wait_s": 70, "time": recent},
    ]
    mem.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    summary = lb._memory_summary(mem, now - 3600)
    assert summary["rows"] == 3
    assert [r["key"] for r in summary["slow_pytest"]] == ["pkg/test_slow.py"]
    assert [r["key"] for r in summary["high_overhead"]] == ["pkg/test_wait.py"]


def test_scan_and_remediate_warm_cache_trim_and_prune(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    (common / mh.FILE).write_text('{"key": "x"}\n' * 12, encoding="utf-8")
    now = time.time()
    monkeypatch.setattr(lb.land_goal, "normalize", lambda *a: ([], []))
    monkeypatch.setattr(lb.land_goal, "report", lambda *a: (["goal ok"], True))
    monkeypatch.setattr(lb.land_stats, "daily", lambda *a: {})
    monkeypatch.setattr(lb.land_gc, "plan", lambda *a: [("remove", "old", None, [])])
    monkeypatch.setattr(lb.land_mainred, "state", lambda *a: {})
    monkeypatch.setattr(lb.worktrees, "scan", lambda *a: (repo, [{"name": f"wt-{i}"} for i in range(15)]))
    pruned = []
    monkeypatch.setattr(lb.worktrees, "prune",
                        lambda *a, **k: pruned.append(k) or (1 if k.get("apply") else 2))
    monkeypatch.setattr(lb, "MAX_MEMORY_ROWS", 10)
    monkeypatch.setattr(lb, "KEEP_MEMORY_ROWS", 5)
    calls, real_run = [], subprocess.run
    monkeypatch.setattr(lb.land_tick, "cleanup", lambda *a: "land_gc removed 1; worktrees removed 0")
    monkeypatch.setattr(lb.subprocess, "run", lambda cmd, **k: (
        calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")) if "--warm" in cmd
        else real_run(cmd, **k))

    report = lb.scan(repo, now=now)
    assert any(f.startswith("cache_cold:") for f in report["findings"])
    assert any(f.startswith("memory_bloat:") for f in report["findings"])
    assert any(f.startswith("worktrees_over_cap:") for f in report["findings"])
    assert any(f.startswith("gc_backlog:") for f in report["findings"])

    actions = lb.remediate(repo, report, warm_limit=8, idle_hours=4.0)
    assert len((common / mh.FILE).read_text(encoding="utf-8").splitlines()) == 5
    assert any("--warm" in c for c in calls)
    assert any("worktrees_cap_prune" in a for a in actions)
    assert any(k.get("apply") and k.get("snapshot") and k.get("idle_hours") == 4.0 for k in pruned)
