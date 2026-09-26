from games.game import Phase
from games.host.hold import HoldObserver
from games.host.loop import MatchHost
from games.host.session import run_match

from fake_host import FakePlayerClient


def test_hold_observer_keeps_both_robots_at_zero():
    home, away = FakePlayerClient("rosy_01"), FakePlayerClient("rosy_02")
    host = MatchHost(HoldObserver(home_id="rosy_01", away_id="rosy_02"), (home, away))
    states = run_match(host, ticks=3)
    assert states
    assert all(s.phase is Phase.KICKOFF for s in states)
    assert home.manual == 1 and away.manual == 1
    assert home.teleops == [(0.0, 0.0)] * 3
    assert away.teleops == [(0.0, 0.0)] * 3
    assert home.estops >= 1 and away.estops >= 1


def test_run_match_without_a_tick_limit_stops_on_interrupt_and_still_halts():
    home, away = FakePlayerClient("rosy_01"), FakePlayerClient("rosy_02")
    host = MatchHost(HoldObserver(home_id="rosy_01", away_id="rosy_02"), (home, away))
    n = {"i": 0}
    real = host.tick

    def tick():
        n["i"] += 1
        if n["i"] > 3:
            raise KeyboardInterrupt
        return real()

    host.tick = tick  # type: ignore[method-assign]
    states = run_match(host, ticks=None, period_s=0.0)
    assert len(states) == 3
    assert home.estops >= 1 and away.estops >= 1


def test_run_match_stops_when_halt_check_fires():
    home, away = FakePlayerClient("rosy_01"), FakePlayerClient("rosy_02")
    host = MatchHost(HoldObserver(home_id="rosy_01", away_id="rosy_02"), (home, away))
    n = {"i": 0}

    def halt_check() -> bool:
        n["i"] += 1
        return n["i"] >= 2

    states = run_match(host, ticks=10, period_s=0.0, halt_check=halt_check)
    assert len(states) == 2
    assert home.estops >= 1 and away.estops >= 1


def test_run_match_halts_when_observe_raises():
    home, away = FakePlayerClient("rosy_01"), FakePlayerClient("rosy_02")

    class Boom:
        def observe(self):
            raise RuntimeError("camera gone")

    host = MatchHost(Boom(), (home, away))
    try:
        run_match(host, ticks=1)
        raise AssertionError("observe failure must surface")
    except RuntimeError as exc:
        assert "camera gone" in str(exc)
    assert home.estops >= 1 and away.estops >= 1
    assert home.manual == 1
