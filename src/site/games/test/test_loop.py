from games.field import Pose2D
from games.game import Observation, Phase
from games.host import MatchHost

from fake_host import FakeObserver, FakePlayerClient


def _obs(
    *,
    ball=(0.0, 0.0),
    r1=(-0.4, 0.0, 0.0),
    r2=(0.4, 0.0, 3.14),
    lost_ball=False,
    robots=None,
):
    if robots is None:
        robots = {"rosy_01": Pose2D(*r1), "rosy_02": Pose2D(*r2)}
    return Observation(
        t=0.0,
        ball=None if ball is None else Pose2D(ball[0], ball[1], 0.0),
        robots=robots,
        lost_ball=lost_ball,
        lost_robots=frozenset(),
    )


def _clients(*, fail=None):
    home = FakePlayerClient("rosy_01", fail_teleop=fail == "rosy_01")
    away = FakePlayerClient("rosy_02", fail_teleop=fail == "rosy_02")
    return home, away


def test_arm_puts_both_robots_in_manual_before_ticks():
    home, away = _clients()
    host = MatchHost(FakeObserver(_obs()), (home, away))
    host.arm()
    assert home.manual == 1 and away.manual == 1
    assert home.estops == 0 and away.estops == 0
    assert home.limits == [] and away.limits == []


def test_observe_only_skips_arm_and_teleop():
    home, away = _clients()
    host = MatchHost(FakeObserver(_obs()), (home, away), observe_only=True)
    host.reset()
    host.tick()
    assert home.manual == 0 and away.manual == 0
    assert home.teleops == [] and away.teleops == []


def test_drive_ids_arm_only_the_named_robot():
    home, away = _clients()
    host = MatchHost(
        FakeObserver(_obs()),
        (home, away),
        drive_ids=frozenset({"rosy_01"}),
        max_linear=0.08,
        max_angular=0.40,
    )
    host.arm()
    assert home.manual == 1 and away.manual == 0
    assert home.limits == [(0.08, 0.40)]
    assert away.limits == []


def test_arm_puts_safety_limits_after_manual():
    home, away = _clients()
    host = MatchHost(
        FakeObserver(_obs()),
        (home, away),
        max_linear=0.08,
        max_angular=0.40,
    )
    host.arm()
    assert home.manual == 1 and away.manual == 1
    assert home.limits == [(0.08, 0.40)]
    assert away.limits == [(0.08, 0.40)]


def test_arm_failure_estops_both_robots():
    home = FakePlayerClient("rosy_01", fail_manual=True)
    away = FakePlayerClient("rosy_02")
    host = MatchHost(FakeObserver(_obs()), (home, away))
    try:
        host.arm()
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected set_manual to fail")
    assert away.estops == 1


def test_kickoff_not_ready_teleops_zero_to_both_robots():
    home, away = _clients()
    observer = FakeObserver(_obs(ball=None, lost_ball=True))
    host = MatchHost(observer, (home, away))
    host.reset()
    assert home.manual == 1 and away.manual == 1
    state = host.tick()
    assert state.phase is Phase.KICKOFF
    assert home.teleops == [(0.0, 0.0)]
    assert away.teleops == [(0.0, 0.0)]
    assert home.estops == 0 and away.estops == 0


def test_in_play_chase_sends_positive_linear():
    home, away = _clients()
    observer = FakeObserver(
        [
            _obs(ball=(0.0, 0.0)),
            _obs(ball=(0.2, 0.0), r1=(-0.3, 0.0, 0.0)),
        ]
    )
    host = MatchHost(observer, (home, away))
    host.reset()
    first = host.tick()
    assert first.phase is Phase.PLAY
    home.teleops.clear()
    away.teleops.clear()
    second = host.tick()
    assert second.phase is Phase.PLAY
    sent = home.teleops + away.teleops
    assert sent
    assert any(linear > 0.0 for linear, _ in sent)


def test_observe_omitting_one_robot_holds_and_teleops_zero():
    home, away = _clients()
    missing = Observation(
        t=0.0,
        ball=Pose2D(0.0, 0.0, 0.0),
        robots={"rosy_01": Pose2D(-0.4, 0.0, 0.0)},
        lost_ball=False,
        lost_robots=frozenset(),
    )
    observer = FakeObserver([_obs(), missing])
    host = MatchHost(observer, (home, away))
    host.reset()
    host.tick()
    home.teleops.clear()
    away.teleops.clear()
    state = host.tick()
    assert state.phase is Phase.HOLD
    assert home.teleops == [(0.0, 0.0)]
    assert away.teleops == [(0.0, 0.0)]


def test_teleop_failure_estops_both_clients():
    home, away = _clients(fail="rosy_01")
    observer = FakeObserver(_obs())
    host = MatchHost(observer, (home, away))
    host.reset()
    host.tick()
    assert home.estops >= 1
    assert away.estops >= 1


def test_estop_all_still_stops_the_second_client_when_the_first_raises():
    home = FakePlayerClient("rosy_01", fail_estop=True)
    away = FakePlayerClient("rosy_02")
    host = MatchHost(FakeObserver(_obs()), (home, away))
    try:
        host._estop_all()
    except Exception:
        pass
    assert home.estops == 1
    assert away.estops == 1
