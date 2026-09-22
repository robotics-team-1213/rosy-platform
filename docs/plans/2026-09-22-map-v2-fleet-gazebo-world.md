# MAP v2 Fleet (260919 STL) Gazebo World Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `src/apps/control/map/map_v2_fleet/260919 MAP FILE.STL`을 Gazebo Sim 8 월드로 변환하고, Pinky 1대를 그 위에 올려 카메라 차선 인식 → CORE 경유 라인 주행이 실제로 동작하는지 ROS-SIM 증거로 확인한다.

**Architecture:** ROS-free 변환기(`stl_scene.py`)가 STL을 "바닥 차선 삼각형"과 "외곽 벽 링"으로 분리해 ROS 좌표(m, Z-up, 중심 원점)로 옮긴다. 빌더(`build_world.py`)가 차선은 시각 전용 메쉬(`meshes/road_lines.stl`), 벽은 박스 충돌체로 SDF에 써서 기존 `world_to_map.py`(박스 전용)로 Nav2 맵까지 만든다. 실물 매트는 **어두운 바닥 위 흰 선**(2026-09-22 사용자 확인)이라 기존 `detect_lane_error`(밝은 선 임계값)를 수정 없이 쓰고, 주행은 기존 CORE `CAMERA_LINE` 모드를 그대로 쓴다.

**Tech Stack:** Python 3 (struct, xml, 표준 라이브러리), ROS 2 Jazzy launch, Gazebo Sim 8 (Harmonic), pytest.

---

## 0. 배경: STL을 분석해 보니

| 항목 | 측정값 | 의미 |
|---|---|---|
| 형식 | 바이너리 STL, 삼각형 1,768개, 단위 mm, **Y-up** | ROS(Z-up)로 옮길 때 축 변환이 필요하다 |
| 외곽 | X 0.05–2810.05, Z 12.55–1272.55 mm (**2.81 × 1.26 m**) | 기존 `map_260905`(2.715 × 1.265 m)와 거의 같은 책상 크기 |
| 높이 155 mm 형상 | 두께 5 mm 외곽 벽 링 1개(삼각형 24개) | LiDAR(0.125 m) 높이에 걸리는 **유일한** 장애물 |
| 높이 0.1 mm 형상 | 나머지 전부: 차선 경계선, 원형 교차로, 횡단보도 2곳 | 바닥 인쇄/테이프다. 벽이 아니다 |
| 선 폭 | 약 25–26 mm | |
| 차로 폭(선 안쪽 모서리 사이) | 약 159–166 mm, 선 중심 간격 약 185 mm | Pinky 외접 지름 0.172 m보다 좁다. 차체가 선 위로 걸친다 |
| 좌측 직선 차로 | 선 X 30–56 / 215–241 mm, 중심 X 135.5 mm | 스폰 후보 |
| 좌측 횡단보도 | STL Z 727–848 mm | |

핵심 결론:

1. **기존 260905 맵은 벽 16개짜리 미로였고, 새 260919 맵은 외곽 벽만 있는 "도로 트랙"이다.** LiDAR/SLAM/AMCL로 볼 수 있는 특징은 직사각형 하나뿐이다. 180° 대칭이라 AMCL 위치 추정이 모호하다. 그래서 이 맵의 1차 합격선은 **카메라 차선 주행**이다. Nav2는 외곽 안에서 충돌만 막는 보조 역할이다.
2. **선 색.** STL에는 색 정보가 없다. 실물은 **어두운 바닥 위 흰 선**이다(2026-09-22 사용자 확인). 현재 인식 코드(`src/apps/control/control/sensing/lane.py:3-4`, `:118` `THRESH_BINARY`)가 정확히 이 경우를 본다. 그래서 인식 코드는 바꾸지 않는다. 월드는 바닥 회색 0.2, 선 흰색 1.0으로 칠한다. 기존 semantic road 월드(바닥 0.8, 임계값 220)보다 대비가 크다.
3. **방향 모호성.** CAD의 Y-up 우수 좌표계를 ROS로 옮기는 올바른 회전은 R_x(+90°)다: `(x, y, z)_stl → (x, −z, y)`. 거울상이 아니다. 다만 실물 매트 사진과 한 번 대조해야 한다(Task 6 Step 1).
4. `gz_multi.launch.py`(N대)는 카메라 브리지와 line/road observer가 없다. 폴더 이름이 `map_v2_fleet`이지만 **이 계획은 1대까지만** 다룬다. 다대 운용은 §범위 밖에 후속으로 남긴다.

## 범위 밖 (후속 계획)

- `road_observer_node`(횡단보도/정지선) 연결 — 흰 선이라 극성 문제는 없다. 다만 이 맵의 `road_scene`/traffic policy(`map_id`) 정의가 따로 필요하다. 이 계획의 차선 주행과는 독립적이다.
- `gz_multi.launch.py`의 로봇별 카메라 브리지와 observer 추가(Fleet N대 차선 주행).
- 차선 기반 Nav2 keepout 마스크(선 밖을 금지 구역으로).
- 실물 Pinky DEVICE/FIELD 검증. Gazebo PASS는 바퀴 슬립, 조명, 매트 반사를 증명하지 않는다.

