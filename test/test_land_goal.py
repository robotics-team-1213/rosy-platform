"""tools/land_goal.py: the landing goal's lead time, longest stall, stop classes and PASS/FAIL."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import land_goal  # noqa: E402
import land_events  # noqa: E402
import land_stats  # noqa: E402

H = 3600.0


def ev(t, event, branch="land/fix/a-20261031120000", pid=1, **kw):
    return {"t": t, "event": event, "branch": branch, "pid": pid, **kw}


def test_lead_time_counts_from_the_topics_first_queue_across_restarts_and_batches():
    rows = [ev(0, "queue"), ev(10, "stop", reason="x"),  # killed and resubmitted: same topic, same clock
            ev(600, "queue", branch="land/fix/a-20261031121000", pid=2),
            ev(3600, "landed", branch="land/fix/a-20261031121000-batch1-k2", pid=2)]
    assert land_goal.lead_times(rows, 0, 2 * H) == [60.0]
    assert land_goal.lead_times(rows, 2 * H, 3 * H) == [], "landed before the window"


def test_longest_stall_is_only_time_with_a_live_ticket_and_main_still():
    rows = [ev(0, "queue"), ev(1 * H, "landed"),
            ev(2 * H, "queue", branch="land/fix/b", pid=2)]  # still live (alive pid) to t1
    moves = [0.5 * H]
    stall = land_goal.longest_stall(moves, land_goal.live(rows, 4 * H, {2}), 0, 4 * H)
    assert stall == 120.0, "2 h..4 h: b waits, main still; 1 h..2 h has no ticket"
    assert land_goal.longest_stall(moves, land_goal.live(rows, 4 * H, set()), 0, 4 * H) == 30.0, \
        "a dead lander without a stop ends at its last event"


def test_stop_classes_and_pass_fail():
    assert [land_goal.stop_class(r) for r in ("land.py exit 3221225786", "merge aborted; resolve", "[size-range] x",
                                              "NEW failure in pkg")] == ["infra", "conflict", "size", "own failure"]
    rows = [ev(0, "queue"), ev(30 * 60, "landed"), ev(100, "tests", run_s=60.0, wait_s=0.0, queued_s=120.0)]
    lines, ok = land_goal.report(rows, [30 * 60], set(), 0, H, 120, 30)
    assert ok and lines[-1].startswith("PASS") and any(line.startswith("run_s min p50 1") for line in lines)
    _, ok = land_goal.report(rows, [], set(), 0, H, 20, 30)
    assert not ok, "p90 30 min against a 20 min goal"


@pytest.fixture
def goal_repo(tmp_path, monkeypatch):
    """A merge prepared years before the real main fast-forward events."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    env = {**os.environ, "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z"}
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "prepared"], env=env, check=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path / ".git" / land_events.EVENTS, 1_793_500_000.0


def test_goal_cli_stall_uses_landing_events_despite_old_commit_dates(goal_repo, monkeypatch, capsys):
    events, start = goal_repo
    rows = [ev(start + i * 1200, "queue", branch=f"fix/{i}", pid=i + 1) for i in range(3)]
    rows += [ev(start + (i + 1) * 1200, "landed", branch=f"fix/{i}", pid=i + 1) for i in range(3)]
    events.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    monkeypatch.setattr(land_stats.time, "time", lambda: start + H + 1)
    assert land_stats.main(["--goal", "--hours", "2"]) == 0
    output = capsys.readouterr().out
    assert "longest stall 20 min (goal <= 30)" in output
    assert "PASS:" in output


def test_goal_cli_defaults_to_sixty_minutes_and_preserves_override(goal_repo, monkeypatch, capsys):
    events, start = goal_repo
    rows = [ev(start, "queue"), ev(start + 90 * 60, "landed")]
    events.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    monkeypatch.setattr(land_stats.time, "time", lambda: start + 2 * H)
    args = ["--goal", "--hours", "2", "--stall", "120"]
    assert land_stats.main(args) == 1
    assert "p90 90 min (goal <= 60)" in capsys.readouterr().out
    assert land_stats.main([*args, "--p90", "120"]) == 0
    assert "p90 90 min (goal <= 120)" in capsys.readouterr().out
