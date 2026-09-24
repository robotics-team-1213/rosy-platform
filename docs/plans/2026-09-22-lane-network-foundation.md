# 260919 차선망 공통 기반 Implementation Plan (Plan 1 / 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 교차로 스파이크(A와 B)가 함께 쓸 공통 기반을 만든다. 공통 기반은 네 가지다. STL에서 만든 차선 그래프, 좌우 경계를 인식해 가운데선을 따르는 추종기(강등 사다리 포함), 인식 오버레이와 녹화, 12개 교차 시나리오 하네스다. 끝으로 가운데선 모드의 기준선 성능을 Gazebo에서 측정한다.

**Architecture:** 모두 ROS-free 모듈과 얇은 ROS 배선으로 나눈다.
- 차선 그래프는 `lane_rules.yaml`의 거친 앵커를 STL 경계선 거리장의 능선(두 선에서 같은 거리인 점)에 스냅해서 만든다.
- 가운데선 추종기 `LaneBoundaryTracker`는 기존 `LaneEdgeFollower`를 상속해 경계 인식과 기억을 그대로 쓰고, 목표점 선택만 바꾼다. 이를 위해 `_follow`를 "경계 찾기"와 "목표 고르기"로 나누는 리팩터를 먼저 한다. `edge_left`의 동작은 바뀌지 않는다.
- 오버레이는 관측 노드가 `line/debug/compressed`로 발행하고, 녹화기가 MP4로 저장한다.

**Tech Stack:** Python 3 (Windows 호스트 3.14, WSL 3.12), NumPy, OpenCV 5, PyYAML, ROS 2 Jazzy, Gazebo Sim 8.11, pytest.

**Spec:** `docs/plans/2026-09-22-lane-network-junction-spike-design.md` §3, §4(4.1-4.4), §8. §5-§7(A, B, 비교)은 Plan 2에서 다룬다. Plan 2는 이 계획의 기준선 측정(Task 9)이 끝난 뒤에 쓴다.

---

## 공통 규칙

- 작업 디렉터리: `F:\Dev\Control\Robot\ROS\Rosy\.worktrees\lane-network-junctions` (브랜치 `feat/lane-network-junctions`). `git stash`는 쓰지 않는다.
- Windows 호스트 시험 명령:
  ```powershell
  $env:PYTHONPATH = "src/core/control;src/core/core;src"
  python -m pytest src/core/control/test/ src/sim/gz_sim/test/ -q
  ```
  기준선은 1,337 passed, 29 skipped다(main `5207531` 기준). 매 작업 끝에 이 숫자가 줄지 않아야 한다.
- 커밋 메시지 끝에는 다음 줄을 넣는다:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- 불변 조건(spec §8): `control`은 증거와 관찰 이미지만 발행한다. Twist와 `cmd_vel`은 없다. 기존 `line`, `lane`, `edge_left` 모드는 바뀌지 않는다.

## 파일 구조

| 파일 | 책임 |
|---|---|
| Create `src/core/control/test/lane_sim.py` | 시험 공용: 역투영 렌더러 `World`, 차선 생성, CORE 법칙 거울, 폐루프 `drive`, STL 월드 |
| Modify `src/core/control/test/test_lane_edge.py` | 공용 도우미를 `lane_sim`에서 가져온다(동작 변경 없음) |
| Create `src/core/control/map/map_v2_fleet/lane_rules.yaml` | 사람이 정한 규칙: 링 기하, 도로 앵커, 통행 방향, 주차 |
| Create `src/core/control/map/map_v2_fleet/scripts/lane_graph.py` | 규칙과 STL로 `lane_graph.yaml` 생성, 여유 거리 검증 |
| Create `src/core/control/map/map_v2_fleet/lane_graph.yaml` | 생성물(체크인, 결정적) |
| Create `src/core/control/test/test_lane_graph.py` | 그래프 시험 |
| Modify `src/core/control/control/sensing/lane_bev.py` | `_follow`를 `_pursue` 훅으로 분리하고, `_lookahead`를 띠 기반 `_band_lookahead`로 일반화한다(동작 불변) |
| Create `src/core/control/control/sensing/lane_boundaries.py` | `LaneBoundaryTracker`: 좌우 경계, 가운데선, 강등 사다리(BOTH/ONE/MEMORY/STOP), 교차 신호 |
| Create `src/core/control/test/test_lane_boundaries.py` | 추종기 시험 |
| Modify `src/core/control/control/line_observer_node.py` | `camera_lane_mode: centre`, 디버그 오버레이 발행 |
| Modify `src/core/control/config/line_follow.yaml` | 새 파라미터 기본값(끔) |
| Create `src/core/control/control/sensing/lane_debug.py` | ROS-free 4칸 오버레이 렌더러 |
| Create `src/core/control/test/test_lane_debug.py` | 렌더러 시험 |
| Modify `src/sim/gz_sim/launch/map_v2_fleet_lane.launch.py` | 모드, 스폰, 오버레이를 launch 인자로 연다 |
| Create `src/sim/gz_sim/scripts/record_debug.py` | 디버그 토픽을 MP4와 JSONL로 저장 |
| Create `src/sim/gz_sim/scripts/junction_score.py` | ROS-free: 그래프로 12개 시나리오를 만들고 궤적을 판정 |
| Create `src/sim/gz_sim/test/test_junction_score.py` | 판정 시험 |
| Create `src/sim/gz_sim/scripts/junction_harness.py` | ROS: 시나리오마다 Gazebo를 띄우고 기록, 판정 |
| Modify `src/sim/gz_sim/CMakeLists.txt` | 새 스크립트 설치 |
| Create `docs/validation/lane-junction-spike/<실행 날짜 YYYY-MM-DD>/baseline.md` | Task 9 결과 |

---

### Task 1: 시험 공용 도우미 분리

**Files:**
- Create: `src/core/control/test/lane_sim.py`
- Modify: `src/core/control/test/test_lane_edge.py:11-156, 389-402`

순수 이동이다. 새 동작은 없다. 새 시험 파일들이 같은 렌더러와 폐루프를 쓰게 하려는 것이다.

- [ ] **Step 1: `lane_sim.py` 작성**

`test_lane_edge.py` 30-156행의 상수와 `World`, `offset_polyline`, `lane`, `core_command`, `drive`, `_distance_to_polyline`, 그리고 389-402행의 `_stl_world`, `START`를 옮긴다. 이름에서 앞 밑줄을 빼고, `drive`는 추종기를 인자로 받게 한다.

```python
"""Shared lane-following simulation for host tests: inverse-projection
renderer over a 1 mm floor raster, CORE line_follow law mirror, closed loop.

Moved verbatim from test_lane_edge.py so every lane test drives the same
simulated camera; see that file's module docstring for the measured grey
levels behind FLOOR, BODY and the paint dimming fit.
"""

import importlib.util
import math
from pathlib import Path

import cv2
import numpy as np

from control.sensing.camera_ground import simulation_ground_plane

ROOT = Path(__file__).resolve().parents[1]
H = 0.0925
LW = 0.025
CAM_X = 0.034
W, HT = 320, 180
FLOOR, BODY = 109, 218
DT = 0.2
KW = dict(bright_threshold=180, lane_half_width_m=H,
          roi_top_fraction=0.25, roi_bottom_fraction=0.75, washed_fraction=0.75)

GROUND = simulation_ground_plane(
    source="GAZEBO", simulation_enabled=True, use_sim_time=True,
    width_px=W, height_px=HT, height_m=0.060194,
    pitch_rad=math.radians(25.0), hfov_rad=1.1519, max_range_m=0.6)

_FWD = np.full((HT, W), np.nan)
_LAT = np.full((HT, W), np.nan)
for _r in range(HT):
    _d = GROUND.distance(_r)
    if _d is not None:
        _FWD[_r, :] = _d
        _LAT[_r, :] = [GROUND.lateral(_c, _r) for _c in range(W)]


class World:
    """Floor paint on a 1 mm raster; world x right, y up (ROS odom frame)."""

    def __init__(self, x0=-1.5, x1=1.5, y0=-1.0, y1=1.0):
        self.x0, self.y1 = x0, y1
        self.paint = np.zeros((int(round((y1 - y0) * 1000)), int(round((x1 - x0) * 1000))),
                              np.uint8)

    def px(self, points):
        pts = np.asarray(points, float)
        return np.stack([(pts[:, 0] - self.x0) * 1000, (self.y1 - pts[:, 1]) * 1000], axis=1)

    def line(self, points, width=LW):
        pts = np.rint(self.px(points) * 16).astype(np.int32)
        cv2.polylines(self.paint, [pts], False, 255, int(round(width * 1000)),
                      lineType=cv2.LINE_8, shift=4)
        return self

    def rect(self, cx, cy, sx, sy):
        corners = [(cx - sx / 2, cy - sy / 2), (cx + sx / 2, cy - sy / 2),
                   (cx + sx / 2, cy + sy / 2), (cx - sx / 2, cy + sy / 2)]
        cv2.fillPoly(self.paint, [np.rint(self.px(corners) * 16).astype(np.int32)], 255,
                     shift=4)
        return self

    def render(self, pose):
        x, y, yaw = pose
        forward = _FWD + CAM_X
        left = -_LAT
        wx = x + forward * math.cos(yaw) - left * math.sin(yaw)
        wy = y + forward * math.sin(yaw) + left * math.cos(yaw)
        valid = np.isfinite(wx)
        col = np.where(valid, np.rint((wx - self.x0) * 1000), -1).astype(int)
        row = np.where(valid, np.rint((self.y1 - wy) * 1000), -1).astype(int)
        inside = valid & (col >= 0) & (row >= 0) & (col < self.paint.shape[1]) \
            & (row < self.paint.shape[0])
        frame = np.full((HT, W), FLOOR, np.uint8)
        painted = np.zeros((HT, W), bool)
        painted[inside] = self.paint[row[inside], col[inside]] > 0
        frame[painted] = np.clip(np.rint(229.0 - 35.0 * _FWD[painted]), 0, 255)
        frame[139:, :] = BODY
        return frame


def offset_polyline(points, distance):
    """Left offset (+) of a polyline with mitred joints, like the track paint."""
    pts = np.asarray(points, float)
    d = np.diff(pts, axis=0)
    d /= np.linalg.norm(d, axis=1)[:, None]
    n = np.stack([-d[:, 1], d[:, 0]], axis=1)
    out = [pts[0] + distance * n[0]]
    for k in range(1, len(pts) - 1):
        m = n[k - 1] + n[k]
        m /= np.linalg.norm(m)
        out.append(pts[k] + distance * m / float(np.dot(m, n[k])))
    out.append(pts[-1] + distance * n[-1])
    return np.array(out)


def lane(centreline):
    world = World()
    world.line(offset_polyline(centreline, H)).line(offset_polyline(centreline, -H))
    return world


def core_command(obs):
    """CORE line_follow tick(): min_confidence 0.35, cruise 0.08, gain 0.8."""
    if obs is None or obs.confidence < 0.35:
        return 0.0, 0.0
    scale = max(0.0, min(1.0, (obs.confidence - 0.35) / 0.65))
    linear = 0.08 * scale * max(0.2, 1.0 - 0.65 * abs(obs.error))
    angular = max(-0.7, min(0.7, -0.8 * obs.error))
    return linear, angular


def drive(world, follower, *, steps, pose=(0.0, 0.0, 0.0), odom=True, stop=None):
    log = []
    for k in range(steps):
        obs = follower.update(k * DT, pose if odom else None, world.render(pose), GROUND, **KW)
        log.append((pose, obs, follower.state))
        v, w = core_command(obs)
        mid = pose[2] + w * DT / 2.0
        pose = (pose[0] + v * DT * math.cos(mid), pose[1] + v * DT * math.sin(mid),
                pose[2] + w * DT)
        if stop is not None and stop(pose, k):
            break
    return log, pose


def distance_to_polyline(point, polyline):
    p = np.asarray(point, float)
    best = math.inf
    for a, b in zip(polyline[:-1], polyline[1:]):
        ab = b - a
        t = max(0.0, min(1.0, float(np.dot(p - a, ab) / np.dot(ab, ab))))
        best = min(best, float(np.linalg.norm(p - (a + t * ab))))
    return best


def stl_world():
    path = ROOT / "map" / "map_v2_fleet" / "scripts" / "stl_scene.py"
    spec = importlib.util.spec_from_file_location("stl_scene_for_lane_sim", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scene = module.load_scene(next((ROOT / "map" / "map_v2_fleet").glob("260919*.STL")))
    world = World(-1.405, 1.405, -0.63, 0.63)
    for triangle in scene.lines:
        corners = np.rint(world.px([v[:2] for v in triangle]) * 16).astype(np.int32)
        cv2.fillPoly(world.paint, [corners], 255, shift=4)
    return world


START = (-1.26955, 0.24255, -math.pi / 2)
```

