from games.field import ZERO, Field, Pose2D, Twist


def test_home_scores_in_the_away_goal_mouth():
    field = Field()
    assert field.in_away_goal(field.length_m / 2, 0.0)
    assert not field.in_away_goal(0.0, 0.0)
    assert field.in_bounds(0.0, 0.0)
    assert not field.in_bounds(field.length_m, 0.0)


def test_zero_twist_is_a_full_stop():
    assert ZERO == Twist(0.0, 0.0)
    pose = Pose2D(0.1, -0.2, 1.5)
    assert (pose.x, pose.y, pose.yaw) == (0.1, -0.2, 1.5)


def test_updated_goal_polygon_replaces_the_field_end():
    """D-100: 득점은 필드 m 폴리곤. 마커가 옮기면 기본 끝선이 아니다."""
    field = Field()
    moved = (
        (0.50, -0.12),
        (0.70, -0.12),
        (0.70, 0.12),
        (0.50, 0.12),
    )
    scored = field.with_goals(away=moved)
    assert scored.in_away_goal(0.60, 0.0)
    assert not scored.in_away_goal(field.length_m / 2, 0.0)
    assert field.in_away_goal(field.length_m / 2, 0.0)


def test_missing_goal_polygons_keep_the_field_end():
    field = Field().with_goals()
    assert field.in_home_goal(-field.length_m / 2, 0.0)
    assert field.in_away_goal(field.length_m / 2, 0.0)
    from games.field.geometry import in_polygon

    assert in_polygon(0.0, 0.0, ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)))
    assert not in_polygon(2.0, 0.0, ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)))
