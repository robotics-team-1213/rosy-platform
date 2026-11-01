"""land_queue's urgent ticket (D-889 addendum 5): one at a time, ahead of ordinary waiting tickets, never a turn."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land_queue  # noqa: E402


def _ticket(qdir, branch, status, urgent=""):
    path = land_queue.take(qdir, branch, "", status, urgent)
    return path


def _names(rows):
    return [r["branch"] for r in rows]


def test_an_urgent_ticket_passes_ordinary_waiting_tickets_but_not_a_turn(tmp_path):
    turn = _ticket(tmp_path, "a-turn", "turn")
    waiting = _ticket(tmp_path, "b-waiting", "waiting")
    urgent = _ticket(tmp_path, "c-urgent", "waiting", urgent="user: hotfix for the field robot")
    assert _names(land_queue.blockers(tmp_path, urgent)) == ["a-turn"]  # the turn finishes, b is passed
    assert _names(land_queue.blockers(tmp_path, waiting)) == ["a-turn", "c-urgent"]  # b waits for c
    turn.unlink()
    assert land_queue.blockers(tmp_path, urgent) == []


def test_a_preparing_urgent_ticket_holds_no_one_until_it_waits(tmp_path):
    waiting = _ticket(tmp_path, "b-waiting", "waiting")
    _ticket(tmp_path, "c-urgent", "preparing", urgent="user: incident")
    assert land_queue.blockers(tmp_path, waiting) == []


def test_only_one_urgent_ticket_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setattr(land_queue, "queue_dir", lambda wt: tmp_path)
    monkeypatch.setattr(land_queue.land_events, "emit", lambda *a, **k: None)
    _ticket(tmp_path, "c-urgent", "waiting", urgent="user: first")
    with pytest.raises(land_queue.QueueError, match="one at a time"):
        land_queue.enter(tmp_path, "d-urgent", "preparing", urgent="user: second")
    qdir, ticket = land_queue.enter(tmp_path, "e-plain", "preparing")  # an ordinary landing still queues
    assert ticket.exists()
    land_queue.leave()