## 파일 구조

| 파일 | 책임 |
|---|---|
| Create `src/apps/control/map/map_v2_fleet/scripts/stl_scene.py` | ROS-free: STL 읽기, 바닥선/벽 분리, 좌표 변환, 벽 링 → 박스 4개 |
| Create `src/apps/control/map/map_v2_fleet/scripts/build_world.py` | CLI: 차선 메쉬 STL + `.world` SDF 쓰기 (결정적 출력) |
| Create `src/apps/control/map/map_v2_fleet/worlds/map_v2_fleet.world` | 생성물 (체크인) |
| Create `src/apps/control/map/map_v2_fleet/meshes/road_lines.stl` | 생성물 (체크인) |
| Create `src/apps/control/map/map_v2_fleet/maps/map_v2_fleet.{pgm,yaml}` | `world_to_map.py` 생성물 (체크인) |
| Create `src/apps/control/map/map_v2_fleet/README.md` | 출처 해시, 재생성 명령, 증거 경계 |
| Create `src/apps/control/test/test_map_v2_fleet_scene.py` | 변환기/빌더 테스트 |
| Modify `src/apps/control/setup.py:7-14` | `map_v2_fleet` 번들도 설치 |
| Modify `src/sim/gz_sim/config/worlds.yaml` | `map_v2_fleet.world` 카탈로그 항목 |
| Modify `src/sim/gz_sim/test/test_world_profiles.py` | 카탈로그/설치 계약 테스트 |
| Create `src/sim/gz_sim/launch/map_v2_fleet_lane.launch.py` | 1대 + 카메라 + line observer + CORE |
| Create `src/sim/gz_sim/test/test_map_v2_fleet_launch.py` | 런치 소스 계약 테스트 |
| Create `docs/validation/map-v2-fleet-gazebo-2026-09-22/result.md` | ROS-SIM 증거 (Task 6) |

테스트 명령(Windows 호스트, 워크트리 루트):

```powershell
$env:PYTHONPATH = "src/apps/control;src/core/core;src"
python -m pytest src/apps/control/test/test_map_v2_fleet_scene.py src/sim/gz_sim/test/test_world_profiles.py src/sim/gz_sim/test/test_map_v2_fleet_launch.py -q
```

---

### Task 1: STL → ROS 좌표 장면 변환기 (ROS-free)

**Files:**
- Create: `src/apps/control/map/map_v2_fleet/scripts/stl_scene.py`
- Test: `src/apps/control/test/test_map_v2_fleet_scene.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""MAP v2 fleet — 260919 STL becomes a Gazebo road scene without reshaping it."""

import importlib.util
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "map" / "map_v2_fleet"
SOURCE = BUNDLE / "260919 MAP FILE.STL"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BUNDLE / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def scene():
    return _load("stl_scene").load_scene(SOURCE)


def test_source_is_the_reviewed_binary_stl(scene):
    assert scene.triangle_count == 1768
    assert len(scene.source_sha256) == 64


def test_footprint_is_centred_in_metres(scene):
    assert scene.size_x == pytest.approx(2.810, abs=1e-4)
    assert scene.size_y == pytest.approx(1.260, abs=1e-4)
    xs = [v[0] for t in scene.lines for v in t]
    ys = [v[1] for t in scene.lines for v in t]
    assert min(xs) >= -1.4051 and max(xs) <= 1.4051
    assert min(ys) >= -0.6301 and max(ys) <= 0.6301


def test_perimeter_ring_becomes_four_wall_boxes(scene):
    walls = scene.walls
    assert len(walls) == 4
    for wall in walls:
        assert min(wall.size_x, wall.size_y) == pytest.approx(0.005, abs=1e-6)
        assert wall.height == pytest.approx(0.155, abs=1e-6)
    long_walls = sorted(max(w.size_x, w.size_y) for w in walls)
    assert long_walls[-1] == pytest.approx(2.810, abs=1e-4)


def test_floor_paint_is_flat_and_below_one_millimetre(scene):
    assert len(scene.lines) == 1768 - scene.wall_triangle_count
    assert max(v[2] for t in scene.lines for v in t) <= 0.001


def test_rotation_is_proper_not_mirrored():
    mod = _load("stl_scene")
    # STL Y-up: +z (toward viewer) must map to ROS -y; +y (up) to ROS +z.
    assert mod.stl_to_ros((0.0, 0.0, 1000.0), (0.0, 0.0)) == pytest.approx((0.0, -1.0, 0.0))
    assert mod.stl_to_ros((0.0, 1000.0, 0.0), (0.0, 0.0)) == pytest.approx((0.0, 0.0, 1.0))


def test_rejects_truncated_stl(tmp_path):
    bad = tmp_path / "bad.stl"
    bad.write_bytes(b"\0" * 80 + struct.pack("<I", 5))
    with pytest.raises(ValueError, match="binary STL"):
        _load("stl_scene").load_scene(bad)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/apps/control/test/test_map_v2_fleet_scene.py -q`
