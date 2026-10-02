"""비켜설 자리 찾기 — 맵에서 공간을 만들어 낼 수 있는지, 없으면 없다고 하는지."""

from __future__ import annotations

import math

import pytest

from fleet.server import bays

RES = 0.1

#: 폭 1.0 m 통로. 두 대가 마주치면 지나갈 수 없다 — 비켜설 자리도 없다.
CORRIDOR = [
    "##########################",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "##########################",
]

#: 같은 통로에 0.4 x 0.3 m 벽감 하나. 한 대가 여기 들어가면 다른 대가 지나간다.
ALCOVE = [
    "##########################",
    "##########....############",
    "##########....############",
    "##########....############",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "##########################",
]

#: 벽 건너편에 넓은 방이 있다. 자리는 있지만 갈 수는 없다.
WALLED_OFF = [
    "##########################",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "##########################",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "#........................#",
    "##########################",
]

#: 폭 2.0 m 방. 여기서는 두 대가 서로 지나간다 — Fleet 이 끼어들 이유가 없다.
HALL = ["#" * 26] + ["#" + "." * 24 + "#" for _ in range(20)] + ["#" * 26]


def payload(rows, resolution=RES, origin=(0.0, 0.0)):
    """그림 → 점유 격자 스냅샷. **첫 줄이 위**다 (격자 행 0 은 아래이므로 뒤집는다).

    '#' 벽, '.' 빈 칸, '?' 모르는 칸. 관제 시험도 같은 그림을 쓰도록 여기 둔다 - 맵이
    두 벌이면 기하 시험이 통과하는 맵에서 관제가 실패해도 알아채지 못한다.
    """
    height = len(rows)
    width = len(rows[0])
    data = []
    for line in reversed(rows):
        assert len(line) == width, "그림의 줄 길이가 다르면 격자가 어긋난다"
        for ch in line:
            data.append(100 if ch == "#" else (-1 if ch == "?" else 0))
    return {"width": width, "height": height, "resolution": resolution,
            "origin": {"x": origin[0], "y": origin[1], "yaw": 0.0}, "data": data}


def _grid(rows, resolution=RES, origin=(0.0, 0.0)):
    grid = bays.Grid.from_payload(payload(rows, resolution, origin))
    assert grid is not None
    return grid


def _line(x0, y0, x1, y1, n=30):
    return [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n + 1)]


# --- 격자 읽기 -------------------------------------------------------------------


def test_a_payload_that_is_not_a_grid_is_refused():
    """맵을 못 읽었는데 읽은 척하면, 없는 자리로 로봇을 비켜세운다."""
    assert bays.Grid.from_payload(None) is None
    assert bays.Grid.from_payload({}) is None
    assert bays.Grid.from_payload({"width": 2, "height": 2, "resolution": 0.1,
                                   "data": [0, 0]}) is None      # data 가 짧다
    assert bays.Grid.from_payload({"width": 0, "height": 2, "resolution": 0.1,
                                   "data": []}) is None


def test_cells_and_points_round_trip_through_an_offset_origin():
    """원점이 0 이 아닌 맵이 보통이다 — 여기가 어긋나면 비켜선 자리가 통째로 밀린다."""
    grid = _grid(CORRIDOR, origin=(-1.3, -0.6))
    for point in [(-1.25, -0.55), (0.35, 0.15), (1.05, -0.25)]:
        back = grid.point_of(grid.cell_of(point))
        assert math.dist(back, point) <= RES


def test_an_unknown_cell_counts_as_blocked():
    """아직 못 본 곳으로 비켜세우면 그 자리가 벽 속일 수 있다."""
    grid = _grid(["###", "#?#", "###"])
    assert grid.blocked(1, 1)
    assert grid.blocked(-1, 0)          # 격자 밖도 막힌 것


# --- 자유 폭 --------------------------------------------------------------------


def test_the_free_width_of_a_one_metre_corridor_is_about_one_metre():
    grid = _grid(CORRIDOR)
    assert bays.free_width_at(grid, (1.3, 0.55)) == pytest.approx(0.9, abs=0.15)


def test_a_two_metre_hall_is_about_two_metres_wide():
    grid = _grid(HALL)
    assert bays.free_width_at(grid, (1.3, 1.05)) == pytest.approx(2.0, abs=0.3)


def test_a_point_inside_a_wall_has_no_free_width():
    grid = _grid(CORRIDOR)
    assert bays.free_width_at(grid, (0.05, 0.05)) == 0.0


def test_corridor_width_is_not_a_passing_exemption():
    """D-93: 면제 상수와 분기가 없다. 6x6 m 빈 방도 스스로 교행하지 못했다."""
    assert not hasattr(bays, "PASSING_WIDTH_M")
    assert not hasattr(bays, "passing_is_possible")


# --- 자리 고르기 -----------------------------------------------------------------


def test_the_alcove_is_found_and_is_clear_of_the_route():
    """이것이 이 모듈의 존재 이유다 — 순서가 아니라 공간을 만든다."""
    grid = _grid(ALCOVE)
    route = _line(0.2, 0.55, 2.4, 0.55)

    bay = bays.best_bay(grid, route, (1.25, 0.55), keep_out_m=bays.YIELD_KEEP_OUT_M)

    assert bay is not None
    nearest = bays.nearest_on_route(route, bay)
    assert math.dist(nearest, bay) >= bays.YIELD_KEEP_OUT_M
    assert bays.free_width_at(grid, bay) >= 2 * bays.ROBOT_RADIUS_M
    assert bay[1] > 1.0                  # 벽감 안이지 통로가 아니다


