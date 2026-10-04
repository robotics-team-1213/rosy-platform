"""FOR-002 슬롯 배정. 그리디는 최적이 아니다 — 테스트가 고정하는 것은 전단사, 입력
순서 불변, 2대 비교차, 개수 불일치 거절이다. Hungarian 은 같은 프로토콜로 들어온다."""

import pytest

from fleet.formation.assignment import AssignmentError, GreedyDistanceAssigner, SlotAssigner


def test_the_greedy_assigner_satisfies_the_protocol():
    assert isinstance(GreedyDistanceAssigner(), SlotAssigner)


def test_two_robots_do_not_cross():
    robots = {"a": (0.0, 0.0), "b": (1.0, 0.0)}
    slots = [(0.0, 1.0), (1.0, 1.0)]
    assert GreedyDistanceAssigner().assign(robots, slots) == {"a": 0, "b": 1}


def test_the_assignment_is_a_bijection():
    robots = {"a": (0.0, 0.0), "b": (3.0, 0.0), "c": (0.0, 3.0)}
    slots = [(2.9, 0.1), (0.1, 2.9), (0.1, 0.1)]
    got = GreedyDistanceAssigner().assign(robots, slots)
    assert sorted(got) == ["a", "b", "c"]
    assert sorted(got.values()) == [0, 1, 2]
    assert got == {"a": 2, "b": 0, "c": 1}


def test_input_order_does_not_change_the_result():
    robots = {"a": (0.0, 0.0), "b": (3.0, 0.0), "c": (0.0, 3.0)}
    slots = [(2.9, 0.1), (0.1, 2.9), (0.1, 0.1)]
    forward = GreedyDistanceAssigner().assign(robots, slots)
    backward = GreedyDistanceAssigner().assign(dict(reversed(list(robots.items()))), slots)
    assert forward == backward


def test_ties_break_deterministically_regardless_of_input_order():
    # 두 로봇이 두 슬롯에서 같은 거리다. robot_id 로 갈라야 하므로 dict 순서를 뒤집어도
    # 같은 답이어야 한다 — 같은 입력을 다섯 번 부르는 것은 순수 함수에서 아무것도 증명하지 않는다.
    robots = {"a": (0.0, 0.0), "b": (0.0, 0.0)}
    slots = [(1.0, 0.0), (-1.0, 0.0)]
    forward = GreedyDistanceAssigner().assign(robots, slots)
    backward = GreedyDistanceAssigner().assign(dict(reversed(list(robots.items()))), slots)
    assert forward == backward == {"a": 0, "b": 1}


def test_robot_and_slot_counts_must_match():
    with pytest.raises(AssignmentError):
        GreedyDistanceAssigner().assign({"a": (0.0, 0.0)}, [(0.0, 1.0), (1.0, 1.0)])


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_position_is_refused_instead_of_sorted_arbitrarily(bad):
    with pytest.raises(AssignmentError):
        GreedyDistanceAssigner().assign({"a": (bad, 0.0), "b": (1.0, 0.0)}, [(0.0, 1.0), (1.0, 1.0)])
    with pytest.raises(AssignmentError):
        GreedyDistanceAssigner().assign({"a": (0.0, 0.0), "b": (1.0, 0.0)}, [(bad, 1.0), (1.0, 1.0)])