Expected: FAIL — `FileNotFoundError` (`scripts/stl_scene.py` 없음)

- [ ] **Step 3: 최소 구현**

```python
"""MAP v2 fleet — 260919 CAD STL to a ROS-frame road scene (ROS-free).

The STL is millimetres, Y-up. Floor paint (lane lines, roundabout, crosswalks)
is 0.1 mm thick; the only tall solid is a 5 mm perimeter wall ring. Nothing is
reshaped: geometry is rotated R_x(+90 deg), scaled to metres and centred.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

MM = 0.001
#: Floor paint is 0.1 mm; anything taller than 1 mm is a solid.
FLOOR_MAX_UP_MM = 1.0

Vertex = tuple[float, float, float]
Triangle = tuple[Vertex, Vertex, Vertex]


@dataclass(frozen=True)
class WallBox:
    cx: float
    cy: float
    size_x: float
    size_y: float
    height: float


@dataclass(frozen=True)
class RoadScene:
    source_sha256: str
    triangle_count: int
    wall_triangle_count: int
    size_x: float
    size_y: float
    lines: tuple[Triangle, ...]
    walls: tuple[WallBox, ...]


def stl_to_ros(p: Vertex, centre: tuple[float, float]) -> Vertex:
    """(x, y_up, z) mm -> ROS (x, y, z) m. Proper rotation, never a mirror."""
    x, y, z = p
    return ((x - centre[0]) * MM, -(z - centre[1]) * MM, y * MM)


def _read_triangles(data: bytes) -> list[Triangle]:
    if len(data) < 84:
        raise ValueError("not a binary STL: shorter than the 84-byte header")
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + 50 * count:
        raise ValueError("not a binary STL: size does not match triangle count")
    triangles = []
    for i in range(count):
        v = struct.unpack_from("<12f", data, 84 + 50 * i)
        triangles.append(((v[3], v[4], v[5]), (v[6], v[7], v[8]), (v[9], v[10], v[11])))
    return triangles


def _ring_walls(tall: list[Triangle]) -> tuple[tuple[WallBox, ...], tuple[float, float], float, float]:
    """Rebuild the perimeter ring as four boxes and fail closed otherwise."""
    xs = sorted({round(v[0], 3) for t in tall for v in t})
    zs = sorted({round(v[2], 3) for t in tall for v in t})
    heights = {round(v[1], 3) for t in tall for v in t}
    if len(xs) != 4 or len(zs) != 4 or len(heights) != 2:
        raise ValueError("tall geometry is not a single rectangular wall ring")
    thick_x, thick_z = xs[1] - xs[0], zs[1] - zs[0]
    if abs(thick_x - (xs[3] - xs[2])) > 1e-3 or abs(thick_z - (zs[3] - zs[2])) > 1e-3:
        raise ValueError("wall ring thickness is not uniform")
    height = max(heights) * MM
    x0, x1, z0, z1 = xs[0], xs[3], zs[0], zs[3]
    cx, cz = (x0 + x1) / 2.0, (z0 + z1) / 2.0
    lx, lz = (x1 - x0) * MM, (z1 - z0) * MM
    tx, tz = thick_x * MM, thick_z * MM
    return (
        WallBox(0.0, (lz - tz) / 2.0, lx, tz, height),    # STL z0 side -> ROS +y
        WallBox(0.0, -(lz - tz) / 2.0, lx, tz, height),   # STL z1 side -> ROS -y
        WallBox(-(lx - tx) / 2.0, 0.0, tx, lz, height),
        WallBox((lx - tx) / 2.0, 0.0, tx, lz, height),
    ), (cx, cz), lx, lz


def load_scene(path: Path | str) -> RoadScene:
    data = Path(path).read_bytes()
    triangles = _read_triangles(data)
    tall = [t for t in triangles if max(v[1] for v in t) > FLOOR_MAX_UP_MM]
    floor = [t for t in triangles if max(v[1] for v in t) <= FLOOR_MAX_UP_MM]
    walls, centre, size_x, size_y = _ring_walls(tall)
    lines = tuple(tuple(stl_to_ros(v, centre) for v in t) for t in floor)
    return RoadScene(
        source_sha256=hashlib.sha256(data).hexdigest(),
        triangle_count=len(triangles),
        wall_triangle_count=len(tall),
        size_x=size_x,
        size_y=size_y,
        lines=lines,
        walls=walls,
    )
```

