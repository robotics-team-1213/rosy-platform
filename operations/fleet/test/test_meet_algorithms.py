"""같은 장면에 알고리즘만 바꿔 끼울 수 있는지."""

from __future__ import annotations

import pytest

from fleet.meet import Action, Pin, decide, names, register
from fleet.meet.scene import Order, Robot, Scene
from fleet.meet.track import track_v2


def _by(name, robots):
    return {order.robot_id: order for order in decide(name, track_v2(robots))}


def test_both_algorithms_are_registered():
    assert names() == ("room_hold", "wait_both")


def test_the_same_head_on_scene_picks_a_different_order():
    """동쪽 문 뒤에 있는 쪽이 방으로 빠지고, wait_both 는 둘 다 선다."""
    robots = (Robot("near", "east", 1.2, 1), Robot("far", "east", 2.5, -1))
    held = _by("room_hold", robots)
    assert held["near"].action is Action.SIDESTEP
    assert held["near"].room_id == "east_room"
    assert held["near"].s_m == pytest.approx(0.860)
    assert held["far"].action is Action.WAIT
    waiting = _by("wait_both", robots)
    assert waiting["near"].action is Action.WAIT
    assert waiting["far"].action is Action.WAIT


def test_a_short_rear_exit_beats_a_longer_door():
    """구간 끝까지 0.165 m 인 쪽이, 문까지 0.563 m 인 쪽보다 가깝다."""
    orders = _by("room_hold", (Robot("door", "west", 2.0, 1), Robot("end", "west", 2.7, -1)))
    assert orders["end"].action is Action.RETREAT
    assert orders["end"].s_m == pytest.approx(2.865)
    assert orders["door"].action is Action.WAIT


def test_the_same_direction_only_holds_the_rear_robot():
    robots = (Robot("rear", "west", 1.0, 1), Robot("lead", "west", 1.1, 1))
    orders = _by("room_hold", robots)
    assert orders["rear"].action is Action.WAIT
    assert orders["lead"].action is Action.PROCEED
    assert _by("wait_both", robots)["rear"].action is Action.PROCEED


def test_an_untrusted_heading_is_not_a_sidestep():
    robots = (Robot("near", "east", 1.2, 1, trusted=False), Robot("far", "east", 2.5, -1))
    orders = _by("room_hold", robots)
    assert orders["near"].action is Action.ESCALATE
    assert orders["far"].action is Action.ESCALATE


def test_three_on_one_line_and_a_backward_ring_are_left_to_a_person():
    crowd = _by("room_hold", (
        Robot("a", "east", 0.5, 1), Robot("b", "east", 1.5, 1), Robot("c", "east", 2.5, -1),
    ))
    assert {order.action for order in crowd.values()} == {Action.ESCALATE}
    ring = _by("room_hold", (Robot("a", "ring_n", 0.1, 1), Robot("b", "ring_n", 0.3, -1)))
    assert ring["a"].action is Action.ESCALATE
    assert ring["b"].action is Action.ESCALATE


def test_opposite_entry_waits_outside_the_line():
    robots = (Robot("in", "west", 1.0, -1), Robot("out", None, 0.0, 1, wants_edge="west"))
    assert _by("room_hold", robots)["out"].action is Action.HOLD
    assert _by("wait_both", robots)["out"].action is Action.HOLD


def test_robots_already_moving_apart_continue():
    orders = _by("room_hold", (Robot("a", "west", 2.0, 1), Robot("b", "west", 1.0, -1)))
    assert orders["a"].action is Action.PROCEED
    assert orders["b"].action is Action.PROCEED


def test_a_new_algorithm_registers_beside_the_others():
    class HoldAll:
        name = "hold_all"

        def decide(self, scene: Scene) -> tuple[Order, ...]:
            return tuple(Order(robot.id, Action.HOLD, reason="test") for robot in scene.robots)

    if "hold_all" not in names():
        register(HoldAll())
    scene = track_v2((Robot("a", "west", 1.0, 1),))
    assert decide("hold_all", scene)[0].action is Action.HOLD
    assert decide("wait_both", scene)[0].action is Action.PROCEED


