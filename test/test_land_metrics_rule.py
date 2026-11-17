"""D-889 addendum 36: a commit that changes the landing pipeline cites its numbers and what it removes.

``Metrics: before=...`` for any commit touching tools/land*.py or tools/land_*/; ``Removes: ...`` as well when it adds
a timer/trigger constant (*_S, *_EVERY*, *_POLLS) or a call that builds a rollup. Enforced by tools/harness/size_range.py.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "harness"))

import land_metrics_rule  # noqa: E402
from land_metrics_rule import violations  # noqa: E402


def test_the_rule_on_made_up_commits():
    pipeline, other = ["tools/land_tick.py"], ["tools/other.py"]
    assert violations("fix", other, "+X_S = 1") == []
    assert violations("fix", pipeline, "+x = 1") == ["touches the landing pipeline without a 'Metrics: before=...' line"]
    assert violations("fix\n\nMetrics: before=rollups 3", pipeline, "+x = 1") == []
    assert violations("fix\n\nMetrics: before=1", pipeline, "+GATHER_S = 90.0") != []
    assert violations("fix\n\nMetrics: before=1", pipeline, "+RETRY_POLLS = 4") != []
    assert violations("fix\n\nMetrics: before=1", pipeline, "+EVERY_X = 4") == []  # not a trigger name
    assert violations("fix\n\nMetrics: before=1", pipeline, "+    land.land_watchdog.rollup(common)") != []
    assert violations("fix\n\nMetrics: before=1\nRemoves: gather", pipeline, "+GATHER_S = 90.0") == []
    assert violations("fix\n\nMetrics: before=1", ["tools/land_x/a.py"], "-GATHER_S = 90.0") == []  # deletion is fine


def test_size_range_enforces_the_rule_on_new_non_merge_commits(tmp_path, monkeypatch, capsys):
    """tools/harness/size_range.py runs in land.py's precheck and turn: old-dated and merge commits pass."""
    import shutil
    import subprocess

    import size_range

    if shutil.which("git") is None:
        pytest.skip("git is required")
    monkeypatch.chdir(tmp_path)
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "t")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "t@x")
    old = (land_metrics_rule.RULE_SINCE - dt.timedelta(days=1)).isoformat()
    new = (land_metrics_rule.RULE_SINCE + dt.timedelta(days=1)).isoformat()

    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()

    def commit(name, message, when, extra=()):
        monkeypatch.setenv("GIT_COMMITTER_DATE", when)
        monkeypatch.setenv("GIT_AUTHOR_DATE", when)
        (tmp_path / "tools").mkdir(exist_ok=True)
        (tmp_path / "tools" / name).write_text(message, encoding="utf-8")
        for extra_name, text in extra:
            (tmp_path / "tools" / extra_name).write_text(text, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "--no-verify", "-m", message)
        return git("rev-parse", "HEAD")

    git("init", "-q", "-b", "main")
    base = commit("land_a.py", "base", old)
    git("checkout", "-q", "-b", "side")
    older = commit("land_b.py", "old work without the line", old)
    git("checkout", "-q", "main")
    git("checkout", "-q", "-b", "work", base)
    bad = commit("land_c.py", "new work without the line", new)
    good = commit("land_d.py", "new work"+chr(10)*2+"Metrics: before=landed 1/h", new)
    ok_msg = "new work" + chr(10) * 2 + "Metrics: before=landed 1/h"
    doc = commit("land_e.py", ok_msg, new, [("AGENTS.md", "| `land_rollup.py` | doc line |" + chr(10))])
    code = commit("land_f.py", ok_msg, new, [("land_g.py", "x.rollup(common)" + chr(10))])
    git("merge", "-q", "--no-ff", "--no-verify", "-m", "merge without the line", "side")
    merged = git("rev-parse", "HEAD")
    assert size_range.metrics_problems(older) == []  # committed before RULE_SINCE
    assert size_range.metrics_problems(bad) == ["touches the landing pipeline without a 'Metrics: before=...' line"]
    assert size_range.metrics_problems(good) == []
    assert size_range.metrics_problems(doc) == []  # a doc line naming land_rollup.py is no trigger
    assert size_range.metrics_problems(code) == ["adds a timer or rollup trigger without a 'Removes: ...' line"]
    assert size_range.metrics_problems(merged) == []  # a merge is skipped
    assert size_range.main([base, bad]) == 1
    assert bad[:7] in capsys.readouterr().err
    assert size_range.main([base, good]) == 1  # bad is in the range