주의: 벽 링의 바닥면(y=0) 삼각형은 `max y ≤ 1 mm`라 `floor`로 분류될 수 있다. `test_floor_paint_is_flat...`가 개수로 이를 고정한다. 벽 아래에 깔려 보이지 않으므로 무해하다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/apps/control/test/test_map_v2_fleet_scene.py -q`
Expected: 6 passed. 벽 링 판정이 실패하면 STL을 고치지 말고 `_ring_walls` 가정(x/z 고유값 4개)을 실제 데이터로 다시 확인한다.

- [ ] **Step 5: 커밋**

```bash
git add src/apps/control/map/map_v2_fleet/scripts/stl_scene.py src/apps/control/test/test_map_v2_fleet_scene.py
git commit -m "feat(map): parse 260919 STL into a ROS-frame road scene"
```

### Task 2: 월드 빌더 (차선 메쉬 + 벽 박스 SDF)

**Files:**
- Create: `src/apps/control/map/map_v2_fleet/scripts/build_world.py`
- Create (generated): `src/apps/control/map/map_v2_fleet/worlds/map_v2_fleet.world`, `meshes/road_lines.stl`
- Test: `src/apps/control/test/test_map_v2_fleet_scene.py` (추가)

- [ ] **Step 1: 실패하는 테스트 추가**

```python
import xml.etree.ElementTree as ET

WORLD = BUNDLE / "worlds" / "map_v2_fleet.world"
MESH = BUNDLE / "meshes" / "road_lines.stl"


def test_builder_output_is_deterministic_and_checked_in(tmp_path):
    build = _load("build_world")
    build.build(SOURCE, tmp_path)
    assert (tmp_path / "worlds" / "map_v2_fleet.world").read_bytes() == WORLD.read_bytes()
    assert (tmp_path / "meshes" / "road_lines.stl").read_bytes() == MESH.read_bytes()


def test_world_has_four_lidar_height_wall_collisions_only():
    world = ET.parse(WORLD).getroot().find("world")
    boxes = [c for c in world.iter("collision") if c.find("./geometry/box") is not None]
    assert len(boxes) == 4
    assert not [c for c in world.iter("collision") if c.find("./geometry/mesh") is not None]


def test_lane_mesh_is_visual_only_above_the_ground_plane():
    world = ET.parse(WORLD).getroot().find("world")
    uris = [u.text for u in world.iter("uri")]
    assert "model://control/map/map_v2_fleet/meshes/road_lines.stl" in uris
    lines = world.find("./model[@name='road_lines']")
    assert lines.find("static").text == "true"
    assert float(lines.find("pose").text.split()[2]) == pytest.approx(0.001)


def test_world_records_the_source_hash(scene):
    assert scene.source_sha256 in WORLD.read_text(encoding="utf-8")


def test_white_lines_on_dark_floor_by_default():
    """The physical 260919 mat is white tape on a dark floor (lane.py polarity)."""
    text = WORLD.read_text(encoding="utf-8")
    assert "<diffuse>0.2 0.2 0.2 1</diffuse>" in text  # floor
    assert "<diffuse>1 1 1 1</diffuse>" in text        # lane paint
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/apps/control/test/test_map_v2_fleet_scene.py -q`
Expected: 새 5개 FAIL (`build_world.py` 없음)

- [ ] **Step 3: 구현**

```python
#!/usr/bin/env python3
"""Build worlds/map_v2_fleet.world and meshes/road_lines.stl from the 260919 STL.

Usage: python build_world.py [--out BUNDLE_DIR] [--line-colour bright|dark]
Output is byte-deterministic; re-run and diff before committing.
"""

from __future__ import annotations

import argparse
import importlib.util
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLE = HERE.parent
SOURCE = BUNDLE / "260919 MAP FILE.STL"
MESH_URI = "model://control/map/map_v2_fleet/meshes/road_lines.stl"
COLOURS = {
    # (floor, paint): dark = black tape on white mat, bright = white tape on dark floor
    "dark": ("1 1 1 1", "0.05 0.05 0.05 1"),
    "bright": ("0.2 0.2 0.2 1", "1 1 1 1"),
}