- [ ] **Step 2: `test_lane_edge.py`가 `lane_sim`을 쓰게 바꾼다**

옮긴 정의를 지우고 파일 위쪽에 다음을 넣는다.

```python
from lane_sim import (  # noqa: E402  (test-directory helper)
    BODY, CAM_X, DT, FLOOR, GROUND, H, HT, KW, LW, START, W, World,
    core_command, distance_to_polyline as _distance_to_polyline, lane,
    offset_polyline, stl_world as _stl_world,
)
from lane_sim import drive as _drive


def drive(world, *, steps, pose=(0.0, 0.0, 0.0), follower=None, odom=True, stop=None):
    return _drive(world, follower or LaneEdgeFollower(camera_x_offset_m=CAM_X),
                  steps=steps, pose=pose, odom=odom, stop=stop)
```

`World._px`를 쓰던 곳은 `World.px`로 바꾼다(`grep -n "_px(" src/core/control/test/test_lane_edge.py`). 시험 폴더는 pytest `rootdir` 규칙에 따라 `sys.path`에 들어가므로 `import lane_sim`이 동작한다. 동작하지 않으면 `src/core/control/test/conftest.py`에 다음 두 줄을 넣는다.

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
```

- [ ] **Step 3: 회귀 확인**

Run: `python -m pytest src/core/control/test/test_lane_edge.py -q`
Expected: 이전과 같은 개수로 전부 PASS(`git stash` 없이 `git show HEAD:src/core/control/test/test_lane_edge.py | grep -c "^def test_"`로 개수를 비교).

- [ ] **Step 4: 커밋**

```bash
git add src/core/control/test/lane_sim.py src/core/control/test/test_lane_edge.py src/core/control/test/conftest.py
git commit -m "test(control): share the lane simulation renderer and closed loop"
```
(`conftest.py`를 만들지 않았으면 add에서 뺀다.)

---

### Task 2: 차선 그래프 생성기

**Files:**
- Create: `src/core/control/map/map_v2_fleet/lane_rules.yaml`
- Create: `src/core/control/map/map_v2_fleet/scripts/lane_graph.py`
- Create (generated): `src/core/control/map/map_v2_fleet/lane_graph.yaml`
- Test: `src/core/control/test/test_lane_graph.py`

배경:
- 자동 능선 연결은 횡단보도에서 끊긴다. 막대가 차로 안에 있어서 능선 틈이 0.16 m를 넘는다(2026-09-22 측정).
- 그래서 규칙 파일에 도로마다 거친 앵커를 적고, 생성기가 각 점을 경계선 거리장의 능선에 스냅한다. 능선은 두 선에서 같은 거리인 점이다.
- 링은 능선점 원 맞춤으로 얻은 값을 규칙에 적는다: 중심 (-0.3357, 0.0011), 반지름 0.2514.
- 노드는 도로 끝 방향을 연장해 링 원과 만나는 점이다.

- [ ] **Step 1: 규칙 파일 작성**

```yaml
# 260919 lane network rules. Human-owned; lane_graph.py turns them into
# lane_graph.yaml. Coordinates: ROS map/odom frame, metres (world centred).
# Anchors are coarse (every ~8 cm, measured from the STL paint ridge on
# 2026-09-22); the generator snaps them to the exact centre between lines.
roundabout:
  centre: [-0.3357, 0.0011]     # circle fit to the ring's ridge points
  radius: 0.2514
  direction: ccw                # one-way; roads are two-way (user, 2026-09-22)
roads:
  west:                         # SW spoke -> bottom-west -> left lane -> top-west -> NW spoke
    two_way: true
    anchors:
      - [-0.559, -0.241]
      - [-0.597, -0.315]
      - [-0.635, -0.393]
      - [-0.673, -0.471]
      - [-0.739, -0.509]
      - [-0.911, -0.509]
      - [-1.079, -0.509]
      - [-1.209, -0.507]
      - [-1.269, -0.457]
      - [-1.2696, -0.300]
      - [-1.2696, 0.000]
      - [-1.2696, 0.300]
      - [-1.269, 0.457]
      - [-1.209, 0.507]
      - [-1.079, 0.509]
      - [-0.911, 0.509]
      - [-0.739, 0.509]
      - [-0.673, 0.471]
      - [-0.635, 0.393]
      - [-0.597, 0.315]
      - [-0.557, 0.241]
  east:                         # NE spoke -> top-east -> S-curve -> right loop -> bottom-east -> SE spoke
    two_way: true
    anchors:
      - [-0.153, 0.273]
      - [-0.127, 0.339]
      - [-0.103, 0.403]
      - [-0.079, 0.465]
      - [-0.015, 0.511]
      - [0.065, 0.511]
      - [0.145, 0.511]
      - [0.225, 0.507]
      - [0.293, 0.467]
      - [0.323, 0.401]
      - [0.327, 0.309]
      - [0.327, 0.227]
      - [0.339, 0.147]
      - [0.371, 0.077]
      - [0.423, 0.015]
      - [0.491, -0.029]
      - [0.565, -0.053]
      - [0.643, -0.055]
      - [0.719, -0.035]
      - [0.785, 0.001]
      - [0.855, 0.041]
      - [0.933, 0.059]
      - [1.005, 0.057]
      - [1.079, 0.035]
      - [1.145, -0.009]
      - [1.199, -0.071]
      - [1.231, -0.139]
      - [1.243, -0.211]
      - [1.235, -0.287]
      - [1.209, -0.359]
      - [1.165, -0.421]
      - [1.107, -0.467]
      - [1.035, -0.497]
      - [0.955, -0.509]
      - [0.793, -0.509]
      - [0.631, -0.509]
      - [0.469, -0.509]
      - [0.311, -0.509]
      - [0.197, -0.509]
      - [0.111, -0.509]
      - [0.027, -0.509]
      - [-0.057, -0.501]
      - [-0.097, -0.419]
      - [-0.127, -0.339]
      - [-0.157, -0.263]
parking:                        # inside the west block, entered at right angles from the left lane
  road: west
  entry: [-1.2696, 0.000]
  spot: [-1.000, 0.000, 0.0]    # x, y, yaw (facing +x into the block)
```

- [ ] **Step 2: 실패하는 시험 작성**

```python
"""260919 lane graph: rules anchors snapped to the STL paint (spec §4.1)."""

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

BUNDLE = Path(__file__).resolve().parents[1] / "map" / "map_v2_fleet"


