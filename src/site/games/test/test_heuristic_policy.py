from games.field import ZERO, Pose2D
from games.game import MatchState, Observation, Phase
from games.policy import HeuristicPolicy


def _obs(ball, robots):
    return Observation(
        t=0.0,
        ball=Pose2D(ball[0], ball[1], 0.0),
        robots={rid: Pose2D(*pose) for rid, pose in robots.items()},
        lost_ball=False,
        lost_robots=frozenset(),
    )


def _play() -> MatchState:
    return MatchState(phase=Phase.PLAY, score={"rosy_01": 0, "rosy_02": 0}, reason="")


def test_policy_turns_toward_the_ball_and_stops_when_the_other_robot_is_close():
    policy = HeuristicPolicy()
    play = _play()
    far = _obs((0.5, 0.0), {"rosy_01": (0.0, 0.0, 0.0), "rosy_02": (0.0, 1.0, 0.0)})
    chase = policy.act(far, play)
    assert chase["rosy_01"].linear > 0
    assert "rosy_02" in chase
    close = _obs((0.5, 0.0), {"rosy_01": (0.0, 0.0, 0.0), "rosy_02": (0.1, 0.0, 0.0)})
    hold = policy.act(close, play)
    assert hold["rosy_01"].linear <= 0


def test_policy_idles_when_phase_is_not_play():
    policy = HeuristicPolicy()
    obs = _obs((0.5, 0.0), {"rosy_01": (0.0, 0.0, 0.0), "rosy_02": (0.0, 1.0, 0.0)})
    state = MatchState(phase=Phase.HOLD, score={"rosy_01": 0, "rosy_02": 0}, reason="lost")
    out = policy.act(obs, state)
    assert out == {} or all(twist == ZERO for twist in out.values())


def test_policy_does_not_hang_on_nonfinite_yaw():
    policy = HeuristicPolicy()
    play = _play()
    obs = _obs(
        (0.5, 0.0),
        {"rosy_01": (0.0, 0.0, float("inf")), "rosy_02": (0.0, 1.0, 0.0)},
    )
    out = policy.act(obs, play)
    assert out["rosy_01"].linear == 0.0 or abs(out["rosy_01"].angular) <= 1.0


def test_policy_clamps_angular_to_its_limit():
    policy = HeuristicPolicy(angular=0.40)
    play = _play()
    obs = _obs((0.0, 0.8), {"rosy_01": (0.0, 0.0, 0.0), "rosy_02": (0.0, 1.0, 0.0)})
    out = policy.act(obs, play)
    assert abs(out["rosy_01"].angular) <= 0.40 + 1e-9