def _scene_module():
    spec = importlib.util.spec_from_file_location("stl_scene", HERE / "stl_scene.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _normal(t):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = t
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
    return nx / length, ny / length, nz / length


def write_mesh(lines, path: Path) -> None:
    header = b"rosy map_v2_fleet road_lines (metres, Z-up)".ljust(80, b" ")
    body = bytearray(header + struct.pack("<I", len(lines)))
    for t in lines:
        body += struct.pack("<12fH", *_normal(t), *t[0], *t[1], *t[2], 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(body))


def _wall_xml(i: int, w) -> str:
    pose = f"{w.cx:.5f} {w.cy:.5f} {w.height / 2:.5f} 0 0 0"
    size = f"{w.size_x:.5f} {w.size_y:.5f} {w.height:.5f}"
    return f"""        <collision name="wall_{i:02d}_col">
          <pose>{pose}</pose>
          <geometry><box><size>{size}</size></box></geometry>
          <surface><friction><ode><mu>0.9</mu><mu2>0.9</mu2></ode></friction></surface>
        </collision>
        <visual name="wall_{i:02d}_vis">
          <pose>{pose}</pose>
          <geometry><box><size>{size}</size></box></geometry>
          <material><ambient>0.30 0.35 0.45 1</ambient><diffuse>0.30 0.35 0.45 1</diffuse></material>
        </visual>
"""


def world_xml(scene, line_colour: str) -> str:
    floor, paint = COLOURS[line_colour]
    walls = "".join(_wall_xml(i, w) for i, w in enumerate(scene.walls))
    return f"""<?xml version="1.0"?>
<!-- MAP v2 fleet / 260919 — generated by scripts/build_world.py. Do not edit.
  Source: 260919 MAP FILE.STL sha256 {scene.source_sha256}
  Envelope {scene.size_x:.3f} x {scene.size_y:.3f} m, centred at the origin.
  STL Y-up mm -> ROS Z-up m by R_x(+90 deg); no reshaping.
  Lane paint is visual-only; the perimeter ring is the only collision.
  Line colour: {line_colour}. Orientation vs the physical mat: see README.md.
-->
<sdf version="1.6">
  <world name="map_v2_fleet">
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics">
      <engine><filename>gz-physics-dartsim-plugin</filename></engine>
    </plugin>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>

    <light type="directional" name="sun">
      <cast_shadows>false</cast_shadows>
      <pose>0 0 10 0 0 0</pose>
      <diffuse>0.9 0.9 0.9 1</diffuse>
      <specular>0.2 0.2 0.2 1</specular>
      <direction>-0.4 0.2 -0.9</direction>
    </light>

    <model name="ground_plane">
      <static>true</static>
      <link name="link">
        <collision name="collision">
          <geometry><plane><normal>0 0 1</normal><size>100 100</size></plane></geometry>
        </collision>
        <visual name="visual">
          <geometry><plane><normal>0 0 1</normal><size>100 100</size></plane></geometry>
          <material><ambient>{floor}</ambient><diffuse>{floor}</diffuse></material>
        </visual>
      </link>
    </model>

    <model name="road_lines">
      <static>true</static>
      <pose>0 0 0.001 0 0 0</pose>
      <link name="link">
        <visual name="paint">
          <geometry><mesh><uri>{MESH_URI}</uri></mesh></geometry>
          <material><ambient>{paint}</ambient><diffuse>{paint}</diffuse></material>
        </visual>
      </link>
    </model>

    <model name="track_v2_fleet">
      <static>true</static>
      <pose>0 0 0 0 0 0</pose>
      <link name="link">
{walls}      </link>
    </model>
  </world>
</sdf>
"""


def build(source: Path, out: Path, line_colour: str = "bright") -> None:
    scene = _scene_module().load_scene(source)
    write_mesh(scene.lines, out / "meshes" / "road_lines.stl")
    world = out / "worlds" / "map_v2_fleet.world"
    world.parent.mkdir(parents=True, exist_ok=True)
    world.write_text(world_xml(scene, line_colour), encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=BUNDLE)
    p.add_argument("--line-colour", choices=sorted(COLOURS), default="bright")
    args = p.parse_args(argv)
    build(SOURCE, args.out, args.line_colour)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 생성물 만들기**

Run: `python src/apps/control/map/map_v2_fleet/scripts/build_world.py`
Expected: `worlds/map_v2_fleet.world`, `meshes/road_lines.stl` 생성, 종료 코드 0

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest src/apps/control/test/test_map_v2_fleet_scene.py -q`
Expected: 11 passed

- [ ] **Step 6: 커밋**

```bash
git add src/apps/control/map/map_v2_fleet/scripts/build_world.py src/apps/control/map/map_v2_fleet/worlds src/apps/control/map/map_v2_fleet/meshes src/apps/control/test/test_map_v2_fleet_scene.py
git commit -m "feat(map): generate map_v2_fleet Gazebo world from the 260919 STL"
```

### Task 3: Nav2 점유 맵 생성

**Files:**
- Create (generated): `src/apps/control/map/map_v2_fleet/maps/map_v2_fleet.pgm`, `.yaml`
- Test: `src/apps/control/test/test_map_v2_fleet_scene.py` (추가)

- [ ] **Step 1: 실패하는 테스트 추가**

```python
import yaml

MAP_YAML = BUNDLE / "maps" / "map_v2_fleet.yaml"


def test_occupancy_map_matches_the_wall_ring():
    meta = yaml.safe_load(MAP_YAML.read_text(encoding="utf-8"))
    assert meta["image"] == "map_v2_fleet.pgm"
    assert meta["resolution"] == pytest.approx(0.01)
    pgm = (BUNDLE / "maps" / meta["image"]).read_bytes()
    assert pgm.startswith(b"P5")
    width, height = (int(v) for v in pgm.split(b"\n")[1].split())
    # 2.81 x 1.26 m ring + 0.3 m margin on each side, 1 cm cells.
    assert width == pytest.approx(341, abs=2)
    assert height == pytest.approx(186, abs=2)
```

주의: `world_to_map.py`의 PGM 헤더 줄 배치를 먼저 확인한다(`src/sim/gz_sim/scripts/world_to_map.py` 쓰기 함수). 주석 줄이 있으면 `split(b"\n")` 인덱스를 맞춘다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/apps/control/test/test_map_v2_fleet_scene.py::test_occupancy_map_matches_the_wall_ring -q`
Expected: FAIL (`FileNotFoundError`)

- [ ] **Step 3: 생성**

Run:
```bash
python src/sim/gz_sim/scripts/world_to_map.py src/apps/control/map/map_v2_fleet/worlds/map_v2_fleet.world -o src/apps/control/map/map_v2_fleet/maps/map_v2_fleet --resolution 0.01 --seed -1.26955,0.24255
```
Expected: `.pgm`/`.yaml` 생성. 시드는 Task 4의 스폰 지점(좌측 차로 중심)이다. 차선은 충돌체가 아니므로 링 안쪽 전체가 free다. 이것이 맞는 결과다.

- [ ] **Step 4: 통과 확인** — Run 위 pytest, Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/apps/control/map/map_v2_fleet/maps src/apps/control/test/test_map_v2_fleet_scene.py
git commit -m "feat(map): rasterize map_v2_fleet perimeter into a Nav2 map"
```

### Task 4: 설치 + 월드 카탈로그 등록

**Files:**
- Modify: `src/apps/control/setup.py:7-14`
- Modify: `src/sim/gz_sim/config/worlds.yaml` (`map_260905.world` 항목 아래)
- Test: `src/sim/gz_sim/test/test_world_profiles.py`

스폰 지점 근거: 좌측 세로 차로의 선이 STL X 30–56 / 215–241 mm라 중심은 X 135.5 mm이다. STL Z 400 mm는 횡단보도(Z 727–848)에서 떨어져 있다. ROS 좌표는 `(135.5 − 1405.05, −(400 − 642.55)) mm = (−1.26955, 0.24255) m`이다.

- [ ] **Step 1: 실패하는 테스트 추가** (`test_world_profiles.py` 끝)

```python
def test_map_v2_fleet_is_catalogued_from_the_control_bundle():
    profile = profile_for("map_v2_fleet.world")
    assert profile.world_source == (
        "package://control/map/map_v2_fleet/worlds/map_v2_fleet.world")
    assert profile.map == "package://control/map/map_v2_fleet/maps/map_v2_fleet.yaml"
    assert profile.spawn_x == pytest.approx(-1.26955)
    assert profile.spawn_y == pytest.approx(0.24255)
    assert profile.spawn_spacing == 0.0


def test_control_package_installs_the_map_v2_fleet_bundle():
    setup_py = (ROOT.parents[1] / "apps" / "control" / "setup.py").read_text(
        encoding="utf-8")
    assert "map_v2_fleet" in setup_py
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/sim/gz_sim/test/test_world_profiles.py -q`
Expected: 새 2개 FAIL

- [ ] **Step 3: 구현**

`worlds.yaml`:
```yaml
  map_v2_fleet.world:
    world_source: package://control/map/map_v2_fleet/worlds/map_v2_fleet.world
    map: package://control/map/map_v2_fleet/maps/map_v2_fleet.yaml
    inflation_radius: 0.10
    # 260919 STL 좌측 세로 차로 중심, 횡단보도(STL Z 727-848 mm)에서 떨어진 곳.
    # 차선은 시각 전용이라 Nav2 는 외곽 벽만 본다.
    spawn_x: -1.26955
    spawn_y: 0.24255
    spawn_spacing: 0.0
```

`setup.py`:
```python
map_bundles = (
    os.path.join('map', 'map_260905_update_v2'),
    os.path.join('map', 'map_v2_fleet'),
)
map_data_files = [
    (
        os.path.join('share', package_name, os.path.dirname(path)),
        [path],
    )
    for bundle in map_bundles
    for path in glob(os.path.join(bundle, '**', '*'), recursive=True)
    if os.path.isfile(path)
]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/sim/gz_sim/test/test_world_profiles.py -q`
Expected: 전부 PASS (기존 `test_control_package_installs_the_complete_v2_map_bundle` 포함)

- [ ] **Step 5: 커밋**

```bash
git add src/apps/control/setup.py src/sim/gz_sim/config/worlds.yaml src/sim/gz_sim/test/test_world_profiles.py
git commit -m "feat(sim): catalogue and install the map_v2_fleet world"
```

### Task 5: map_v2_fleet 1대 차선 런치

**Files:**
- Create: `src/sim/gz_sim/launch/map_v2_fleet_lane.launch.py`
- Test: `src/sim/gz_sim/test/test_map_v2_fleet_launch.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""map_v2_fleet lane launch keeps CORE the only final cmd_vel publisher."""

from pathlib import Path

LAUNCH = Path(__file__).resolve().parents[1] / "launch" / "map_v2_fleet_lane.launch.py"


def test_launch_uses_the_catalogued_world_and_spawn():
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"map_v2_fleet", "worlds", "map_v2_fleet.world"' in source
    assert '"spawn_x": "-1.26955"' in source
    assert '"spawn_y": "0.24255"' in source
    assert '"bridge_image": "true"' in source


def test_line_observer_uses_the_bright_line_threshold():
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"camera_bright_threshold": 180' in source


def test_only_core_can_command_motion():
    source = LAUNCH.read_text(encoding="utf-8")
    assert 'executable="core"' in source
    assert "cmd_vel" not in source
    assert "road_observer_node" not in source  # needs a map_v2_fleet road scene first
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/sim/gz_sim/test/test_map_v2_fleet_launch.py -q`
Expected: FAIL (`FileNotFoundError`)

- [ ] **Step 3: 구현**

```python
#!/usr/bin/env python3
"""One Pinky on the 260919 road track: camera lane evidence into CORE."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    gz_share = get_package_share_directory("gz_sim")
    control_share = get_package_share_directory("control")
    world = os.path.join(
        control_share, "map", "map_v2_fleet", "worlds", "map_v2_fleet.world")
    line_config = os.path.join(control_share, "config", "line_follow.yaml")
    default_core_overlay = os.path.join(
        gz_share, "config", "semantic_road_core.yaml")

    simulation = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            os.path.join(gz_share, "launch", "launch_sim.launch.xml")),
        launch_arguments={
            "world": world,
            "bridge_image": "true",
            "cam_tilt_deg": "25",
            "camera_width": LaunchConfiguration("camera_width"),
            "camera_height": LaunchConfiguration("camera_height"),
            "camera_update_rate": LaunchConfiguration("camera_update_rate"),
            "spawn_x": "-1.26955",
            "spawn_y": "0.24255",
            "spawn_yaw": LaunchConfiguration("spawn_yaw"),
            "gui": LaunchConfiguration("gazebo_gui"),
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument("gazebo_gui", default_value="false"),
        DeclareLaunchArgument("camera_width", default_value="320"),
        DeclareLaunchArgument("camera_height", default_value="180"),
        DeclareLaunchArgument("camera_update_rate", default_value="5"),
        # -pi/2 faces ROS -y along the left lane (toward the crosswalk).
        DeclareLaunchArgument("spawn_yaw", default_value="-1.5708"),
        DeclareLaunchArgument("core_overlay", default_value=default_core_overlay),
        simulation,
        Node(
            package="control",
            executable="line_observer_node",
            name="line_observer_node",
            output="screen",
            parameters=[line_config, {
                "use_sim_time": True,
                "require_camera_controls_stable": False,
                # Floor 0.2 grey (~51) vs paint 1.0 (~255): 180 sits well between.
                "camera_bright_threshold": 180,
            }],
        ),
        Node(
            package="core",
            executable="core",
            name="core",
            output="screen",
            parameters=[{"use_sim_time": True}],
            additional_env={"ROSY_CONFIG": LaunchConfiguration("core_overlay")},
        ),
        LogInfo(msg=(
            "map_v2_fleet lane sim: http://127.0.0.1:8080/dashboard "
            "(viewer token: rosy-dev-viewer). Start: PUT /api/v1/line-follow/mode "
            "{\"mode\": \"CAMERA_LINE\"} with the operator token.")),
    ])
