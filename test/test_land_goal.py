"""tools/land_goal.py: the landing goal's lead time, longest stall, stop classes and PASS/FAIL."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import land_goal  # noqa: E402

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
