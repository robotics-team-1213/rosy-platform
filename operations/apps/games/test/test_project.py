from games.field import Field
from games.field.homography import field_corners, fit
from games.host.project import observation_from_pixels


def _h(field: Field):
    src = ((0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0))
    return fit(src, field_corners(field))


def test_missing_homography_marks_everyone_lost():
    field = Field(length_m=2.0, width_m=1.0)
    obs = observation_from_pixels(
        field=field,
        homography=None,
        ball_uv=(100.0, 50.0),
        robots={},
        roster=(field.home_id, field.away_id),
    )
    assert obs.lost_ball
    assert obs.ball is None
    assert obs.lost_robots == frozenset({field.home_id, field.away_id})


def test_ball_and_robots_project_onto_the_pitch():
    field = Field(length_m=2.0, width_m=1.0)
    obs = observation_from_pixels(
        field=field,
        homography=_h(field),
        ball_uv=(100.0, 50.0),
        robots={
            field.home_id: ((50.0, 50.0), (80.0, 50.0)),
            field.away_id: ((150.0, 50.0), (180.0, 50.0)),
        },
        roster=(field.home_id, field.away_id),
    )
    assert obs.ball is not None
    assert abs(obs.ball.x) < 1e-6
    assert abs(obs.ball.y) < 1e-6
    assert not obs.lost_ball
    assert not obs.lost_robots
    assert abs(obs.robots[field.home_id].yaw) < 1e-3
    assert obs.robots[field.home_id].x < 0
    assert obs.robots[field.away_id].x > 0


def test_missing_ball_or_robot_is_lost_not_guessed():
    field = Field(length_m=2.0, width_m=1.0)
    obs = observation_from_pixels(
        field=field,
        homography=_h(field),
        ball_uv=None,
        robots={field.home_id: ((50.0, 50.0), (80.0, 50.0))},
        roster=(field.home_id, field.away_id),
    )
    assert obs.lost_ball
    assert obs.ball is None
    assert field.away_id in obs.lost_robots
    assert field.home_id in obs.robots
