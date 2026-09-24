"""D-112: stair 1 visibility is a host report, not FIELD GO."""

from pathlib import Path

from games.field import Pose2D
from games.game import Observation
from games.host.robots import load_match
from games.host.visibility import format_visibility, stair1_expect, stair1_visibility

PKG = Path(__file__).resolve().parents[1]
MATCH = PKG / "config" / "match.yaml"


def _obs(*, ball=True, lost_ball=False):
    return Observation(
        t=0.0,
        ball=Pose2D(0.0, 0.0, 0.0) if ball else None,
        robots={
            "rosy_01": Pose2D(-0.4, 0.0, 0.0),
            "rosy_02": Pose2D(0.4, 0.0, 3.14),
        },
        lost_ball=lost_ball,
        lost_robots=frozenset(),
    )


def test_stair1_ready_when_corners_robots_ball_and_goals_are_seen():
    setup = load_match(MATCH)
    report = stair1_visibility(
        setup,
        markers=(10, 11, 12, 13, 1, 2, 20, 21),
        obs=_obs(),
    )
    assert report["corners"] == [10, 11, 12, 13]
    assert report["robots"] == [1, 2]
    assert report["goals"] == [20, 21]
    assert report["ball"] is True
    assert report["ready"] is True


def test_stair1_not_ready_when_a_corner_is_missing():
    setup = load_match(MATCH)
    report = stair1_visibility(
        setup,
        markers=(10, 11, 12, 1, 2, 20, 21),
        obs=_obs(),
    )
    assert 13 not in report["corners"]
    assert report["ready"] is False


def test_stair1_not_ready_when_the_ball_is_lost():
    setup = load_match(MATCH)
    report = stair1_visibility(
        setup,
        markers=(10, 11, 12, 13, 1, 2, 20, 21),
        obs=_obs(ball=False, lost_ball=True),
    )
    assert report["ball"] is False
    assert report["ready"] is False


def test_format_visibility_says_not_field_go():
    setup = load_match(MATCH)
    report = stair1_visibility(
        setup,
        markers=(10, 11, 12, 13, 1, 2, 20, 21),
        obs=_obs(),
    )
    line = format_visibility(report)
    assert "ready=yes" in line
    assert "not FIELD GO" in line


def test_stair1_expect_lists_yaml_ids_and_is_not_ready():
    setup = load_match(MATCH)
    expect = stair1_expect(setup)
    assert expect["corners"] == [10, 11, 12, 13]
    assert expect["robots"] == [1, 2]
    assert expect["goals"] == [20, 21]
    line = format_visibility(expect, expect=True)
    assert "stair 1 expect" in line
    assert "not FIELD GO" in line
