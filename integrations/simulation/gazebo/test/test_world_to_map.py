"""world_to_map — 월드 기하에서 점유 격자를 만드는 규칙.

순수 기하다. ROS 도 Gazebo 도 필요 없으므로 Windows 호스트에서 그대로 돈다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "world_to_map.py"


def _module():
    spec = importlib.util.spec_from_file_location("world_to_map", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wall(name, x, y, yaw, sx, sy, sz=0.44, z=0.22):
    return f"""
    <model name="{name}">
      <static>true</static><pose>{x} {y} {z} 0 0 {yaw}</pose>
      <link name="l"><collision name="c">
        <geometry><box><size>{sx} {sy} {sz}</size></box></geometry>
      </collision></link>
    </model>"""


def _world(tmp_path: Path, body: str, name: str = "t") -> Path:
    path = tmp_path / f"{name}.world"
    path.write_text(f"<?xml version='1.0' ?><sdf version='1.8'><world name='{name}'>"
                    f"{body}</world></sdf>", encoding="utf-8")
    return path


def _room(size: float = 4.0) -> str:
    half = size / 2
    return (_wall("front", 0, half, 0, size, 0.08)
            + _wall("back", 0, -half, 0, size, 0.08)
            + _wall("left", -half, 0, 1.5708, size, 0.08)
            + _wall("right", half, 0, 1.5708, size, 0.08))


def test_a_closed_room_becomes_free_inside_and_unknown_outside(tmp_path):
    """바깥까지 free 로 칠하면 플래너가 벽을 질러가는 경로를 낸다."""
    mod = _module()
    boxes = mod.read_boxes(_world(tmp_path, _room()))
    grid, x0, y0 = mod.rasterize(boxes, 0.05, (0.0, 0.0))

    def at(x, y):
        return grid[int((y - y0) / 0.05)][int((x - x0) / 0.05)]

    assert at(0.0, 0.0) == mod.FREE
    assert at(1.5, 1.5) == mod.FREE
    assert at(0.0, 2.0) == mod.OCCUPIED          # 벽 위
    assert at(0.0, 2.3) == mod.UNKNOWN           # 방 바깥


def test_a_rotated_wall_lies_along_the_axis_it_was_turned_onto(tmp_path):
    """yaw 를 무시하면 세로 벽이 가로로 깔려 통로가 통째로 막힌다."""
    mod = _module()
    boxes = mod.read_boxes(_world(tmp_path, _room() + _wall("v", 0.0, 0.0, 1.5708, 2.0, 0.08)))
    grid, x0, y0 = mod.rasterize(boxes, 0.05, (1.5, 0.0))

    def at(x, y):
        return grid[int((y - y0) / 0.05)][int((x - x0) / 0.05)]

    assert at(0.0, 0.8) == mod.OCCUPIED    # 벽은 y 축을 따라 뻗는다
    assert at(0.0, -0.8) == mod.OCCUPIED
    assert at(0.8, 0.0) == mod.FREE        # x 축은 비어 있다
    assert at(-0.8, 0.0) == mod.FREE


def test_the_canvas_hugs_the_world_instead_of_the_diagonal(tmp_path):
    """회전 박스의 경계를 대각선 반경으로 잡으면 6 m 벽 하나가 캔버스를 12 m 로 부풀린다."""
    mod = _module()
    boxes = mod.read_boxes(_world(tmp_path, _room(6.0)))
    grid, _x0, _y0 = mod.rasterize(boxes, 0.05, (0.0, 0.0))

    assert len(grid[0]) == pytest.approx(134, abs=2)      # 6 m + 벽 + 여백
    assert len(grid) == pytest.approx(134, abs=2)


def test_structures_that_miss_the_lidar_plane_are_left_out(tmp_path):
    """스캔에 안 잡히는 벽을 맵에 넣으면 로봇이 보지 못하는 장애물을 플래너만 아는 상태가 된다."""
    mod = _module()
    # 바닥에 깔린 문턱: 위쪽 끝이 0.04 m 라 0.125 m 의 라이다 평면에 닿지 않는다
    body = _room() + _wall("threshold", 0.0, 0.0, 0.0, 2.0, 0.08, sz=0.04, z=0.02)
    boxes = mod.read_boxes(_world(tmp_path, body))
    grid, x0, y0 = mod.rasterize(boxes, 0.05, (0.0, 1.0))

    assert grid[int((0.0 - y0) / 0.05)][int((0.0 - x0) / 0.05)] == mod.FREE


def test_a_seed_inside_a_wall_is_refused(tmp_path):
    """씨앗이 벽 안이면 flood 가 한 칸도 못 퍼진다 — 전부 unknown 인 맵을 쓰기 전에 멈춘다."""
    mod = _module()
    boxes = mod.read_boxes(_world(tmp_path, _room()))
    with pytest.raises(SystemExit):
        mod.rasterize(boxes, 0.05, (0.0, 2.0))


def test_the_written_map_reads_back_as_nav2_expects(tmp_path):
    """PGM 은 위에서 아래로 쓰고 격자는 아래에서 위로 센다. 뒤집으면 맵이 상하로 뒤집힌다."""
    mod = _module()
    boxes = mod.read_boxes(_world(tmp_path, _room() + _wall("top_bar", 0.0, 1.0, 0, 1.0, 0.08)))
    grid, x0, y0 = mod.rasterize(boxes, 0.05, (0.0, 0.0))
    out = tmp_path / "m"
    mod.write_map(grid, x0, y0, 0.05, out)

    data = out.with_suffix(".pgm").read_bytes()
    header, _, pixels = data.partition(b"255\n")
    width, height = (int(v) for v in header.split(b"\n")[2].split())
    bar_row_from_top = height - 1 - int((1.0 - y0) / 0.05)
    centre = int((0.0 - x0) / 0.05)
    assert pixels[bar_row_from_top * width + centre] == 0        # 막대는 위쪽 절반에 있다
    assert "resolution: 0.05" in out.with_suffix(".yaml").read_text(encoding="utf-8")