```

주의: `semantic_road_core.yaml`의 `traffic_policy.map_id`가 `map_260905_update_v2`다. CORE가 map_id 불일치로 라인 주행을 막으면 `src/sim/gz_sim/config/map_v2_fleet_core.yaml`을 같은 내용에 `map_id: map_v2_fleet`로 만들어 기본값을 바꾼다. 이 분기는 Task 6 실행 로그로 결정한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/sim/gz_sim/test/ -q`
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/sim/gz_sim/launch/map_v2_fleet_lane.launch.py src/sim/gz_sim/test/test_map_v2_fleet_launch.py
git commit -m "feat(sim): add one-Pinky map_v2_fleet camera lane launch"
```

### Task 6: ROS-SIM 실행 검증 (WSL Ubuntu)

**Files:**
- Create: `docs/validation/map-v2-fleet-gazebo-2026-09-22/result.md`
- Create: `src/apps/control/map/map_v2_fleet/README.md`

- [ ] **Step 1: 방향 대조 (사람 확인)**

`review/map_v2_fleet_top.png`(Step 3에서 캡처한 Gazebo 탑뷰)를 실물 매트 사진이나 CAD 화면과 비교한다. 원형 교차로 오른쪽 S자 곡선과 상단 횡단보도의 위치가 같아야 한다. 거울상이면 `stl_to_ros`의 부호를 바꾸지 말고 먼저 CAD 내보내기 축 설정을 확인한다. 선 색은 흰색으로 확정됐다(2026-09-22). 바닥 밝기가 실물과 크게 다르면 README에 적는다.

- [ ] **Step 2: 빌드**

```bash
source /opt/ros/jazzy/setup.bash
cd <Rosy OS worktree in WSL>
colcon build --merge-install --packages-select control gz_sim core
source install/setup.bash
```
Expected: 3 packages finished, 실패 0

- [ ] **Step 3: 월드 로드 + 카메라**

```bash
ROS_DOMAIN_ID=42 ros2 launch gz_sim map_v2_fleet_lane.launch.py gazebo_gui:=true
```
확인:
- Gazebo 로그에 `road_lines.stl` 메쉬 로드 에러가 없다 (`model://control/...`가 `GZ_SIM_RESOURCE_PATH`의 `share/`에서 풀린다)
- `ros2 topic hz /camera/front` ≈ 5 Hz
- `ros2 topic echo /line/observation --once`에 `error`가 0 근처이고 confidence가 0보다 크다
- 탑뷰 스크린샷을 `src/apps/control/map/map_v2_fleet/review/map_v2_fleet_top.png`로 저장