def _module():
    spec = importlib.util.spec_from_file_location("lane_graph", BUNDLE / "scripts" / "lane_graph.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def graph():
    return yaml.safe_load((BUNDLE / "lane_graph.yaml").read_text(encoding="utf-8"))


def test_four_ring_nodes_and_six_segments(graph):
    assert sorted(graph["nodes"]) == ["NE", "NW", "SE", "SW"]
    assert sorted(graph["segments"]) == ["east", "ring_e", "ring_n", "ring_s", "ring_w", "west"]


def test_ring_is_one_way_ccw_and_roads_are_two_way(graph):
    seg = graph["segments"]
    for name in ("ring_n", "ring_w", "ring_s", "ring_e"):
        assert seg[name]["directions"] == ["forward"]
    for name in ("west", "east"):
        assert seg[name]["directions"] == ["forward", "reverse"]
    # CCW: each arc's heading turns left (positive cross product).
    for name in ("ring_n", "ring_w", "ring_s", "ring_e"):
        p = np.array(seg[name]["points"])
        a, b = p[1] - p[0], p[2] - p[1]
        assert a[0] * b[1] - a[1] * b[0] > 0


def test_segments_join_at_their_nodes(graph):
    nodes = {k: np.array(v) for k, v in graph["nodes"].items()}
    for name, seg in graph["segments"].items():
        p = np.array(seg["points"])
        assert np.linalg.norm(p[0] - nodes[seg["from"]]) < 1e-3, name
        assert np.linalg.norm(p[-1] - nodes[seg["to"]]) < 1e-3, name


def test_centrelines_keep_clear_of_the_boundary_lines(graph):
    """Every centre point 60-100 mm from the nearest boundary line, except
    within NODE_EXEMPT_M of a junction node where the lane mouth widens."""
    mod = _module()
    field = mod.LineField(mod.load_scene())
    assert mod.clearance_violations(graph, field) == []


def test_lengths_are_plausible(graph):
    seg = graph["segments"]
    ring = sum(seg[n]["length_m"] for n in ("ring_n", "ring_w", "ring_s", "ring_e"))
    assert ring == pytest.approx(2 * math.pi * graph["roundabout"]["radius"], rel=0.01)
    assert 1.9 < seg["west"]["length_m"] < 2.4
    assert 3.2 < seg["east"]["length_m"] < 4.2


def test_parking_spur_runs_from_the_left_lane_into_the_west_block(graph):
    park = graph["parking"]
    p = np.array(park["points"])
    assert park["road"] == "west"
    assert p[0] == pytest.approx([-1.2696, 0.0], abs=0.01)
    assert p[-1] == pytest.approx([-1.0, 0.0], abs=0.01)


def test_generator_output_is_checked_in_and_deterministic(tmp_path):
    mod = _module()
    out = tmp_path / "lane_graph.yaml"
    mod.write(mod.build(), out)
    assert out.read_bytes() == (BUNDLE / "lane_graph.yaml").read_bytes()
```

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest src/core/control/test/test_lane_graph.py -q`
Expected: FAIL. `lane_graph.yaml`과 `lane_graph.py`가 없어서 `FileNotFoundError`가 난다.

- [ ] **Step 4: 생성기 구현**

```python
#!/usr/bin/env python3
"""260919 lane graph: lane_rules.yaml anchors snapped to the STL paint.

Usage: python lane_graph.py   (writes ../lane_graph.yaml)

Each road's coarse anchors are densified to SPACING_M, every point is moved
along its normal (within SNAP_SEARCH_M) to the maximum of the distance to the
nearest boundary line -- the point equidistant from both lines -- then
smoothed and resampled. Crosswalk bars are not boundary lines (extent under
LINE_MIN_EXTENT_M) so they neither pull the snap nor fail the check. The
ring is the rules' circle; a node is where a road's end direction meets it.
ROS-free and byte-deterministic.
"""

import importlib.util
import math
from pathlib import Path

import cv2
import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
BUNDLE = HERE.parent
SOURCE = next(BUNDLE.glob("260919*.STL"))
RULES = BUNDLE / "lane_rules.yaml"
OUT = BUNDLE / "lane_graph.yaml"

RASTER_M = 0.002
#: Crosswalk bars are 0.121 m; boundary lines run for metres.
LINE_MIN_EXTENT_M = 0.25
SNAP_SEARCH_M = 0.04
SPACING_M = 0.01
SMOOTH_POINTS = 5
#: Lane centre to nearest line paint: half-width 92.5 mm minus half a line
#: width 12.5 mm is 80 mm on a straight; bends and joints vary it.
CLEAR_MIN_M, CLEAR_MAX_M = 0.060, 0.100
#: Lane mouths at the ring widen past CLEAR_MAX_M.
NODE_EXEMPT_M = 0.12
DECIMALS = 4
RING_ORDER = (("ring_n", "NE", "NW"), ("ring_w", "NW", "SW"),
              ("ring_s", "SW", "SE"), ("ring_e", "SE", "NE"))


def load_scene():
    spec = importlib.util.spec_from_file_location("stl_scene", HERE / "stl_scene.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_scene(SOURCE)


class LineField:
    """Distance (m) from a floor point to the nearest boundary-line paint."""

    def __init__(self, scene):
        self.x0, self.y1 = -scene.size_x / 2.0, scene.size_y / 2.0
        w = int(math.ceil(scene.size_x / RASTER_M)) + 1
        h = int(math.ceil(scene.size_y / RASTER_M)) + 1
        paint = np.zeros((h, w), np.uint8)
        for tri in scene.lines:
            pts = np.array([[(v[0] - self.x0) / RASTER_M, (self.y1 - v[1]) / RASTER_M]
                            for v in tri])
            cv2.fillPoly(paint, [np.rint(pts * 16).astype(np.int32)], 255, shift=4)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(paint, connectivity=8)
        keep = np.zeros(count, bool)
        for k in range(1, count):
            extent = max(stats[k, cv2.CC_STAT_WIDTH], stats[k, cv2.CC_STAT_HEIGHT]) * RASTER_M
            keep[k] = extent >= LINE_MIN_EXTENT_M
        lines = keep[labels]
        self.distance = cv2.distanceTransform(
            (~lines).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE) * RASTER_M

    def at(self, x, y):
        col = int(round((x - self.x0) / RASTER_M))
        row = int(round((self.y1 - y) / RASTER_M))
        if not (0 <= row < self.distance.shape[0] and 0 <= col < self.distance.shape[1]):
            return 0.0
        return float(self.distance[row, col])


def densify(points, spacing):
    pts = np.asarray(points, float)
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        n = max(1, int(math.ceil(np.linalg.norm(b - a) / spacing)))
        out.extend(a + (b - a) * k / n for k in range(1, n + 1))
    return np.array(out)


def resample(points, spacing):
    pts = np.asarray(points, float)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(2, int(round(s[-1] / spacing)) + 1)
    t = np.linspace(0.0, s[-1], n)
    return np.stack([np.interp(t, s, pts[:, 0]), np.interp(t, s, pts[:, 1])], axis=1)


def snap(points, field):
    pts = densify(points, SPACING_M)
    offsets = np.arange(-SNAP_SEARCH_M, SNAP_SEARCH_M + 1e-9, RASTER_M)
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        t = pts[i + 1] - pts[i - 1]
        t /= np.linalg.norm(t)
        normal = np.array([-t[1], t[0]])
        # Maximum clearance; ties go to the smallest move (flat ridge).
        best = max(offsets, key=lambda o: (round(field.at(*(pts[i] + o * normal)), 4), -abs(o)))
        out.append(pts[i] + best * normal)
    out.append(pts[-1])
    out = np.array(out)
    k = SMOOTH_POINTS // 2
    smooth = out.copy()
    for i in range(k, len(out) - k):
        smooth[i] = out[i - k:i + k + 1].mean(axis=0)
    return resample(smooth, SPACING_M)


def ring_meeting(end, before, centre, radius):
    """Where the road's end direction (before -> end) meets the ring circle."""
    d = np.asarray(end, float) - np.asarray(before, float)
    d /= np.linalg.norm(d)
    p = np.asarray(end, float) - np.asarray(centre, float)
    b = float(np.dot(d, p))
    c = float(np.dot(p, p)) - radius * radius
    disc = b * b - c
    if disc < 0:
        raise ValueError("road end direction misses the roundabout")
    t = -b - math.sqrt(disc)
    return np.asarray(end, float) + t * d


def _angle(point, centre):
    return math.atan2(point[1] - centre[1], point[0] - centre[0])


def arc(centre, radius, a0, a1):
    """CCW arc from angle a0 to a1 at SPACING_M."""
    while a1 <= a0:
        a1 += 2 * math.pi
    n = max(2, int(round(radius * (a1 - a0) / SPACING_M)) + 1)
    a = np.linspace(a0, a1, n)
    return np.stack([centre[0] + radius * np.cos(a), centre[1] + radius * np.sin(a)], axis=1)


def _length(points):
    return float(np.sum(np.linalg.norm(np.diff(np.asarray(points), axis=0), axis=1)))


def _round(points):
    return [[round(float(x), DECIMALS), round(float(y), DECIMALS)] for x, y in points]


def build(rules_path=RULES):
    rules = yaml.safe_load(Path(rules_path).read_text(encoding="utf-8"))
    ring = rules["roundabout"]
    if ring["direction"] != "ccw":
        raise ValueError("only a ccw roundabout is modelled")
    centre, radius = np.array(ring["centre"], float), float(ring["radius"])
    field = LineField(load_scene())
    nodes, segments = {}, {}
    ends = {"west": ("SW", "NW"), "east": ("NE", "SE")}
    for name, road in rules["roads"].items():
        anchors = np.array(road["anchors"], float)
        start = ring_meeting(anchors[0], anchors[1], centre, radius)
        end = ring_meeting(anchors[-1], anchors[-2], centre, radius)
        body = snap(anchors, field)
        points = np.vstack([[start], body, [end]])
        a, b = ends[name]
        nodes[a], nodes[b] = start, end
        segments[name] = {"from": a, "to": b,
                          "directions": ["forward", "reverse"] if road["two_way"] else ["forward"],
                          "points": points}
    for name, a, b in RING_ORDER:
        points = arc(centre, radius, _angle(nodes[a], centre), _angle(nodes[b], centre))
        points[0], points[-1] = nodes[a], nodes[b]
        segments[name] = {"from": a, "to": b, "directions": ["forward"], "points": points}
    park = rules["parking"]
    spur = resample([park["entry"], park["spot"][:2]], SPACING_M)
    graph = {
        "source_sha256": load_scene().source_sha256,
        "roundabout": {"centre": _round([centre])[0], "radius": round(radius, DECIMALS),
                       "direction": "ccw"},
        "nodes": {k: _round([v])[0] for k, v in sorted(nodes.items())},
        "segments": {},
        "parking": {"road": park["road"], "spot": [round(float(v), DECIMALS) for v in park["spot"]],
                    "points": _round(spur), "length_m": round(_length(spur), DECIMALS)},
    }
    for name in sorted(segments):
        seg = segments[name]
        graph["segments"][name] = {"from": seg["from"], "to": seg["to"],
                                   "directions": seg["directions"],
                                   "length_m": round(_length(seg["points"]), DECIMALS),
                                   "points": _round(seg["points"])}
    return graph


def clearance_violations(graph, field):
    nodes = [np.array(v) for v in graph["nodes"].values()]
    bad = []
    for name, seg in graph["segments"].items():
        for x, y in seg["points"]:
            if min(math.dist((x, y), n) for n in nodes) <= NODE_EXEMPT_M:
                continue
            clear = field.at(x, y)
            if not CLEAR_MIN_M <= clear <= CLEAR_MAX_M:
                bad.append((name, x, y, round(clear, 4)))
    return bad


def write(graph, path=OUT):
    text = yaml.safe_dump(graph, sort_keys=True, default_flow_style=None, width=100)
    Path(path).write_text("# Generated by scripts/lane_graph.py from lane_rules.yaml. Do not edit.\n"
                          + text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write(build())
```

- [ ] **Step 5: 생성하고 시험 확인**

Run:
```bash
python src/core/control/map/map_v2_fleet/scripts/lane_graph.py
python -m pytest src/core/control/test/test_lane_graph.py -q
```
Expected: 7 passed.

`test_centrelines_keep_clear_of_the_boundary_lines`가 실패하면 순서대로 확인한다:
1. 위반 목록의 위치를 `scratchpad`에 그림으로 그린다.
2. 위반이 앵커 오류 때문이면 규칙 앵커를 고친다. 곡률 큰 구간의 여유 폭 때문이면 `CLEAR_MIN_M`/`CLEAR_MAX_M`을 측정값과 함께 고친다.
3. 측정 근거는 커밋 메시지에 적는다. 선 위치(STL)는 바꾸지 않는다.

- [ ] **Step 6: `.gitattributes`와 설치**

`.gitattributes`에 `src/core/control/map/map_v2_fleet/lane_graph.yaml text eol=lf`를 추가한다. `setup.py`는 `map_v2_fleet` 전체를 이미 설치한다. `git check-attr eol -- src/core/control/map/map_v2_fleet/lane_graph.yaml`로 `eol: lf`를 확인한다.

- [ ] **Step 7: 커밋**

```bash
git add .gitattributes src/core/control/map/map_v2_fleet/lane_rules.yaml src/core/control/map/map_v2_fleet/scripts/lane_graph.py src/core/control/map/map_v2_fleet/lane_graph.yaml src/core/control/test/test_lane_graph.py
git commit -m "feat(map): 260919 lane graph from rules anchors snapped to the STL"
```

---

### Task 3: `LaneEdgeFollower` 리팩터 (동작 불변)

**Files:**
- Modify: `src/core/control/control/sensing/lane_bev.py:442-467, 553-594`
- Test: 기존 `src/core/control/test/test_lane_edge.py`(바뀌지 않아야 한다)

목적은 두 가지다. 하위 클래스가 목표점 선택만 바꿀 수 있게 하고, 띠(band)에서 룩어헤드를 찾는 부분을 재사용하게 하는 것이다.

- [ ] **Step 1: `_follow` 끝부분을 `_pursue`로 분리**

`lane_bev.py` 442-467행(`left_grid = self._one_line(...)`부터 `return LaneObservation(...)`까지)을 다음으로 바꾼다.

```python
        left_grid = self._one_line(self._left.grid(view, pose),
                                   None if left is None else labels == left)
        right_grid = self._one_line(self._right.grid(view, pose),
                                    None if right is None else labels == right)
        self.last.update(left_label=left, right_label=right, memory=left_grid,
                         right_memory=right_grid, fresh_length=fresh_length)
        return self._pursue(view, {
            "left": left, "right": right, "labels": labels, "stats": stats, "count": count,
            "left_grid": left_grid, "right_grid": right_grid, "fresh_length": fresh_length,
        }, half)

    def _pursue(self, view, found, half):
        """Target selection. edge_left: the left boundary leads; the right one
        of the same lane stands in where the left has left the field of view
        (convex left turns)."""
        target, supported, source = None, False, None
        for name, grid in (("LEFT", found["left_grid"]), ("RIGHT", found["right_grid"])):
            if not grid.any():
                continue
            target, supported = self._lookahead(view, grid, half)
            if supported:
                source = name
                break
        self.last.update(target=target, source=source, supported=supported)
        if target is None or not supported:
            return None
        confidence = min(1.0, found["fresh_length"] / LOOKAHEAD_M)
        confidence = max(confidence, MEMORY_CONFIDENCE)
        return self._observation(target, confidence)

    @staticmethod
    def _observation(target, confidence):
        x, y = target
        curvature = 2.0 * y / (x * x + y * y)
        return LaneObservation(error=error_for_curvature(curvature, confidence),
                               confidence=confidence)
```

- [ ] **Step 2: `_lookahead`를 띠 기반으로 일반화**

553-594행의 `_lookahead`를 다음 두 메서드로 바꾼다. 원래 `_lookahead(view, boundary_grid, half)`의 동작은 그대로 유지한다.

```python
    def _lookahead(self, view, boundary_grid, half):
        """(nearest supported path point at LOOKAHEAD_M..LOOKAHEAD_MAX_M,
        True), else (the LOOKAHEAD_M point or None, False).

        The iso-line runs on both sides of a boundary; the piece nearest the
        robot is the side it drives on.
        """
        distance = cv2.distanceTransform((boundary_grid == 0).astype(np.uint8),
                                         cv2.DIST_L2, cv2.DIST_MASK_PRECISE) * BEV_CELL_M
        offset = half - LANE_LINE_WIDTH_M / 2.0
        band = (np.abs(distance - offset) <= PATH_BAND_HALF_M).astype(np.uint8)
        return self._band_lookahead(
            view, band, lambda target: self._supported(view, boundary_grid, target))

    def _band_lookahead(self, view, band, supported):
        """Pursuit point on the band piece nearest the robot; `supported`
        decides whether a candidate may be pursued."""
        count, labels = cv2.connectedComponents(band, connectivity=8)
        if count <= 1:
            return None, False
        radius = np.hypot(view.x, view.y)
        in_band = labels > 0
        nearest = np.argmin(np.where(in_band, radius, np.inf))
        if radius.flat[nearest] > PATH_MAX_OFFSET_M:
            return None, False
        path = labels == labels.flat[nearest]
        self.last["path"] = path
        bearing = np.abs(np.arctan2(view.y, view.x))
        first = None
        steps = int(round((LOOKAHEAD_MAX_M - LOOKAHEAD_M) / LOOKAHEAD_STEP_M))
        for step in range(steps + 1):
            ring = path & (np.abs(radius - (LOOKAHEAD_M + step * LOOKAHEAD_STEP_M))
                           <= BEV_CELL_M)
            if not ring.any():
                continue
            candidates = np.where(ring, bearing, np.inf)
            best = np.argmin(candidates)
            if candidates.flat[best] > LOOKAHEAD_MAX_BEARING_RAD:
                continue
            close = ring & (np.hypot(view.x - view.x.flat[best],
                                     view.y - view.y.flat[best]) <= 0.01)
            target = (float(view.x[close].mean()), float(view.y[close].mean()))
            if supported(np.array(target)):
                return target, True
            if first is None:
                first = target
        return first, False
```

- [ ] **Step 3: 회귀 확인**

Run: `python -m pytest src/core/control/test/test_lane_edge.py src/core/control/test/test_lane_corner.py -q`
Expected: 리팩터 전과 같은 개수로 전부 PASS. 전체 한 바퀴 시험(`test_full_lap_of_the_260919_track_returns_to_the_start`)도 포함한다.

- [ ] **Step 4: 커밋**

```bash
git add src/core/control/control/sensing/lane_bev.py
git commit -m "refactor(control): split edge-follower target choice from boundary finding"
```

---

### Task 4: 좌우 경계 가운데선 추종기 (`LaneBoundaryTracker`)

**Files:**
- Create: `src/core/control/control/sensing/lane_boundaries.py`
- Test: `src/core/control/test/test_lane_boundaries.py`

spec §4.2의 강등 사다리 중 1(BOTH), 2(ONE), 3(MEMORY), 5(STOP)를 만든다. 4(기동)는 Plan 2에서 A와 B가 채운다.

- [ ] **Step 1: 실패하는 시험 작성**

```python
"""Left AND right boundaries, centre-line following, fallback ladder (spec §4.2)."""

import math

import numpy as np
import pytest

from control.sensing.lane_boundaries import LaneBoundaryTracker, TIERS
from lane_sim import (CAM_X, DT, GROUND, H, KW, START, World, core_command,
                      distance_to_polyline, drive, lane, offset_polyline, stl_world)


def tracker():
    return LaneBoundaryTracker(camera_x_offset_m=CAM_X)


STRAIGHT = np.array([(-1.0, 0.0), (1.4, 0.0)])


def test_tiers_are_the_spec_ladder():
    assert TIERS == ("BOTH", "ONE", "MEMORY", "STOP")


def test_straight_lane_uses_both_lines_and_holds_the_centre():
    t = tracker()
    log, pose = drive(lane(STRAIGHT), t, steps=60, pose=(-0.9, 0.0, 0.0))
    assert t.tier == "BOTH"
    assert max(abs(p[1]) for p, _, _ in log[5:]) < 0.005


def test_offset_start_converges_to_the_centre_between_the_lines():
    t = tracker()
    log, pose = drive(lane(STRAIGHT), t, steps=90, pose=(-0.9, -0.03, 0.0))
    assert abs(pose[1]) < 0.006
    assert t.tier == "BOTH"


def test_centre_is_midway_even_when_the_lane_is_narrower_than_assumed():
    """The midpoint uses both lines: a 150 mm lane (h=0.075 real vs 0.0925
    assumed) is still followed at its middle, where a one-line offset would
    sit 17.5 mm off-centre."""
    world = World().line(offset_polyline(STRAIGHT, 0.075)).line(offset_polyline(STRAIGHT, -0.075))
    t = tracker()
    log, pose = drive(world, t, steps=90, pose=(-0.9, 0.0, 0.0))
    assert abs(pose[1]) < 0.006


def test_one_line_visible_falls_to_tier_one():
    """Only the left line after x=0.2: the tracker keeps a half-width off it."""
    world = World().line(offset_polyline(STRAIGHT, H)).line(
        offset_polyline(np.array([(-1.0, 0.0), (0.2, 0.0)]), -H))
    t = tracker()
    tiers = []
    log, pose = drive(world, t, steps=120, pose=(-0.9, 0.0, 0.0),
                      stop=lambda p, k: tiers.append(t.tier) or p[0] > 1.0)
    assert "BOTH" in tiers and "ONE" in tiers
    assert max(abs(p[1]) for p, _, _ in log) < 0.02


def test_lost_lines_step_down_through_memory_to_stop():
    world = World().line(offset_polyline(np.array([(-1.0, 0.0), (-0.3, 0.0)]), H)).line(
        offset_polyline(np.array([(-1.0, 0.0), (-0.3, 0.0)]), -H))
    t = tracker()
    tiers = []
    drive(world, t, steps=200, pose=(-0.9, 0.0, 0.0), stop=lambda p, k: tiers.append(t.tier) or False)
    assert tiers.index("MEMORY") < tiers.index("STOP")
    assert tiers[-1] == "STOP"


def test_no_ground_or_no_odometry_is_no_output():
    t = tracker()
    frame = lane(STRAIGHT).render((-0.9, 0.0, 0.0))
    assert t.update(0.0, None, frame, GROUND, **KW) is None
    assert t.update(0.0, (-0.9, 0.0, 0.0), frame, None, **KW) is None
    assert t.tier == "STOP"


def test_crosswalk_bars_between_the_lines_are_not_boundaries():
    world = lane(STRAIGHT)
    for y in (-0.05, -0.017, 0.017, 0.05):
        world.rect(0.2, y, 0.121, 0.02)
    t = tracker()
    log, pose = drive(world, t, steps=120, pose=(-0.9, 0.0, 0.0), stop=lambda p, k: p[0] > 0.7)
    assert max(abs(p[1]) for p, _, _ in log) < 0.015


def test_opening_on_one_side_raises_the_junction_signal():
    """The right line ends while the left continues: a mouth opens on the right."""
    world = World().line(offset_polyline(STRAIGHT, H)).line(
        offset_polyline(np.array([(-1.0, 0.0), (0.0, 0.0)]), -H))
    t = tracker()
    signals = []
    drive(world, t, steps=100, pose=(-0.9, 0.0, 0.0),
          stop=lambda p, k: signals.append(t.last.get("junction")) or p[0] > 0.3)
    assert "RIGHT_OPENS" in signals


def test_west_loop_both_directions_stay_in_the_lane():
    """Left lane of the 260919 track, driven south (start) and north (reverse):
    left/right roles swap, the centre rule does not care."""
    world = stl_world()
    centre_x = -1.2696
    for yaw, y0, stop_y in ((-math.pi / 2, 0.30, -0.35), (math.pi / 2, -0.30, 0.35)):
        t = tracker()
        log, pose = drive(world, t, steps=120, pose=(centre_x, y0, yaw),
                          stop=lambda p, k: (p[1] < stop_y) if yaw < 0 else (p[1] > stop_y))
        assert max(abs(p[0] - centre_x) for p, _, _ in log) < 0.02
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/core/control/test/test_lane_boundaries.py -q`
Expected: FAIL (`ModuleNotFoundError: control.sensing.lane_boundaries`)

- [ ] **Step 3: 구현**

```python
"""Subject: both lane boundaries, centre-line following with a fallback ladder.

Builds on lane_bev's bird's-eye view and its left/right boundary memories
(LaneEdgeFollower finds and remembers both lines); only the target choice
differs (spec 2026-09-22 lane-network junction spike §4.2):

  BOTH    both boundaries seen this frame: pursue the centre line, the
          locus equidistant from the two (it needs no lane-width assumption)
  ONE     one boundary seen: pursue its half-width iso-line (lane_bev rule)
  MEMORY  none seen, remembered ones still inside lane_bev's travel and
          clock limits: pursue them at MEMORY_CONFIDENCE
  STOP    nothing: no output, CORE stops
Tier 4 (a committed manoeuvre) belongs to the junction prototypes.

Junction signal (for the overlay and the prototypes, never a decision):
LEFT_OPENS / RIGHT_OPENS when both boundaries are remembered but only the
other side is seen, BRANCH when a fresh line of boundary length belongs to
neither side.
"""

import cv2
import numpy as np

from .lane import LANE_LINE_WIDTH_M, LaneObservation
from .lane_bev import (
    BEV_CELL_M, LOOKAHEAD_M, MEMORY_CONFIDENCE, MIN_BOUNDARY_LENGTH_M, LaneEdgeFollower,
)

TIERS = ("BOTH", "ONE", "MEMORY", "STOP")
#: Centre band: equal distance to both lines within this many cells.
CENTRE_BAND_CELLS = 2
#: The centre locus counts only between the lines, not far beyond them.
CENTRE_MAX_REACH = 1.5


class LaneBoundaryTracker(LaneEdgeFollower):
    """Centre-line follower over both boundaries; see the module docstring."""

    def __init__(self, *, camera_x_offset_m: float = 0.0) -> None:
        super().__init__(camera_x_offset_m=camera_x_offset_m, corner_handoff=False)
        self.tier = "STOP"

    @property
    def state(self) -> str:
        return self.tier

    def update(self, now_s, pose, bgr, ground, **kwargs) -> LaneObservation | None:
        self.tier = "STOP"
        self.last = {}
        return super().update(now_s, pose, bgr, ground, **kwargs)

    def _pursue(self, view, found, half):
        left_seen, right_seen = found["left"] is not None, found["right"] is not None
        left_grid, right_grid = found["left_grid"], found["right_grid"]
        self.last["junction"] = self._junction(found, left_seen, right_seen)
        target, supported = None, False
        if left_seen and right_seen:
            target, supported = self._centre(view, left_grid, right_grid, half)
            if supported:
                self.tier = "BOTH"
        if not supported:
            for seen, grid in ((left_seen, left_grid), (right_seen, right_grid)):
                if seen and grid.any():
                    target, supported = self._lookahead(view, grid, half)
                    if supported:
                        self.tier = "ONE"
                        break
        if not supported and not (left_seen or right_seen):
            if left_grid.any() and right_grid.any():
                target, supported = self._centre(view, left_grid, right_grid, half)
            for grid in (left_grid, right_grid):
                if supported:
                    break
                if grid.any():
                    target, supported = self._lookahead(view, grid, half)
            if supported:
                self.tier = "MEMORY"
        self.last.update(target=target, supported=supported, tier=self.tier)
        if target is None or not supported:
            self.tier = "STOP"
            self.last["tier"] = "STOP"
            return None
        if self.tier == "MEMORY":
            confidence = MEMORY_CONFIDENCE
        else:
            confidence = max(min(1.0, found["fresh_length"] / LOOKAHEAD_M), MEMORY_CONFIDENCE)
        return self._observation(target, confidence)

    def _centre(self, view, left_grid, right_grid, half):
        dl = cv2.distanceTransform((left_grid == 0).astype(np.uint8),
                                   cv2.DIST_L2, cv2.DIST_MASK_PRECISE) * BEV_CELL_M
        dr = cv2.distanceTransform((right_grid == 0).astype(np.uint8),
                                   cv2.DIST_L2, cv2.DIST_MASK_PRECISE) * BEV_CELL_M
        reach = CENTRE_MAX_REACH * half
        band = ((np.abs(dl - dr) <= CENTRE_BAND_CELLS * BEV_CELL_M)
                & (dl <= reach) & (dr <= reach)).astype(np.uint8)
        self.last["centre_band"] = band

        def supported(target):
            return (self._supported(view, left_grid, target)
                    and self._supported(view, right_grid, target))

        return self._band_lookahead(view, band, supported)

    def _junction(self, found, left_seen, right_seen):
        remembered = bool(self._left) and bool(self._right)
        if remembered and left_seen and not right_seen:
            return "RIGHT_OPENS"
        if remembered and right_seen and not left_seen:
            return "LEFT_OPENS"
        labels, stats, count = found["labels"], found["stats"], found["count"]
        for label in range(1, count):
            if label in (found["left"], found["right"]):
                continue
            if self._length(stats, label) >= MIN_BOUNDARY_LENGTH_M:
                return "BRANCH"
        return None
```

`LANE_LINE_WIDTH_M`을 쓰지 않으면 import에서 뺀다(flake8).

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/core/control/test/test_lane_boundaries.py -q`
Expected: 11 passed.

실패하면 합성 프레임과 `t.last`(`centre_band`, `memory`, `right_memory`, `path`)를 `scratchpad`에 그림으로 떨궈서 원인을 본다. 문턱을 바꾸면 측정 근거를 시험 docstring에 적는다.
- `test_west_loop_both_directions`가 역방향에서 실패하면, 원인은 대개 오른쪽 선이 왼쪽 기억 기준으로만 탐색되는 것이다(`_right_boundary`).
- 그 경우 대칭 탐색 `_left_boundary`를 추가한다. `_right_boundary`와 같은 코드에서 `view.y` 부호 검사만 반대로 한다.
- 그리고 `_follow`의 `if right is None and self._left:` 다음에, 하위 클래스에서만 켜지는 훅 `self._find_left_from_right(...)`를 둔다. `edge_left` 동작은 바뀌면 안 된다.

- [ ] **Step 5: 전체 회귀**

Run: `python -m pytest src/core/control/test/ -q`
Expected: 기존 개수 + 11, 실패 0.

- [ ] **Step 6: 커밋**

```bash
git add src/core/control/control/sensing/lane_boundaries.py src/core/control/test/test_lane_boundaries.py
git commit -m "feat(control): centre-line lane following over both boundaries with a fallback ladder"
```

---

### Task 5: 관측 노드에 `centre` 모드 연결

**Files:**
- Modify: `src/core/control/control/line_observer_node.py:29, 55-60, 76-80, 106-108, 182-197`
- Modify: `src/core/control/config/line_follow.yaml`
- Modify: `src/sim/gz_sim/launch/map_v2_fleet_lane.launch.py`
- Test: `src/core/control/test/test_line_observer_wiring.py`, `src/sim/gz_sim/test/test_map_v2_fleet_launch.py`

- [ ] **Step 1: 실패하는 배선 시험 추가**

`test_line_observer_wiring.py` 끝에 추가한다.

```python
def test_centre_mode_uses_the_boundary_tracker_with_fresh_odometry():
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "LaneBoundaryTracker" in source
    assert "mode in ('lane', 'edge_left', 'centre')" in source
    assert "self._centre_tracker.update(" in source
    assert source.count("pose_if_fresh(self._odom_pose, self._odom_stamp") == 3
```

`test_map_v2_fleet_launch.py` 끝에 추가한다.

```python
def test_launch_exposes_mode_and_spawn_for_the_junction_harness():
    source = LAUNCH.read_text(encoding="utf-8")
    for arg in ('"camera_lane_mode"', '"spawn_x"', '"spawn_y"', '"spawn_yaw"', '"debug_overlay"'):
        assert f"DeclareLaunchArgument({arg}" in source
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/core/control/test/test_line_observer_wiring.py src/sim/gz_sim/test/test_map_v2_fleet_launch.py -q`
Expected: 새 시험 2개 FAIL

- [ ] **Step 3: 노드 구현**

- import: `from .sensing.lane_boundaries import LaneBoundaryTracker`
- 모드 주석에 한 줄 추가: `# 'centre' follows the centre line between both boundaries (fallback ladder).`
- `__init__`에서 `_edge_follower` 다음에 추가:
  ```python
          self._centre_tracker = LaneBoundaryTracker(
              camera_x_offset_m=float(self.get_parameter('camera_x_offset_m').value))
  ```
- odom 구독 조건: `if mode in ('lane', 'edge_left', 'centre'):`
- `_on_camera`: `elif mode in ('lane', 'edge_left'):`을 `elif mode in ('lane', 'edge_left', 'centre'):`로 바꾸고, `if mode == 'edge_left':` 앞에 다음을 넣는다.
  ```python
                  if mode == 'centre':
                      image_stamp = (float(msg.header.stamp.sec)
                                     + float(msg.header.stamp.nanosec) * 1e-9)
                      observation = self._centre_tracker.update(
                          image_stamp,
                          pose_if_fresh(self._odom_pose, self._odom_stamp, image_stamp),
                          frame, ground, **lane_kwargs)
                  elif mode == 'edge_left':
  ```
  원래의 `if mode == 'edge_left':`는 `elif`가 된다.

- [ ] **Step 4: launch 인자**

`map_v2_fleet_lane.launch.py`에서 다음을 바꾼다.
- 스폰 좌표를 `LaunchConfiguration`으로 바꾸고 선언한다:
  ```python
          DeclareLaunchArgument("spawn_x", default_value="-1.26955"),
          DeclareLaunchArgument("spawn_y", default_value="0.24255"),
          DeclareLaunchArgument("camera_lane_mode", default_value="edge_left"),
          DeclareLaunchArgument("debug_overlay", default_value="false"),
  ```
- simulation include의 `"spawn_x": "-1.26955"`, `"spawn_y": "0.24255"`를 `LaunchConfiguration("spawn_x")`, `LaunchConfiguration("spawn_y")`로 바꾼다.
- line_observer 파라미터의 `"camera_lane_mode": "edge_left"`를 `LaunchConfiguration("camera_lane_mode")`로 바꾼다.
- `"debug_overlay"`를 추가한다: `ParameterValue(LaunchConfiguration("debug_overlay"), value_type=bool)`. `from launch_ros.parameter_descriptions import ParameterValue`도 추가한다.

기존 시험이 `'"spawn_x": "-1.26955"'` 같은 문자열을 찾으면, 시험을 기본값 선언 문자열(`default_value="-1.26955"`)로 바꾼다. 기본 동작은 그대로다.

- [ ] **Step 5: yaml 기본값**

`line_follow.yaml`의 line_observer_node 블록에 추가한다.
```yaml
    debug_overlay: false            # line/debug/compressed (observation only)
    debug_overlay_max_hz: 5.0
    debug_lane_graph: ""            # optional lane_graph.yaml for the map panel
```

- [ ] **Step 6: 통과 확인과 커밋**

Run: `python -m pytest src/core/control/test/ src/sim/gz_sim/test/ -q`
Expected: 전부 PASS

```bash
git add src/core/control/control/line_observer_node.py src/core/control/config/line_follow.yaml src/sim/gz_sim/launch/map_v2_fleet_lane.launch.py src/core/control/test/test_line_observer_wiring.py src/sim/gz_sim/test/test_map_v2_fleet_launch.py
git commit -m "feat(control): centre camera lane mode and harness-ready launch arguments"
```

---

### Task 6: 인식 오버레이 렌더러 (ROS-free)

**Files:**
- Create: `src/core/control/control/sensing/lane_debug.py`
- Test: `src/core/control/test/test_lane_debug.py`

패널은 4칸이고 각 320×180이다. 전체는 640×360 BGR이다.
1. 카메라: 원본 프레임에 임계 마스크를 빨갛게 겹친다.
2. BEV: 전방이 위다. 도색은 회색, 왼쪽 경계는 초록, 오른쪽 경계는 파랑, 가운데 띠는 노랑, 목표점은 자홍, 로봇은 흰 삼각형이다.
3. 상태 글자: 모드, tier, 교차 신호, 오차, 신뢰도, 소스.
4. 지도: 그래프 폴리라인 위에 odom 자세를 그린다. Gazebo에서는 odom이 참값이라는 사실을 글자로 표시한다.

- [ ] **Step 1: 실패하는 시험 작성**

```python
"""Perception overlay renderer (spec §4.3): what the robot saw and chose."""

import numpy as np

from control.sensing.lane import LaneObservation
from control.sensing.lane_boundaries import LaneBoundaryTracker
from control.sensing.lane_debug import PANEL_H, PANEL_W, render_debug
from lane_sim import CAM_X, GROUND, KW, lane

STRAIGHT = np.array([(-1.0, 0.0), (1.4, 0.0)])


def _frame_and_tracker():
    t = LaneBoundaryTracker(camera_x_offset_m=CAM_X)
    world = lane(STRAIGHT)
    pose = (-0.9, 0.0, 0.0)
    obs = None
    for k in range(3):
        frame = world.render(pose)
        obs = t.update(k * 0.2, pose, frame, GROUND, **KW)
    return frame, t, obs, pose


def test_overlay_is_four_panels():
    frame, t, obs, pose = _frame_and_tracker()
    img = render_debug(frame, t, obs, mode="centre", pose=pose)
    assert img.shape == (2 * PANEL_H, 2 * PANEL_W, 3)
    assert img.dtype == np.uint8


def test_birds_eye_panel_draws_left_green_and_right_blue():
    frame, t, obs, pose = _frame_and_tracker()
    img = render_debug(frame, t, obs, mode="centre", pose=pose)
    bev = img[:PANEL_H, PANEL_W:]
    green = (bev[:, :, 1] > 180) & (bev[:, :, 0] < 100) & (bev[:, :, 2] < 100)
    blue = (bev[:, :, 0] > 180) & (bev[:, :, 1] < 140) & (bev[:, :, 2] < 100)
    assert green.sum() > 50 and blue.sum() > 50


def test_status_panel_is_not_blank_and_map_panel_shows_the_pose():
    frame, t, obs, pose = _frame_and_tracker()
    graph = {"segments": {"west": {"points": [[-1.2, -0.5], [-1.2, 0.5]]}}}
    img = render_debug(frame, t, obs, mode="centre", pose=pose, graph=graph)
    status = img[PANEL_H:, :PANEL_W]
    assert (status > 200).sum() > 100          # white text drawn
    mapp = img[PANEL_H:, PANEL_W:]
    assert (mapp[:, :, 2] > 200).sum() > 10    # red pose marker


def test_no_observation_still_renders_and_says_stop():
    frame, t, _, pose = _frame_and_tracker()
    img = render_debug(frame, t, None, mode="centre", pose=None)
    assert img.shape == (2 * PANEL_H, 2 * PANEL_W, 3)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/core/control/test/test_lane_debug.py -q`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
"""Subject: a four-panel picture of one lane-following decision.

Observation only: it reads a follower's `last` intermediate results and
never feeds back into perception or motion.
  camera   the frame with the paint threshold tinted red
  bev      bird's-eye grid, forward up: paint grey, left boundary green,
           right boundary blue, centre band yellow, target magenta
  status   mode, ladder tier, junction signal, error and confidence
  map      lane graph with the odometry pose (in Gazebo odom is ground truth;
           on a Device it is only the robot's own estimate -- labelled)
"""

import math

import cv2
import numpy as np

PANEL_W, PANEL_H = 320, 180
_GREEN, _BLUE, _YELLOW, _MAGENTA, _GREY = (60, 220, 60), (230, 120, 40), (40, 220, 240), \
    (230, 60, 230), (120, 120, 120)


def _fit(img):
    return cv2.resize(img, (PANEL_W, PANEL_H), interpolation=cv2.INTER_NEAREST)


def _camera(frame, threshold):
    bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR) if frame.ndim == 2 else frame.copy()
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    tint = bgr.copy()
    tint[gray > threshold] = (40, 40, 230)
    return _fit(cv2.addWeighted(bgr, 0.55, tint, 0.45, 0.0))


