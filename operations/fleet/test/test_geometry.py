"""FOR-001 대형 → 슬롯 오프셋. 좌표 규약은 core_features.swarm.follow_goal 과 같다:
distance 는 리더 뒤(+), lateral 은 리더 왼쪽(+). 리더는 슬롯 0 이며 목록에 없다."""

import math

import pytest

from fleet.formation.geometry import (
    MIN_SPACING,
    Formation,
    FormationError,
    SlotOffset,
    slot_world_position,
    slots,
)


def _close(a: SlotOffset, b: tuple[float, float]) -> bool:
    return math.isclose(a.distance, b[0], abs_tol=1e-9) and math.isclose(a.lateral, b[1], abs_tol=1e-9)


def test_column_stacks_behind_the_leader():
    got = slots(Formation.COLUMN, 3, 0.5)
    assert [(s.distance, s.lateral) for s in got] == [(0.5, 0.0), (1.0, 0.0), (1.5, 0.0)]


def test_line_alternates_left_then_right_beside_the_leader():
    got = slots(Formation.LINE, 3, 0.5)
    assert [(s.distance, s.lateral) for s in got] == [(0.0, 0.5), (0.0, -0.5), (0.0, 1.0)]


def test_v_opens_behind_the_leader_alternating_sides():
    got = slots(Formation.V, 2, 0.5)
    assert [(s.distance, s.lateral) for s in got] == [(0.5, 0.5), (0.5, -0.5)]


def test_grid_fills_rows_of_grid_cols_with_the_leader_at_front_left():
    got = slots(Formation.GRID, 3, 0.5, grid_cols=2)
    # 인덱스 0 은 리더 (row 0, col 0). k=1 → (0, col 1) 오른쪽, k=2 → 다음 행 왼쪽, k=3 → 그 오른쪽.
    assert [(s.distance, s.lateral) for s in got] == [(0.0, -0.5), (0.5, 0.0), (0.5, -0.5)]


def test_circle_puts_the_leader_on_the_ring_and_keeps_the_chord_equal_to_spacing():
    s = 0.5
    got = slots(Formation.CIRCLE, 3, s)
    r = s / (2 * math.sin(math.pi / 4))
    assert _close(got[0], (r, r))            # θ = 90°
    assert _close(got[1], (2 * r, 0.0))      # θ = 180°
    assert _close(got[2], (r, -r))           # θ = 270°
    # 인접 현 길이가 spacing 이다 — 두 로봇 사이 직선 거리가 안전 하한을 넘어야 하므로.
    ring = [(0.0, 0.0)] + [(p.distance, p.lateral) for p in got]
    for a, b in zip(ring, ring[1:] + ring[:1]):
        assert math.isclose(math.dist(a, b), s, abs_tol=1e-9)


def test_follow_is_exactly_one_slot_behind():
    assert slots(Formation.FOLLOW, 1, 0.7) == [SlotOffset(0.7, 0.0)]


@pytest.mark.parametrize("bad", [MIN_SPACING - 0.01, 0.0, -1.0, float("inf"), float("nan")])
def test_spacing_below_the_floor_is_refused(bad):
    with pytest.raises(FormationError):
        slots(Formation.COLUMN, 2, bad)


def test_follow_refuses_more_than_one_follower():
    with pytest.raises(FormationError):
        slots(Formation.FOLLOW, 2, 0.6)


@pytest.mark.parametrize("followers", [0, -1])
def test_a_formation_needs_at_least_one_follower(followers):
    with pytest.raises(FormationError):
        slots(Formation.LINE, followers, 0.6)


def test_grid_refuses_zero_columns():
    with pytest.raises(FormationError):
        slots(Formation.GRID, 2, 0.6, grid_cols=0)


def test_slot_world_position_matches_follow_goal_convention():
    # 리더 (1, 2) 가 +y 를 본다. 뒤 1 m 는 (1, 1), 왼쪽 1 m 는 -x 쪽 (0, 2).
    behind = slot_world_position(SlotOffset(1.0, 0.0), 1.0, 2.0, math.pi / 2)
    left = slot_world_position(SlotOffset(0.0, 1.0), 1.0, 2.0, math.pi / 2)
    assert math.isclose(behind[0], 1.0, abs_tol=1e-9) and math.isclose(behind[1], 1.0, abs_tol=1e-9)
    assert math.isclose(left[0], 0.0, abs_tol=1e-9) and math.isclose(left[1], 2.0, abs_tol=1e-9)


def test_a_string_formation_name_is_normalized_so_the_follow_guard_still_holds():
    assert slots("COLUMN", 2, 0.5) == slots(Formation.COLUMN, 2, 0.5)
    with pytest.raises(FormationError):
        slots("FOLLOW", 3, 0.6)


def test_an_unknown_formation_is_a_formation_error():
    with pytest.raises(FormationError):
        slots("TRIANGLE", 2, 0.6)


def test_spacing_exactly_at_the_floor_is_accepted_and_the_list_has_one_slot_per_follower():
    got = slots(Formation.V, 4, MIN_SPACING)
    assert len(got) == 4


def test_slot_world_position_is_the_point_follow_goal_drives_to():
    # 이 모듈의 존재 이유다: 로봇 쪽 follow_goal 과 같은 점을 내야 한다. 손계산이 아니라
    # 그 함수와 직접 비교한다 — 어느 쪽 규약이 바뀌어도 여기서 드러난다.
    from core_features.swarm import ReferencePose, follow_goal

    for x, y, yaw, d, lat in [(0.0, 0.0, 0.0, 0.6, 0.0), (1.0, 2.0, math.pi / 2, 1.0, 1.0),
                              (-3.2, 0.7, -2.1, 0.45, -0.6), (5.0, -1.0, 3.0, 1.2, 0.3)]:
        ours = slot_world_position(SlotOffset(d, lat), x, y, yaw)
        theirs = follow_goal(ReferencePose("leader", x, y, yaw), d, lat)
        assert math.isclose(ours[0], theirs.x, abs_tol=1e-12)
        assert math.isclose(ours[1], theirs.y, abs_tol=1e-12)


@pytest.mark.parametrize("formation", list(Formation))
@pytest.mark.parametrize("followers", [1, 2, 3, 4, 5, 6])
def test_no_two_robots_are_ever_closer_than_spacing(formation, followers):
    # MIN_SPACING 이 지키려는 성질 그 자체. 새 대형이 _GENERATORS 에 들어와도 이 테스트가 막는다.
    if formation is Formation.FOLLOW and followers != 1:
        pytest.skip("FOLLOW is a single follower")
    s = 0.5
    points = [(0.0, 0.0)] + [(o.distance, o.lateral) for o in slots(formation, followers, s)]
    for i, a in enumerate(points):
        for b in points[i + 1:]:
            assert math.dist(a, b) >= s - 1e-9, (formation, followers, a, b)


@pytest.mark.parametrize("followers", [1, 2, 3, 4, 5, 6])
def test_circle_chord_equals_spacing_for_any_size(followers):
    s = 0.5
    ring = [(0.0, 0.0)] + [(p.distance, p.lateral) for p in slots(Formation.CIRCLE, followers, s)]
    for a, b in zip(ring, ring[1:] + ring[:1]):
        assert math.isclose(math.dist(a, b), s, abs_tol=1e-9)