메쉬가 안 보이면 `GZ_SIM_RESOURCE_PATH`에 `install/share`가 들어 있는지 확인한다. `launch_sim.launch.xml:20`의 `$(find-pkg-share description)/../`가 그 경로다.

- [ ] **Step 4: CORE 경유 라인 주행**

```bash
curl -s -X PUT http://127.0.0.1:8080/api/v1/line-follow/mode \
  -H "Authorization: Bearer rosy-dev-operator" -H "Content-Type: application/json" \
  -d '{"mode": "CAMERA_LINE"}'
ros2 topic info /cmd_vel -v   # 퍼블리셔는 core 하나뿐이어야 한다
```
60초 이상 주행하며 `/odom`을 기록한다. 판정:
- 좌측 차로 → 코너 → 하단 직선을 지난다
- 선 소실 3초 뒤 정지한다(`LANE_LOST_GRACE_S`). 선이 안 보이는데 계속 가면 FAIL
- 모드 OFF 후 최종 명령이 0이다

알려진 위험: 좌측 루프 모서리는 직각이다. 단순 무게중심 추종은 직각 코너에서 선을 잃을 수 있다. 잃고 **안전 정지**하면 인식 계약은 PASS, 코너 주행은 HOLD로 따로 적는다. 이 계획 안에서 제어 게인을 튜닝하지 않는다.

