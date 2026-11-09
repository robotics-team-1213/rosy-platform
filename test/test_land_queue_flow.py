"""D-889 addendum 32 (2026-11-09 bottleneck report 4-8): API pin conflicts, mixed branches, the unattended rollup,
the watchdog's rollup schedule and the stage numbers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land_merge  # noqa: E402
import land_precheck  # noqa: E402
import land_stats  # noqa: E402
import land_watchdog  # noqa: E402

HEAD = b"# Ref\n\n**Version:** v1.%d\n\n"
OLD = b"### v1.10 old\n\n- old fact\n\n## 1. Rules\n\nbody\n"


def section(n: int) -> bytes:
    return b"### v1.%d new %d\n\n- fact %d\n\n" % (n, n, n)


def ref(pin: int, *sections: int) -> bytes:
    return HEAD % pin + b"".join(section(n) for n in sections) + OLD


def test_both_sides_bumping_the_api_version_merge_with_the_higher_pin_and_newest_section_first():
    data = land_merge.api_version(ref(10), ref(11, 11), ref(12, 12))
    assert data == ref(12, 12, 11), data.decode()
    assert land_merge.api_version(ref(10), ref(12, 12), ref(11, 11)) == ref(12, 12, 11)


def test_contract_version_pins_take_the_higher_version():
    pin = b'CONTRACT = "ROSY-API-REF-001 v1.%d"\n'
    assert land_merge.api_version(pin % 10, pin % 12, pin % 11) == pin % 12
    assert land_merge.resolver("middleware/core/api/core_api_web/api/contract_version.py") == "api"
    assert land_merge.resolver(land_merge.API_REF) == "api"


@pytest.mark.parametrize("ours,theirs", [
    (ref(11, 11), ref(11, 11)),  # one number taken twice, without api_reserve: a person renumbers
    (ref(11, 11), ref(12, 12).replace(b"### v1.10 old", b"### v1.10 renamed")),  # an existing line changed
    (ref(11, 12), ref(12, 12)),  # a new section under a number the other side has
])
def test_api_conflicts_a_person_must_decide_stay_manual(ours, theirs):
    assert land_merge.api_version(ref(10), ours, theirs) is None


def test_mixed_branches_split_gate_and_safety_from_product_paths_with_docs_and_tests_neutral():
    paths = ["tools/land_async.py", "tools/remote/remote_pytest.py", "operations/fleet/x.py", "docs/logs.md",
             "test/test_land.py", "operations/fleet/test/test_x.py", "AGENTS.md", "middleware/core/safe.py"]
    held, product = land_precheck.mixed(paths, lambda p: p == "middleware/core/safe.py")
    assert held == ["tools/land_async.py", "tools/remote/remote_pytest.py", "middleware/core/safe.py"]
    assert product == ["operations/fleet/x.py"]


def fake_land(paths):
    class Stop(Exception):
        pass
    calls = []
    return calls, SimpleNamespace(
        Stop=Stop, HARNESS="absent.py", out=lambda *a: "main-sha", lines=lambda *a: paths,
        safety_review=lambda *a: calls.append("safety"), size_check=lambda *a: calls.append("size"),
        secret_scan=lambda *a: calls.append("secret"), git=lambda *a, **k: SimpleNamespace(returncode=0))


def test_precheck_refuses_a_mixed_branch_unless_the_users_words_are_given(tmp_path):
    calls, land = fake_land(["tools/land.py", "operations/fleet/x.py"])
    with pytest.raises(land.Stop, match="--mixed"):
        land_precheck.precheck(land, tmp_path, "python")
    assert calls == []  # before any other gate
    land_precheck.precheck(land, tmp_path, "python", "user: one change, 2026-11-09")
    assert calls == ["safety", "size", "secret"]
    calls, land = fake_land(["tools/land.py", "docs/adr/D-889.md", "test/test_land.py"])
    land_precheck.precheck(land, tmp_path, "python")
    assert calls == ["safety", "size", "secret"]


def test_land_async_hands_the_mixed_words_to_the_precheck(monkeypatch, tmp_path):
    import land_async
    seen = []
    monkeypatch.setattr(land_async.subprocess, "call", lambda argv, **k: seen.append(argv) or 1)
    assert land_async.main(["--tests", "auto", "--mixed", "user said so"]) == 1
    assert seen[0][-3:] == ["--precheck", "--mixed", "user said so"]


def test_the_unattended_rollup_takes_affected_tier_members_only(monkeypatch):
    import land_rollup
    monkeypatch.setattr(land_rollup, "tier", lambda repo, branch: {"a": "affected", "f": "full"}.get(branch))
    assert [land_rollup.affected(None, b) for b in ("a", "f", "safety")] == ["affected", None, None]


def test_only_the_turn_holder_starts_the_rollup_once_per_half_hour(tmp_path, monkeypatch):
    common = tmp_path / ".git"
    common.mkdir()
    ticket = common / "t.json"
    ticket.write_text("{}", encoding="utf-8")
    events = SimpleNamespace(_where={"path": common / "rosy-land-events.jsonl"})
    owner = {"turn": False}
    queue = SimpleNamespace(_held=[ticket], owns_turn=lambda t: owner["turn"])
    now = [time.time()]
    assert land_watchdog.rollup_due(events, queue, now=lambda: now[0]) is None  # not in its turn
    owner["turn"] = True
    assert land_watchdog.rollup_due(events, queue, now=lambda: now[0]) == common  # first one: claims the stamp
    assert land_watchdog.rollup_due(events, queue, now=lambda: now[0]) is None  # just claimed
    stamp = common / land_watchdog.STAMP
    os.utime(stamp, (now[0] - 10, now[0] - 10))
    assert land_watchdog.rollup_due(events, queue, now=lambda: now[0]) is None  # ran 10 s ago
    os.utime(stamp, (now[0] - land_watchdog.ROLLUP_EVERY_S - 1,) * 2)
    assert land_watchdog.rollup_due(events, queue, now=lambda: now[0]) == common
    started = []
    land_watchdog.rollup(common, popen=lambda argv, **kw: started.append((argv, kw["cwd"])))
    (argv, cwd), = started
    assert argv[-3:] == [str(tmp_path / "tools" / "land_rollup.py"), "apply", "--auto"] and cwd == tmp_path


def test_land_stats_shows_the_stage_times_and_how_far_behind_main_a_change_was_queued():
    t = 1_762_650_000.0
    rows = [{"t": t, "event": "async", "behind": 7}, {"t": t + 1, "event": "async", "behind": 1},
            {"t": t + 2, "event": "prepared", "tier": "affected", "seconds": 600},
            {"t": t + 3, "event": "prepared", "tier": "full", "seconds": 3600},
            {"t": t + 4, "event": "merged", "round": 1, "seconds": 30, "resolved": []}]
    (day,) = land_stats.daily(rows).values()
    assert (day["pretest_p50"], day["full_p50"], day["merge_p50"]) == (10, 60, .5)
    assert (day["behind_p50"], day["behind_p90"]) == (1, 7)
    assert json.dumps(day)


def test_land_async_also_takes_the_mixed_words_in_equals_form(monkeypatch):
    import land_async
    seen = []
    monkeypatch.setattr(land_async.subprocess, "call", lambda argv, **k: seen.append(argv) or 1)
    assert land_async.main(["--mixed=user said so", "--tests", "auto"]) == 1
    assert seen[0][-2:] == ["--precheck", "--mixed=user said so"]