def _bev(last):
    paint = last.get("paint")
    if paint is None:
        return np.zeros((PANEL_H, PANEL_W, 3), np.uint8)
    img = np.zeros(paint.shape + (3,), np.uint8)
    img[paint > 0] = _GREY
    for key, colour in (("memory", _GREEN), ("right_memory", _BLUE)):
        grid = last.get(key)
        if grid is not None:
            img[grid > 0] = colour
    band = last.get("centre_band")
    if band is None:
        band = last.get("path")
    if band is not None:
        img[band > 0] = _YELLOW
    img = img[::-1, :]                       # forward (row index up) at the top
    size = max(img.shape[:2])
    square = np.zeros((size, size, 3), np.uint8)
    square[:img.shape[0], (size - img.shape[1]) // 2:(size - img.shape[1]) // 2 + img.shape[1]] = img
    panel = cv2.resize(square, (PANEL_H, PANEL_H), interpolation=cv2.INTER_NEAREST)
    out = np.zeros((PANEL_H, PANEL_W, 3), np.uint8)
    out[:, (PANEL_W - PANEL_H) // 2:(PANEL_W + PANEL_H) // 2] = panel
    return out, size


def _mark_target(panel_and_size, last, view):
    panel, size = panel_and_size
    target = last.get("target")
    if target is None or view is None:
        return panel
    i, j = view.cell(*target)
    row = (view.rows - 1 - i) * PANEL_H / size
    col = (PANEL_W - PANEL_H) / 2 + (j + (size - view.cols) / 2) * PANEL_H / size
    cv2.circle(panel, (int(col), int(row)), 5, _MAGENTA, -1)
    return panel


def _status(mode, tier, junction, observation, source):
    panel = np.full((PANEL_H, PANEL_W, 3), 24, np.uint8)
    lines = [f"mode   {mode}", f"tier   {tier}", f"signal {junction or '-'}"]
    if observation is None:
        lines += ["output NONE (CORE stops)"]
    else:
        lines += [f"error  {observation.error:+.3f}", f"conf   {observation.confidence:.2f}"]
    lines += [f"source {source or '-'}"]
    for k, text in enumerate(lines):
        cv2.putText(panel, text, (10, 28 + 26 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (240, 240, 240), 1, cv2.LINE_AA)
    return panel


def _map(graph, pose, pose_label):
    panel = np.full((PANEL_H, PANEL_W, 3), 30, np.uint8)
    sx, sy = PANEL_W / 2.9, PANEL_H / 1.35
    scale = min(sx, sy)

    def px(x, y):
        return int(PANEL_W / 2 + x * scale), int(PANEL_H / 2 - y * scale)

    for seg in (graph or {}).get("segments", {}).values():
        pts = np.array([px(x, y) for x, y in seg["points"]], np.int32)
        cv2.polylines(panel, [pts], False, (170, 170, 170), 1, cv2.LINE_AA)
    if pose is not None:
        x, y, yaw = pose
        tip = px(x + 0.06 * math.cos(yaw), y + 0.06 * math.sin(yaw))
        cv2.circle(panel, px(x, y), 5, (40, 40, 240), -1)
        cv2.line(panel, px(x, y), tip, (40, 40, 240), 2)
    cv2.putText(panel, pose_label, (8, PANEL_H - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (200, 200, 200), 1, cv2.LINE_AA)
    return panel


def render_debug(frame, follower, observation, *, mode, pose=None, graph=None,
                 bright_threshold=180, pose_label="odom pose"):
    last = dict(getattr(follower, "last", {}) or {})
    view = getattr(follower, "_view", None)
    top = np.hstack([_camera(frame, bright_threshold),
                     _mark_target(_bev(last), last, view) if last.get("paint") is not None
                     else np.zeros((PANEL_H, PANEL_W, 3), np.uint8)])
    tier = last.get("tier") or getattr(follower, "state", "-")
    bottom = np.hstack([_status(mode, tier, last.get("junction"), observation, last.get("source")),
                        _map(graph, pose, pose_label)])
    return np.vstack([top, bottom])
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/core/control/test/test_lane_debug.py -q`
Expected: 4 passed.

`_bev`는 `(panel, size)`를 돌려준다. `_mark_target`이 그것을 받는다. `paint`가 없는 분기에서는 빈 패널을 직접 만든다.

- [ ] **Step 5: 커밋**

```bash
git add src/core/control/control/sensing/lane_debug.py src/core/control/test/test_lane_debug.py
git commit -m "feat(control): four-panel lane perception overlay renderer"
```

---

### Task 7: 오버레이 발행과 녹화기

**Files:**
- Modify: `src/core/control/control/line_observer_node.py`
- Create: `src/sim/gz_sim/scripts/record_debug.py`
- Modify: `src/sim/gz_sim/CMakeLists.txt:38-46`
- Test: `src/core/control/test/test_line_observer_wiring.py`, `src/sim/gz_sim/test/test_gz_package_contract.py`

- [ ] **Step 1: 실패하는 배선 시험**

`test_line_observer_wiring.py`에 추가한다.

```python
def test_debug_overlay_is_off_by_default_and_publishes_only_an_image():
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    config = yaml.safe_load((ROOT / "config/line_follow.yaml").read_text(encoding="utf-8"))
    params = config["/**/line_observer_node"]["ros__parameters"]
    assert params["debug_overlay"] is False
    assert "CompressedImage, 'line/debug/compressed'" in source
    assert "render_debug(" in source
    assert "Twist" not in source and "'cmd_vel'" not in source
```

`test_gz_package_contract.py` 쪽은 CMake 설치 목록에 새 스크립트가 들어갔는지 본다.

```python
def test_junction_tools_are_installed():
    from pathlib import Path
    cmake = (Path(__file__).resolve().parents[1] / "CMakeLists.txt").read_text(encoding="utf-8")
    for script in ("scripts/record_debug.py", "scripts/junction_score.py", "scripts/junction_harness.py"):
        assert script in cmake
```
(이 시험은 Task 8이 끝나야 통과한다. Task 7에서는 `record_debug.py` 줄만 먼저 확인하도록 `for` 목록을 하나로 시작하고, Task 8에서 둘을 더한다.)

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/core/control/test/test_line_observer_wiring.py src/sim/gz_sim/test/test_gz_package_contract.py -q`
Expected: 새 시험 FAIL

- [ ] **Step 3: 노드 발행 구현**

- import: `from sensor_msgs.msg import CompressedImage, Image`, `import cv2`, `import yaml`, `from .sensing.lane_debug import render_debug`
- `__init__`:
  ```python
          self.declare_parameter('debug_overlay', False, _READ_ONLY)
          self.declare_parameter('debug_overlay_max_hz', 5.0)
          self.declare_parameter('debug_lane_graph', '')
          self._debug_pub = None
          self._debug_last_s = None
          self._debug_graph = None
          if bool(self.get_parameter('debug_overlay').value):
              self._debug_pub = self.create_publisher(
                  CompressedImage, 'line/debug/compressed', 2)
              path = str(self.get_parameter('debug_lane_graph').value)
              if path:
                  with open(path, encoding='utf-8') as handle:
                      self._debug_graph = yaml.safe_load(handle)
  ```
- `_on_camera` 끝, `self._publish(...)` 바로 뒤에 추가:
  ```python
          self._publish_debug(msg, frame if 'frame' in locals() else None, observation)
  ```
  그리고 메서드 추가:
  ```python
      def _publish_debug(self, msg, frame, observation) -> None:
          """Observation only: a picture of the decision just published."""
          if self._debug_pub is None or frame is None:
              return
          stamp = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
          period = 1.0 / max(0.1, float(self.get_parameter('debug_overlay_max_hz').value))
          if self._debug_last_s is not None and 0.0 <= stamp - self._debug_last_s < period:
              return
          self._debug_last_s = stamp
          mode = str(self.get_parameter('camera_lane_mode').value)
          follower = {'centre': self._centre_tracker, 'edge_left': self._edge_follower}.get(mode)
          if follower is None:
              return
          image = render_debug(
              frame, follower, observation, mode=mode,
              pose=pose_if_fresh(self._odom_pose, self._odom_stamp, stamp),
              graph=self._debug_graph,
              bright_threshold=int(self.get_parameter('camera_bright_threshold').value))
          ok, data = cv2.imencode('.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
          if not ok:
              return
          out = CompressedImage()
          out.header = msg.header
          out.format = 'jpeg; overlay=lane-debug-v1'
          out.data = data.tobytes()
          self._debug_pub.publish(out)
  ```
  `frame`은 `try` 블록 안에서 정의되므로 `_on_camera` 첫 줄에 `frame = None`을 두고 `locals()` 검사는 빼는 편이 낫다. 그 경우 호출은 `self._publish_debug(msg, frame, observation)`이다.
- launch(`map_v2_fleet_lane.launch.py`) line_observer 파라미터에 `"debug_lane_graph": os.path.join(control_share, "map", "map_v2_fleet", "lane_graph.yaml")`를 추가한다.

- [ ] **Step 4: 녹화기 작성**

```python
#!/usr/bin/env python3
"""Record line/debug/compressed to <out>/overlay.mp4 plus frames.jsonl.

Usage: ros2 run gz_sim record_debug.py --out DIR [--seconds 180] [--fps 5]
Observation only; subscribes, never publishes.
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=180.0)
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--topic", default="line/debug/compressed")
    args, ros_args = parser.parse_known_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    rclpy.init(args=ros_args)
    node = Node("lane_debug_recorder")
    state = {"writer": None, "count": 0}
    log = (args.out / "frames.jsonl").open("w", encoding="utf-8")

    def on_image(msg):
        image = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return
        if state["writer"] is None:
            state["writer"] = cv2.VideoWriter(
                str(args.out / "overlay.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), args.fps,
                (image.shape[1], image.shape[0]))
        state["writer"].write(image)
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        log.write(json.dumps({"index": state["count"], "stamp": stamp}) + "\n")
        state["count"] += 1

    node.create_subscription(CompressedImage, args.topic, on_image, qos_profile_sensor_data)
    deadline = time.monotonic() + args.seconds
    try:
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        if state["writer"] is not None:
            state["writer"].release()
        log.close()
        node.destroy_node()
        rclpy.shutdown()
    print(f"recorded {state['count']} frames to {args.out / 'overlay.mp4'}")
    return 0 if state["count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

`CMakeLists.txt`의 `install(PROGRAMS ...)` 목록에 `scripts/record_debug.py`를 추가한다.

- [ ] **Step 5: 통과 확인과 커밋**

Run: `python -m pytest src/core/control/test/ src/sim/gz_sim/test/ -q`
Expected: 전부 PASS

```bash
git add src/core/control/control/line_observer_node.py src/sim/gz_sim/scripts/record_debug.py src/sim/gz_sim/CMakeLists.txt src/sim/gz_sim/launch/map_v2_fleet_lane.launch.py src/core/control/test/test_line_observer_wiring.py src/sim/gz_sim/test/test_gz_package_contract.py
git commit -m "feat(control): publish and record the lane perception overlay"
```

---

### Task 8: 교차 시나리오 판정과 하네스

**Files:**
- Create: `src/sim/gz_sim/scripts/junction_score.py` (ROS-free)
- Test: `src/sim/gz_sim/test/test_junction_score.py`
- Create: `src/sim/gz_sim/scripts/junction_harness.py` (ROS)
- Modify: `src/sim/gz_sim/CMakeLists.txt`, `src/sim/gz_sim/test/test_gz_package_contract.py`

방향 구간 8개는 `west:f`(SW→NW), `west:r`, `east:f`(NE→SE), `east:r`, `ring_n`, `ring_w`, `ring_s`, `ring_e`다. 교차 전이는 노드마다 "들어오는 방향 구간 × 나가는 방향 구간"에서 같은 도로로 되돌아가는 경우를 뺀 것이다. 노드마다 3개씩, 모두 12개다.

- [ ] **Step 1: 실패하는 시험 작성**

```python
"""Junction scenarios from the lane graph, and trajectory scoring (spec §4.4)."""

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT.parents[1] / "core" / "control" / "map" / "map_v2_fleet" / "lane_graph.yaml"


def _mod():
    spec = importlib.util.spec_from_file_location("junction_score", ROOT / "scripts" / "junction_score.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def graph():
    return yaml.safe_load(GRAPH.read_text(encoding="utf-8"))


def test_twelve_transitions_three_per_node(graph):
    scenarios = _mod().scenarios(graph)
    assert len(scenarios) == 12
    per_node = {}
    for s in scenarios:
        per_node[s["node"]] = per_node.get(s["node"], 0) + 1
    assert per_node == {"NE": 3, "NW": 3, "SE": 3, "SW": 3}


def test_ring_is_only_entered_counter_clockwise(graph):
    for s in _mod().scenarios(graph):
        assert s["into"] not in ("ring_n:r", "ring_w:r", "ring_s:r", "ring_e:r")
        assert s["out"] not in ("ring_n:r", "ring_w:r", "ring_s:r", "ring_e:r")


def test_start_pose_is_on_the_incoming_centreline_heading_along_it(graph):
    mod = _mod()
    for s in mod.scenarios(graph):
        x, y, yaw = s["start"]
        pts = mod.directed_points(graph, s["into"])
        d = mod.distance_to(pts, (x, y))
        assert d < 0.005
        assert math.dist((x, y), graph["nodes"][s["node"]]) == pytest.approx(mod.START_BEFORE_M, abs=0.03)


def test_centreline_trajectory_scores_as_a_pass(graph):
    mod = _mod()
    s = mod.scenarios(graph)[0]
    path = np.vstack([mod.directed_points(graph, s["into"])[-40:],
                      mod.directed_points(graph, s["out"])[:40]])
    result = mod.score(graph, s, path)
    assert result["branch_ok"] and result["reached_end"]
    assert result["max_centre_dev_m"] < 0.005


def test_wrong_branch_is_detected(graph):
    mod = _mod()
    by_node = [s for s in mod.scenarios(graph) if s["node"] == "NW"]
    good, other = by_node[0], by_node[1]
    path = np.vstack([mod.directed_points(graph, good["into"])[-40:],
                      mod.directed_points(graph, other["out"])[:40]])
    if other["out"] != good["out"]:
        assert not mod.score(graph, good, path)["branch_ok"]


def test_off_centre_trajectory_reports_its_deviation(graph):
    mod = _mod()
    s = mod.scenarios(graph)[0]
    pts = np.vstack([mod.directed_points(graph, s["into"])[-40:],
                     mod.directed_points(graph, s["out"])[:40]])
    shifted = pts + np.array([0.03, 0.0])
    assert mod.score(graph, s, shifted)["max_centre_dev_m"] == pytest.approx(0.03, abs=0.01)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/sim/gz_sim/test/test_junction_score.py -q`
Expected: FAIL (`FileNotFoundError`)

- [ ] **Step 3: 판정기 구현**

```python
#!/usr/bin/env python3
"""Junction scenarios from lane_graph.yaml and trajectory scoring. ROS-free.

A directed segment is '<name>:f' (from -> to) or '<name>:r' (reverse, only
for two-way roads). A scenario is one transition through a node: arrive on
`into`, leave on `out`, never straight back along the same road. The robot
starts START_BEFORE_M before the node on `into`'s centreline, heading along
it; the scenario ends END_AFTER_M into `out`.
"""

import math

import numpy as np

START_BEFORE_M = 0.35
END_AFTER_M = 0.30
#: A trajectory point belongs to the segment whose centreline is nearest.
PASS_MAX_CENTRE_DEV_M = 0.040


def directed(graph):
    out = []
    for name in sorted(graph["segments"]):
        seg = graph["segments"][name]
        out.append((f"{name}:f", seg["from"], seg["to"]))
        if "reverse" in seg["directions"]:
            out.append((f"{name}:r", seg["to"], seg["from"]))
    return out


def directed_points(graph, key):
    name, way = key.split(":")
    pts = np.array(graph["segments"][name]["points"], float)
    return pts if way == "f" else pts[::-1]


def _arc_length(pts):
    return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])


def distance_to(pts, point):
    p = np.asarray(point, float)
    a, b = pts[:-1], pts[1:]
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12),
                0.0, 1.0)
    return float(np.min(np.linalg.norm(p - (a + ab * t[:, None]), axis=1)))


def scenarios(graph):
    segs = directed(graph)
    result = []
    for node in sorted(graph["nodes"]):
        arriving = [(k, a) for k, a, b in segs if b == node]
        leaving = [(k, b) for k, a, b in segs if a == node]
        for into, _ in arriving:
            for out, _ in leaving:
                if into.split(":")[0] == out.split(":")[0]:
                    continue          # straight back along the same road
                pts = directed_points(graph, into)
                s = _arc_length(pts)
                i = int(np.searchsorted(s, s[-1] - START_BEFORE_M))
                i = min(max(i, 1), len(pts) - 2)
                heading = math.atan2(*(pts[i + 1] - pts[i - 1])[::-1])
                result.append({"node": node, "into": into, "out": out,
                               "start": (round(float(pts[i][0]), 4), round(float(pts[i][1]), 4),
                                         round(heading, 4))})
    return result


def score(graph, scenario, trajectory):
    into = directed_points(graph, scenario["into"])
    out = directed_points(graph, scenario["out"])
    others = [directed_points(graph, k) for k, _, _ in directed(graph)
              if k not in (scenario["into"], scenario["out"])
              and k.split(":")[0] not in (scenario["into"].split(":")[0],
                                          scenario["out"].split(":")[0])]
    node = np.array(graph["nodes"][scenario["node"]], float)
    end_s = END_AFTER_M
    out_s = _arc_length(out)
    end_point = out[int(np.searchsorted(out_s, end_s))]
    max_dev, wrong, reached = 0.0, False, False
    for p in np.asarray(trajectory, float):
        d_into, d_out = distance_to(into, p), distance_to(out, p)
        d_best = min(d_into, d_out)
        d_other = min((distance_to(o, p) for o in others), default=math.inf)
        if d_other + 1e-6 < d_best and math.dist(p, node) > 0.12:
            wrong = True
        max_dev = max(max_dev, d_best if math.dist(p, node) > 0.12 else 0.0)
        if math.dist(p, end_point) < 0.05:
            reached = True
    return {"branch_ok": reached and not wrong, "reached_end": reached,
            "max_centre_dev_m": round(max_dev, 4),
            "pass": reached and not wrong and max_dev <= PASS_MAX_CENTRE_DEV_M}
```

`scenarios`의 제외 조건은 "같은 도로로 곧장 되돌아감"이다. 즉 `into`와 `out`의 도로 이름이 같으면 뺀다. 링 호끼리는 이름이 달라서 걸리지 않는다. 12개가 나오지 않으면 이 조건부터 확인한다.

- [ ] **Step 4: 판정 시험 통과 확인**

Run: `python -m pytest src/sim/gz_sim/test/test_junction_score.py -q`
Expected: 6 passed. `test_wrong_branch_is_detected`는 NW의 첫 두 시나리오에서 `out`이 다를 때만 검사한다. 두 시나리오의 `out`이 같으면 세 번째 시나리오를 쓰도록 고친다.

- [ ] **Step 5: 하네스 작성 (ROS, WSL에서 실행)**

```python
#!/usr/bin/env python3
"""Run the 12 junction scenarios in headless Gazebo and score them.

Usage (WSL, sourced overlay):
  python3 junction_harness.py --mode centre --out /rosy_mapv2_ws/evidence/junctions_<id> [--only NW]
Per scenario: launch map_v2_fleet_lane at the scenario start, enable
CAMERA_LINE through CORE's API, record /odom (Gazebo ground truth) until the
end point or TIMEOUT_S, then stop, score, and write results.json plus the
overlay MP4 (debug_overlay:=true).
"""

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import rclpy
import yaml
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

sys.path.insert(0, str(Path(__file__).resolve().parent))
import junction_score  # noqa: E402

TIMEOUT_S = 90.0
BOOT_S = 45.0
API = "http://127.0.0.1:8080/api/v1/line-follow/mode"
OPERATOR = {"Authorization": "Bearer rosy-dev-operator", "Content-Type": "application/json"}


def set_mode(mode):
    req = urllib.request.Request(API, data=json.dumps({"mode": mode}).encode(), method="PUT",
                                 headers=OPERATOR)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def run_one(scenario, graph, mode, out_dir, domain):
    x, y, yaw = scenario["start"]
    env = dict(os.environ, ROS_DOMAIN_ID=str(domain))
    launch = subprocess.Popen(
        ["ros2", "launch", "gz_sim", "map_v2_fleet_lane.launch.py",
         f"spawn_x:={x}", f"spawn_y:={y}", f"spawn_yaw:={yaw}",
         f"camera_lane_mode:={mode}", "debug_overlay:=true"],
        env=env, stdout=(out_dir / "launch.log").open("w"), stderr=subprocess.STDOUT,
        start_new_session=True)
    recorder = None
    try:
        time.sleep(BOOT_S)
        recorder = subprocess.Popen(
            ["python3", str(Path(__file__).with_name("record_debug.py")), "--out", str(out_dir),
             "--seconds", str(TIMEOUT_S + 5)], env=env)
        os.environ["ROS_DOMAIN_ID"] = str(domain)
        rclpy.init()
        node = Node("junction_harness")
        track = []
        node.create_subscription(
            Odometry, "odom",
            lambda m: track.append((m.pose.pose.position.x, m.pose.pose.position.y)),
            qos_profile_sensor_data)
        set_mode("CAMERA_LINE")
        end = junction_score.directed_points(graph, scenario["out"])
        s = junction_score._arc_length(end)
        end_point = end[int(s.searchsorted(junction_score.END_AFTER_M))]
        deadline = time.monotonic() + TIMEOUT_S
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if track and math.dist(track[-1], end_point) < 0.05:
                break
        set_mode("OFF")
        node.destroy_node()
        rclpy.shutdown()
        result = junction_score.score(graph, scenario, track or [scenario["start"][:2]])
        (out_dir / "track.json").write_text(json.dumps(track))
        return result
    finally:
        if recorder is not None:
            recorder.wait(timeout=TIMEOUT_S + 30)
        os.killpg(launch.pid, signal.SIGINT)
        try:
            launch.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(launch.pid, signal.SIGKILL)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", default="centre")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--only", default="")
    parser.add_argument("--domain", type=int, default=57)
    args = parser.parse_args(argv)
    graph = yaml.safe_load(args.graph.read_text(encoding="utf-8"))
    results = []
    for k, scenario in enumerate(junction_score.scenarios(graph)):
        if args.only and scenario["node"] != args.only:
            continue
        out_dir = args.out / f"{k:02d}_{scenario['node']}_{scenario['into']}_to_{scenario['out']}".replace(":", "")
        out_dir.mkdir(parents=True, exist_ok=True)
        result = dict(scenario, **run_one(scenario, graph, args.mode, out_dir, args.domain))
        results.append(result)
        print(json.dumps(result), flush=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=2))
    passed = sum(r["pass"] for r in results)
    print(f"{passed}/{len(results)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`CMakeLists.txt` 설치 목록에 `scripts/junction_score.py`와 `scripts/junction_harness.py`를 추가한다. `test_junction_tools_are_installed`의 목록을 세 개로 늘린다.

- [ ] **Step 6: 통과 확인과 커밋**

Run: `python -m pytest src/sim/gz_sim/test/ -q`
Expected: 전부 PASS

```bash
git add src/sim/gz_sim/scripts/junction_score.py src/sim/gz_sim/scripts/junction_harness.py src/sim/gz_sim/test/test_junction_score.py src/sim/gz_sim/CMakeLists.txt src/sim/gz_sim/test/test_gz_package_contract.py
git commit -m "feat(sim): junction scenarios from the lane graph and a Gazebo scoring harness"
```

---

### Task 9: Gazebo 기준선 측정 (ROS-SIM)

**Files:**
- Create: `docs/validation/lane-junction-spike/<실행 날짜>/baseline.md`

가운데선 모드에는 분기 선택이 없다. 이 작업은 가운데선 모드가 교차로에서 "저절로" 어떻게 행동하는지와, 오버레이 녹화가 실제로 동작하는지를 측정한다. 이 측정이 Plan 2(A와 B)의 비교 기준선이 된다.

- [ ] **Step 1: WSL 동기화와 빌드**

```bash
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash -lc 'rsync -a --delete "/mnt/f/Dev/Control/Robot/ROS/Rosy/.worktrees/lane-network-junctions/src/" ~/rosy_mapv2_ws/src/ && cd ~/rosy_mapv2_ws && source /opt/ros/jazzy/setup.bash && colcon build --symlink-install --packages-select control gz_sim core 2>&1 | tail -2'
```
Expected: `Summary: 3 packages finished`

- [ ] **Step 2: 한 바퀴 가운데선 주행과 오버레이 녹화**

기존 `scratchpad/run_lap_long.sh` 흐름을 쓴다. launch에 `camera_lane_mode:=centre debug_overlay:=true`를 주고, 동시에 `record_debug.py --out $OUT --seconds 420`를 돌린다.

기록한다:
- 한 바퀴 폐합(시작점 최소 거리, 2 m 이동 후)
- 중심 이탈 최대값(`junction_score.distance_to`로 궤적 대 `west`/링/`east` 중심선)
- tier 분포(`frames.jsonl`과 관측 로그)
- `overlay.mp4` 재생 확인

교차로에서 가운데선 모드가 안쪽 블록을 벗어나 다른 구간으로 가더라도 실패로 보지 않는다. 결과로 기록한다.

- [ ] **Step 3: 12개 교차 시나리오 기준선**

```bash
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash -lc 'cd ~/rosy_mapv2_ws && source /opt/ros/jazzy/setup.bash && source install/setup.bash && python3 install/gz_sim/lib/gz_sim/junction_harness.py --mode centre --graph install/control/share/control/map/map_v2_fleet/lane_graph.yaml --out /rosy_mapv2_ws/evidence/junctions_centre_$(date +%H%M%S)'
```
한 시나리오에 약 2.5분이 걸리고, 12개면 약 30분이다. 백그라운드로 돌리고 완료 알림을 기다린다.

- [ ] **Step 4: 결과 문서화**

`baseline.md`에 적는다:
- run ID, 커밋 SHA, 도구 버전
- 한 바퀴 결과
- 12개 시나리오 표: 노드, `into`, `out`, branch_ok, 최대 이탈, reached, 정지 사유
- 대표 `overlay.mp4` 두 개의 경로(성공 1, 실패 1). 저장소 밖 WSL 경로다.
- "ROS-SIM only. DEVICE/FIELD NOT RUN."

대표 프레임 PNG 몇 장은 `docs/validation/lane-junction-spike/<날짜>/`에 넣는다(각 50 KB 이하).

- [ ] **Step 5: 커밋**

```bash
git add docs/validation/lane-junction-spike
git commit -m "test(sim): centre-mode lap and junction baseline with perception overlay"
```

---

## 자체 검토 결과 (작성자)

- **spec 대응:**
  - §4.1 → Task 2
  - §4.2 → Task 3-4. 사다리 1/2/3/5단계. 4단계는 Plan 2.
  - §4.3 → Task 6-7
  - §4.4 → Task 8-9
  - §8 불변 조건 → 모든 노드 작업의 배선 시험(`Twist`/`cmd_vel` 없음, 기본값 끔)
- **범위 밖(Plan 2):** §5 A, §6 B, §7 비교
- **이름 일관성:**
  - `LaneBoundaryTracker.tier` / `TIERS` / `last["junction"]`는 Task 4, 6에서 같은 이름을 쓴다.
  - `junction_score.scenarios`, `directed_points`, `distance_to`, `score`, `START_BEFORE_M`, `END_AFTER_M`, `_arc_length`는 Task 8 전체에서 같은 이름을 쓴다.
- **알려진 위험:**
  - Task 2의 스냅: 교차 입구의 평탄 능선에서 스냅이 흔들릴 수 있다. 노드 0.12 m 안은 검증에서 뺐다.
  - Task 4의 역방향 좌우 탐색: 비대칭 `_right_boundary` 때문에 실패할 수 있다. 조치는 Step 4에 적었다.
