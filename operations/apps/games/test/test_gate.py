from games.field import ZERO, Field, Pose2D, Twist
from games.game import Observation, Phase
from games.game.gate import gate
from games.game.state import MatchState


def test_gate_zeros_when_not_in_play_and_clips_ramming():
    field = Field()
    obs = Observation(
        t=0.0,
        ball=Pose2D(0.5, 0.0, 0.0),
        robots={
            "rosy_01": Pose2D(0.0, 0.0, 0.0),
            "rosy_02": Pose2D(0.1, 0.0, 0.0),
        },
        lost_ball=False,
        lost_robots=frozenset(),
    )
    hold = MatchState(phase=Phase.HOLD, score={"rosy_01": 0, "rosy_02": 0}, reason="lost")
    out = gate({"rosy_01": Twist(0.08, 0.0)}, obs, hold, field)
    assert out.twists["rosy_01"] == ZERO
    play = MatchState(phase=Phase.PLAY, score=hold.score, reason="")
    ram = gate({"rosy_01": Twist(0.08, 0.0), "rosy_02": Twist(0.08, 0.0)}, obs, play, field)
    assert ram.twists["rosy_01"].linear <= 0.0
    assert ram.twists["rosy_02"].linear <= 0.0


def test_gate_zeros_nan_twist_in_play_when_robots_are_apart():
    field = Field()
    obs = Observation(
        t=0.0,
        ball=Pose2D(0.0, 0.0, 0.0),
        robots={
            "rosy_01": Pose2D(-0.4, 0.0, 0.0),
            "rosy_02": Pose2D(0.4, 0.0, 0.0),
        },
        lost_ball=False,
        lost_robots=frozenset(),
    )
    play = MatchState(phase=Phase.PLAY, score={"rosy_01": 0, "rosy_02": 0}, reason="")
    out = gate({"rosy_01": Twist(float("nan"), 0.0)}, obs, play, field)
    assert out.twists["rosy_01"] == ZERO


def test_gate_clamps_linear_and_angular_to_match_limits():
    field = Field()
    obs = Observation(
        t=0.0,
        ball=Pose2D(0.0, 0.0, 0.0),
        robots={
            "rosy_01": Pose2D(-0.4, 0.0, 0.0),
            "rosy_02": Pose2D(0.4, 0.0, 0.0),
        },
        lost_ball=False,
        lost_robots=frozenset(),
    )
    play = MatchState(phase=Phase.PLAY, score={"rosy_01": 0, "rosy_02": 0}, reason="")
    out = gate(
        {"rosy_01": Twist(0.5, 2.0)},
        obs,
        play,
        field,
        max_linear=0.08,
        max_angular=0.40,
    )
    assert abs(out.twists["rosy_01"].linear) <= 0.08
    assert abs(out.twists["rosy_01"].angular) <= 0.40
