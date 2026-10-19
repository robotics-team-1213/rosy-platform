"""Grid sampling uses the OccupancyGrid origin, including its rotation."""

import math

import pytest

from core_features.maps import GridFrame


@pytest.mark.parametrize("yaw", [math.pi / 2, -math.pi / 2, math.pi])
def test_world_to_cell_rotates_by_origin_yaw(yaw):
    grid = GridFrame(3, 3, 0.5, 2.0, -1.0, yaw, tuple(range(9)))
    x = grid.origin_x + math.cos(yaw) * 0.75 - math.sin(yaw) * 0.25
    y = grid.origin_y + math.sin(yaw) * 0.75 + math.cos(yaw) * 0.25
    assert grid.world_to_cell(x, y) == (1, 0)
    assert grid.sample_world(x, y) == 1
    outside_x = grid.origin_x - math.cos(yaw) * 0.25 - math.sin(yaw) * 0.25
    outside_y = grid.origin_y - math.sin(yaw) * 0.25 + math.cos(yaw) * 0.25
    assert grid.world_to_cell(outside_x, outside_y) is None


def test_world_to_cell_zero_yaw_unchanged():
    grid = GridFrame(3, 3, 1.0, -1.0, -1.0, data=(0,) * 9)
    assert grid.world_to_cell(0.5, -0.5) == (1, 0)