def test_a_plain_corridor_has_no_bay_and_says_so():
    """폭 1 m 방의 정직한 답이다. 있는 척하면 로봇을 벽으로 보낸다."""
    grid = _grid(CORRIDOR)
    route = _line(0.2, 0.55, 2.4, 0.55)
    assert bays.best_bay(grid, route, (1.25, 0.55), keep_out_m=bays.YIELD_KEEP_OUT_M) is None


def test_a_bay_behind_a_wall_is_not_a_bay():
    """넓이만 보고 고르면, 갈 수 없는 자리를 골라 놓고 로봇은 영영 도착하지 못한다."""
    grid = _grid(WALLED_OFF)
    route = _line(0.2, 0.45, 2.4, 0.45)      # 아래쪽 방을 지나는 경로
    assert bays.best_bay(grid, route, (1.25, 0.45), keep_out_m=bays.YIELD_KEEP_OUT_M) is None


def test_a_bay_further_than_the_detour_budget_is_refused():
    """비켜서느라 3 m 를 가야 한다면 그것은 양보가 아니라 또 하나의 미션이다."""
    grid = _grid(ALCOVE)
    route = _line(0.2, 0.55, 2.4, 0.55)
    assert bays.best_bay(grid, route, (0.25, 0.55), keep_out_m=bays.YIELD_KEEP_OUT_M,
                         max_detour_m=0.3) is None


def test_the_nearest_bay_wins():
    """다익스트라가 비용 순으로 내놓으므로 첫 후보가 곧 가장 가까운 자리여야 한다."""
    grid = _grid(ALCOVE)
    route = _line(0.2, 0.55, 2.4, 0.55)
    near = bays.best_bay(grid, route, (1.25, 0.55), keep_out_m=bays.YIELD_KEEP_OUT_M)
    assert near is not None
    # 벽감 입구 쪽이지 깊숙한 안쪽이 아니다 — 들어간 만큼 되나와야 하기 때문이다.
    assert near[1] < 1.5


def test_a_bay_must_be_further_than_the_release_radius():
    """실측에서 온 조건이다 — 딱 기준선에 걸친 자리를 고르면 교착이 생긴다.

    2x1 m 방에서 경로로부터 0.48 m 떨어진 자리를 골랐고(기준 0.45 통과), 로봇은 목표에
    0.13 m 못 미쳐 섰고 AMCL 은 0.18 m 틀렸다. 보고 위치는 경로에서 0.18 m 였고 기다리던
    미션의 해제 조건은 "0.45 m 밖"이라 문이 영영 열리지 않았다.
    """
    grid = _grid(ALCOVE)
    route = _line(0.2, 0.55, 2.4, 0.55)

    bay = bays.best_bay(grid, route, (1.25, 0.55), keep_out_m=bays.YIELD_KEEP_OUT_M)

    assert bay is not None
    off_route = math.dist(bays.nearest_on_route(route, bay), bay)
    assert off_route >= bays.YIELD_KEEP_OUT_M + bays.BAY_MARGIN_M


def test_the_margin_rejects_a_bay_that_only_just_clears_the_release_line():
    """여백이 하는 일 자체. 0.70 m 자리는 기준 0.65 를 통과하지만 여유가 0.05 뿐이다."""
    grid = _grid(ALCOVE)
    route = _line(0.2, 0.55, 2.4, 0.55)

    assert bays.best_bay(grid, route, (1.25, 0.55), keep_out_m=0.65, margin_m=0.0) is not None
    assert bays.best_bay(grid, route, (1.25, 0.55), keep_out_m=0.65) is None


def test_a_pose_inside_a_wall_yields_no_bay():
    """측위가 튀었을 때 조용히 아무 데나 보내면 안 된다."""
    grid = _grid(ALCOVE)
    route = _line(0.2, 0.55, 2.4, 0.55)
    assert bays.best_bay(grid, route, (0.05, 0.05), keep_out_m=bays.YIELD_KEEP_OUT_M) is None


def test_no_map_means_no_bay():
    assert bays.best_bay(None, _line(0, 0, 2, 0), (1.0, 0.0), keep_out_m=0.45) is None


# --- D-395 P2-2: an untrusted robot is not moved to a bay ---------------------------------


def test_an_untrusted_robot_in_the_way_is_not_sent_to_a_bay():
    """Its map pose is not trusted, so a bay goal would be planned from a wrong pose.
    Fleet keeps it as a 0.45 m obstacle and the mission waits instead."""
    from fakes import run
    from test_server_yield import SimRobot, _console, _goals

    grid = payload(ALCOVE)
    left = SimRobot("rosy_01", (0.4, 0.6), grid)
    right = SimRobot("rosy_02", (2.2, 0.6), grid)
    console = _console(left, right)
    run(console.snapshot())                                       # both trusted (legacy) here
    right._state = {**right._state, "localization": {"state": "SUSPECT", "pose_frame": "map"}}

    result = run(console.goal("rosy_01", 2.2, 0.6))

    assert result["queued"] is True and result["reason"] == "LOCALIZATION_UNTRUSTED"
    assert _goals(right) == []
