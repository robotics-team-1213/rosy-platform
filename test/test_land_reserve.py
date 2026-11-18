"""tools/land.py: a full queue is refused at once, before any gate (the reservation of land_queue.reserve)."""

from __future__ import annotations

import pytest
from test_land import commit, land, repos  # noqa: F401  (the fixture)


def test_a_full_queue_is_refused_before_any_gate_and_the_place_is_released(repos, monkeypatch, capsys):
    """11-18: 635 of 696 stops were "queue full" found only after safety, size, merge, lint and quick."""
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    marks, why = [], "landing queue full (12/12 tickets): combine related branches into one landing or retry later"

    def reserve(qdir, branch, lane=None):
        raise land.land_queue.QueueError(why)

    monkeypatch.setattr(land.land_queue, "reserve", reserve, raising=False)
    monkeypatch.setattr(land.land_queue, "unreserve", marks.append, raising=False)
    for gate in ("safety_review", "size_check", "admit"):
        monkeypatch.setattr(land, gate, lambda *a, **k: pytest.fail("a gate ran before the cap check"))
    assert land.main(["--tests", "auto"]) == 1
    assert "[land] STOP: landing queue full (" in capsys.readouterr().err
    monkeypatch.setattr(land.land_queue, "reserve", lambda qdir, branch, lane=None: "marker", raising=False)
    monkeypatch.setattr(land, "safety_review", lambda *a, **k: (_ for _ in ()).throw(land.Stop("stop here")))
    assert land.main(["--tests", "auto"]) == 1
    assert marks == ["marker"], "a reserved place is released when the landing ends"


def test_the_room_is_released_once_the_ticket_exists(repos, monkeypatch):
    """The ticket holds the room; a marker kept past enter() would count the cap twice for every other landing."""
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    monkeypatch.setattr(land.land_queue, "reserve", lambda qdir, branch, lane=None: "marker", raising=False)
    monkeypatch.setattr(land.land_queue, "unreserve", lambda marker: land._reserved.remove(marker), raising=False)

    def run_tests(wt_, args, invocations, logdir, round_no):
        assert land._reserved == [], "the marker must be released at the ticket, not at process exit"
        return []

    monkeypatch.setattr(land, "run_tests", run_tests)
    assert land.main(["--tests", "none"]) == 0
