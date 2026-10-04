"""D-453: project a pose onto the painted track and split one order into one segment."""

import math

import pytest

from fleet.meet.place import painted_track, pose_on, project, steer_toward, yield_move
from fleet.meet.scene import Action, Order


def test_east_heading_is_trusted_and_the_origin_is_not_on_the_ring():
    painted = painted_track()
    x, y, yaw = pose_on(painted, "east", 0.0, direction=1)
    place = project(painted, x, y, yaw)
    assert place is not None and place.edge_id == "east" and place.trusted
    assert place.direction == 1 and place.s_m == pytest.approx(0.0, abs=0.02)
    back = project(painted, x, y, yaw + math.pi)
    assert back is not None and back.direction == -1 and back.trusted
    side = project(painted, x, y, yaw + math.pi / 2)
    assert side is not None and side.trusted is False
    assert project(painted, 0.0, 0.0, 0.0) is None


def test_west_spot_is_a_room_and_the_doors_keep_the_recorded_s():
    painted = painted_track()
    spot = project(painted, -1.0, 0.0, 0.0)
    assert spot is not None and spot.room_id == "west_spot" and spot.edge_id is None
    east = next(door for door in painted.doors if door.edge_id == "east")
    west = next(door for door in painted.doors if door.edge_id == "west")
    assert east.s_m == pytest.approx(0.860, abs=0.05)
    assert west.s_m == pytest.approx(1.437, abs=0.05)


def test_a_sidestep_follows_the_line_to_the_door_then_the_hold():
    painted = painted_track()
    door = next(item for item in painted.doors if item.room_id == "east_room")
    x, y, yaw = pose_on(painted, "east", 1.2, direction=1)
    place = project(painted, x, y, yaw)
    order = Order("near", Action.SIDESTEP, room_id="east_room", edge_id="east", s_m=door.s_m)
    assert place is not None
    move = yield_move(place, order, painted)
    assert move is not None
    turn, dist = move
    assert dist == pytest.approx(abs(1.2 - door.s_m), abs=0.02)
    assert abs(turn) == pytest.approx(math.pi, abs=0.05)
    dx, dy, dyaw = pose_on(painted, "east", door.s_m, direction=-1)
    at_door = project(painted, dx, dy, dyaw)
    assert at_door is not None
    into = yield_move(at_door, order, painted)
    assert into is not None
    assert into[1] == pytest.approx(math.hypot(0.65 - dx, 0.30 - dy), abs=0.05)


def test_the_door_to_hold_gap_is_not_on_the_track_and_steers_by_xy():
    painted = painted_track()
    door = next(item for item in painted.doors if item.room_id == "east_room")
    room = next(item for item in painted.rooms if item.id == "east_room")
    dx, dy, _tangent = painted.line("east").point_at(door.s_m)
    mid_x, mid_y = (dx + room.hold_xy[0]) / 2, (dy + room.hold_xy[1]) / 2
    assert project(painted, mid_x, mid_y, 0.0) is None
    into = steer_toward(mid_x, mid_y, 0.0, room.hold_xy)
    assert into is not None
    assert into[1] == pytest.approx(math.hypot(room.hold_xy[0] - mid_x, room.hold_xy[1] - mid_y), abs=0.01)
    back = steer_toward(room.hold_xy[0], room.hold_xy[1], 0.0, (dx, dy))
    assert back is not None
    assert back[1] == pytest.approx(math.hypot(room.hold_xy[0] - dx, room.hold_xy[1] - dy), abs=0.01)