def test_an_algorithm_that_skips_a_robot_is_rejected():
    class Drop:
        name = "drop"

        def decide(self, scene: Scene) -> tuple[Order, ...]:
            return ()

    if "drop" not in names():
        register(Drop())
    with pytest.raises(ValueError, match="each robot once"):
        decide("drop", track_v2((Robot("a", "west", 1.0, 1),)))


def test_an_unknown_name_names_the_ones_that_exist():
    with pytest.raises(KeyError, match="room_hold"):
        decide("missing", track_v2())


def test_three_in_the_same_direction_on_a_two_way_edge_are_left_to_a_person():
    orders = _by("room_hold", (
        Robot("a", "west", 0.4, 1), Robot("b", "west", 1.0, 1), Robot("c", "west", 1.6, 1),
    ))
    assert {order.action for order in orders.values()} == {Action.ESCALATE}


def test_a_oneway_ring_does_not_stop_same_direction_traffic():
    """고리에서 멈추면 뒤를 막으므로, 같은 방향은 셋이어도 간격과 상관없이 간다."""
    pair = _by("room_hold", (Robot("rear", "ring_n", 0.05, 1), Robot("lead", "ring_n", 0.20, 1)))
    assert pair["rear"].action is Action.PROCEED
    assert pair["rear"].reason == "oneway"
    assert pair["lead"].action is Action.PROCEED
    crowd = _by("room_hold", (
        Robot("a", "ring_e", 0.05, 1), Robot("b", "ring_e", 0.20, 1), Robot("c", "ring_e", 0.35, 1),
    ))
    assert {order.action for order in crowd.values()} == {Action.PROCEED}


def test_a_full_room_is_not_a_door():
    """동쪽 방이 차 있으면 가까운 쪽은 문으로 빠지지 않고 구간 시작으로 물러난다."""
    robots = (
        Robot("near", "east", 1.2, 1),
        Robot("far", "east", 2.5, -1),
        Robot("parked", None, 0.0, 1, room_id="east_room"),
    )
    orders = _by("room_hold", robots)
    assert orders["near"].action is Action.RETREAT
    assert orders["near"].s_m == pytest.approx(0.0)
    assert orders["near"].room_id is None
    assert orders["far"].action is Action.WAIT
    assert orders["parked"].action is Action.WAIT
    assert orders["parked"].reason == "in_room"


def test_a_pin_keeps_the_longer_retreat_as_the_yielder():
    """거리가 뒤집혀도 이미 고른 쪽이 비킨다. 동쪽 먼 쪽의 뒤는 구간 끝이다."""
    robots = (Robot("near", "east", 1.2, 1), Robot("far", "east", 2.5, -1))
    orders = {order.robot_id: order for order in decide(
        "room_hold", track_v2(robots, pins=(Pin("east", "far"),)),
    )}
    assert orders["far"].action is Action.RETREAT
    assert orders["far"].s_m == pytest.approx(3.992)
    assert orders["near"].action is Action.WAIT


def test_a_robot_waiting_in_a_room_holds_while_the_lane_proceeds():
    orders = _by("room_hold", (
        Robot("alone", "west", 1.0, 1),
        Robot("inside", None, 0.0, 1, room_id="west_spot"),
    ))
    assert orders["alone"].action is Action.PROCEED
    assert orders["inside"].action is Action.WAIT
    assert orders["inside"].reason == "in_room"
    assert orders["inside"].room_id == "west_spot"


def test_backward_entry_onto_a_oneway_holds_outside():
    robot = Robot("back", None, 0.0, -1, wants_edge="ring_n")
    order = _by("room_hold", (robot,))["back"]
    assert order.action is Action.HOLD
    assert order.reason == "oneway"