- [ ] **Step 5: 증거 기록**

`docs/validation/map-v2-fleet-gazebo-2026-09-22/result.md`에 적는다: run ID, 소스 STL sha256, 커밋, 카메라 Hz, 관측 샘플, 주행 거리, 정지 이벤트, `/cmd_vel` 퍼블리셔 목록. 그리고 한 줄로 명시한다: "ROS-SIM only. DEVICE / FIELD: NOT RUN."

`README.md`에 적는다: 출처, sha256, 재생성 명령(`build_world.py`, `world_to_map.py`), 좌표 변환, 선 색 가정, 방향 대조 결과.

- [ ] **Step 6: 커밋**

```bash
git add docs/validation/map-v2-fleet-gazebo-2026-09-22 src/apps/control/map/map_v2_fleet/README.md src/apps/control/map/map_v2_fleet/review
git commit -m "test(sim): record map_v2_fleet ROS-SIM lane evidence"
```

---

## 확정된 결정 (2026-09-22)

1. **실물 선 색**: 어두운 바닥 위 흰 선. 인식 코드는 바꾸지 않는다(원래 Task 5 삭제).
2. **통합 위치**: 새 브랜치 `feat/map-v2-fleet-world`, 새 워크트리. `codex/pinky-integrated-acceptance`(Phase 5 통합 중)는 건드리지 않는다.

## 실행 중 변경 (2026-09-22)

- Task 3: 해상도를 0.01에서 **0.005 m**로 바꿨다. 5 mm 벽이 1 cm 셀 중심에 걸리지 않아 +x 벽이 빠졌고, 외부가 free로 새어 나갔다(코드 리뷰에서 발견). 테스트는 셀 단위 판정으로 강화했다.
- Task 5: 차선 메쉬 `model://control/...`가 isolated colcon 레이아웃에서도 풀리도록 `launch_sim.launch.xml`에 `extra_resource_path` 인자를 추가했다. 이 인자의 XML 주석에 `--`가 있어 런치가 깨졌고, 그래서 XML 파싱 테스트를 추가했다.
- Task 6에서 나온 수정: 로봇 차체가 회색 218로 보여 임계값을 180에서 **220**으로 올렸다. ENFORCED 교통 정책이 도로 증거 없이 HOLD를 걸어서, 이 맵 전용 오버레이 `map_v2_fleet_core.yaml`(DISABLED)을 만들었다.
- Task 6 결과: 파이프라인은 PASS다. 그러나 **차로 중앙 유지는 FAIL**이다. 현재 검출기는 단일 선을 추종하기 때문이다. 상세는 `docs/validation/map-v2-fleet-gazebo-2026-09-22/result.md`에 있다.
