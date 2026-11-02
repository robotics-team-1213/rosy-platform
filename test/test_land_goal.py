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


def test_rollup_closes_member_retry_history_but_preserves_later_work_and_deduplicates():
    a, b, carrier = "land/fix/a-20261101000000", "land/fix/b-20261101000000", "land/fix/land-rollup-x"
    members = [{"branch": a, "ticket": "a2", "candidate": "a" * 40},
               {"branch": b, "ticket": "b1", "candidate": "b" * 40}]
    rows = [ev(0, "queue", branch=a, ticket="a1"), ev(10, "stop", branch=a),
            ev(60, "queue", branch=a, ticket="a2"), ev(120, "queue", branch=b, ticket="b1"),
            ev(180, "queue", branch=carrier, ticket="a2"),
            ev(240, "landed", branch=carrier, members=members),
            ev(300, "queue", branch=a, ticket="a3"),
            ev(330, "landed", branch=carrier, members=members),
            ev(360, "landed", branch=a)]
    assert land_goal.lead_times(rows, 0, 400) == [4, 2, 1]


def test_failed_rollup_does_not_close_member_or_create_a_sample():
    rows = [ev(0, "queue", ticket="a"), ev(60, "stop", members=[{"branch": "land/fix/a", "ticket": "a"}]),
            ev(120, "landed")]
    assert land_goal.lead_times(rows, 0, 200) == [2]


def test_legacy_batch_completion_closes_carried_members_before_their_later_exit():
    a, b = "land/fix/a-20261101000000", "land/fix/b-20261101000000"
    rows = [ev(0, "queue", branch=a, ticket="a"), ev(60, "queue", branch=b, ticket="b"),
            ev(120, "train", branch=a, branches=[a, b], result="landed"),
            ev(121, "landed", branch=a), ev(180, "queue", branch=b, ticket="b2"),
            ev(181, "landed", branch=b, pid=1), ev(240, "landed", branch=b, pid=2)]
    # The old member exit must not consume b2, even if the new queue appeared first.
    rows[1]["pid"], rows[4]["pid"] = 1, 2
    assert land_goal.lead_times(rows, 0, 300) == [2, 1, 1]


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


def test_goal_cli_recovers_historical_rollup_members_without_rewriting_events(goal_repo, monkeypatch, capsys):
    events, start = goal_repo
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    a, b, carrier = "land/fix/a-20261101000000", "land/fix/b-20261101000000", "land/fix/land-rollup-x"
    rows = [ev(start, "queue", branch=a, ticket="old-a"), ev(start + 60, "stop", branch=a),
            ev(start + 120, "queue", branch=a, ticket="a"), ev(start + 180, "queue", branch=b, ticket="b"),
            ev(start + 200, "isolation", branch=a, kind="prepare", candidate=sha),
            ev(start + 201, "isolation", branch=b, kind="prepare", candidate=sha),
            ev(start + 240, "queue", branch=carrier), ev(start + 300, "landed", branch=carrier, sha=sha),
            ev(start + 360, "queue", branch=a, ticket="next"), ev(start + 420, "landed", branch=a)]
    raw = "\n".join(json.dumps(r) for r in rows)
    events.write_text(raw, encoding="utf-8")
    holder = events.parent / "rosy-land-wt"
    holder.mkdir()
    sidecar = holder / (carrier.replace("/", "-") + ".members")
    sidecar.write_text(json.dumps([{"branch": a}, {"branch": b}]), encoding="utf-8")
    monkeypatch.setattr(land_stats.time, "time", lambda: start + 600)
    assert land_stats.main(["--goal", "--hours", "1"]) == 0
    assert "landed 3, lead time p50 2 / p90 5 min" in capsys.readouterr().out
    assert events.read_text(encoding="utf-8") == raw
    normalized, warnings = land_goal.normalize(rows, events.parent)
    assert not warnings
    assert land_goal.lead_times(normalized, start, start + 290) == []
    assert land_goal.lead_times(normalized, start, start + 600) == [5, 2, 1]
    assert len([r for r in normalized if r["event"] == "landed"]) == 2
    # A non-ancestor / missing candidate never closes a member by guessing its name.
    rows[4]["candidate"] = "f" * 40
    normalized, warnings = land_goal.normalize(rows, events.parent)
    assert warnings and land_goal.lead_times(normalized, start, start + 600) != [5, 2, 1]
