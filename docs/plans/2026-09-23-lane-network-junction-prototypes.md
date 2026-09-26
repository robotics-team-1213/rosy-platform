# 교차로 주행 시제품 A와 B Implementation Plan (Plan 2 / 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 12개 교차 전이를 통과하는 두 방식을 만들고 같은 시나리오로 측정해 하나를 고른다. A는 경로 순서와 차선망 기하로 교차 기동을 하는 카메라 방식이고, B는 도색 지도 위치 추정 위에서 계획 경로를 따르는 방식이다.

**Architecture:** 두 방식 모두 Plan 1의 `LaneBoundaryTracker`(좌우 경계, 가운데선, 강등 사다리)를 차선 유지에 쓴다. 다른 점은 "교차로에서 어디로 갈지"를 정하는 층뿐이다. 개발은 **오프라인 폐루프**로 한다. Plan 1의 `lane_sim`(역투영 렌더러 + CORE 법칙 거울)과 `junction_score`(방향 인식 판정)를 붙이면 12개 시나리오를 초 단위로 돌릴 수 있다. Gazebo는 마지막 확인에만 쓴다.

**Tech Stack:** Python 3, NumPy, OpenCV 5, PyYAML, ROS 2 Jazzy, Gazebo Sim 8.11, pytest.

**입력 문서:**
- 설계: `docs/plans/2026-09-22-lane-network-junction-spike-design.md` (§5 A, §6 B, §7 비교)
- 기준선: `docs/validation/lane-junction-spike/2026-09-23/baseline.md`

**기준선이 남긴 조건 (반드시 푼다):**
1. 12개 시작점 중 10개에서 추종이 시작되지 않는다. 곡선이나 교차 부근이라 선이 한 줄만 보인다. 두 방식 모두 곡선에서 시작할 수 있어야 한다.
2. 분기 결정이 없으면 링을 역방향으로 돈다. `junction_score`가 `wrong_way`와 `ring_ccw_ok`로 잡는다. 합격은 이 둘을 만족해야 한다.

---

## 공통 규칙

- 작업 디렉터리: `F:\Dev\Control\Robot\ROS\Rosy\.worktrees\lane-network-junctions` (브랜치 `feat/lane-network-junctions`, HEAD `cce234a`). `git stash`는 쓰지 않는다.
- Windows 호스트 시험:
  ```powershell
  $env:PYTHONPATH = "src/core/control;src/core/core;src"
  python -m pytest src/core/control/test/ src/sim/gz_sim/test/ -q
  ```
  기준선은 1,437 passed, 29 skipped다. 매 작업 뒤 줄어들면 안 된다.
- 커밋 메시지 끝에 넣는다: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- 불변 조건: `control`은 증거와 관찰 이미지만 발행한다. CORE가 유일한 최종 명령자다. 증거가 없으면 출력하지 않는다. 기존 `line`/`lane`/`edge_left`/`centre` 모드는 바뀌지 않는다.
- **숫자는 측정으로 정한다.** 문턱을 바꾸면 근거를 시험 docstring이나 커밋 메시지에 적는다.

## 파일 구조

| 파일 | 책임 |
|---|---|
| Create `src/core/control/test/lane_scenarios.py` | 오프라인 12 시나리오 폐루프 실행기(시험 전용 도우미) |
| Create `src/core/control/test/test_lane_scenarios.py` | 실행기 자체 시험 + 가운데선 모드 기준선 재현 |
| Create `src/core/control/control/sensing/lane_route.py` | ROS-free 경로 모델: 방향 구간 순서, 진행도, 다음 노드까지 거리, 출구 접선 |
| Create `src/core/control/test/test_lane_route.py` | 경로 모델 시험 |
| Create `src/core/control/control/sensing/route_camera.py` | 시제품 A: 경로 기반 교차 기동 + `LaneBoundaryTracker` |
| Create `src/core/control/test/test_route_camera.py` | A 시험(12 시나리오 오프라인 포함) |
| Create `src/core/control/control/sensing/paint_localizer.py` | 시제품 B: 도색 지도 입자 필터 |
| Create `src/core/control/test/test_paint_localizer.py` | B 위치 추정 시험 |
| Create `src/core/control/control/sensing/route_map.py` | 시제품 B: 추정 자세 + 계획 경로 pure pursuit |
| Create `src/core/control/test/test_route_map.py` | B 시험(12 시나리오 오프라인 포함) |
| Modify `src/core/control/control/line_observer_node.py` | 모드 `route_a`, `route_b`, 파라미터 `lane_graph_path`, `route`, `route_start` |
| Modify `src/core/control/config/line_follow.yaml` | 새 파라미터 기본값(빈 값, 기존 동작 유지) |
| Modify `src/sim/gz_sim/launch/map_v2_fleet_lane.launch.py` | `route`, `route_start` launch 인자 |
| Modify `src/sim/gz_sim/scripts/junction_harness.py` | `--mode route_a|route_b`일 때 시나리오의 경로와 시작 자세를 노드에 전달 |
| Create `docs/validation/lane-junction-spike/<날짜>/comparison.md` | Gazebo 12 시나리오 × A/B 결과와 결정 |

---

### Task 1: 오프라인 시나리오 실행기

**Files:**
- Create: `src/core/control/test/lane_scenarios.py`
- Test: `src/core/control/test/test_lane_scenarios.py`

Gazebo 한 바퀴는 20분이다. 같은 12개를 합성 카메라로 돌리면 초 단위다. Plan 1의 `stl_world`(STL 도색 래스터 역투영)와 `junction_score`(방향 인식 판정)를 잇는다.

- [ ] **Step 1: 실패하는 시험 작성**

```python
"""Offline 12-scenario closed loop: same scoring as the Gazebo harness."""

import math

import pytest

from lane_scenarios import GRAPH, SCENARIOS, run_scenario
from control.sensing.lane_boundaries import LaneBoundaryTracker
from lane_sim import CAM_X


def centre_tracker():
    return LaneBoundaryTracker(camera_x_offset_m=CAM_X)


def test_twelve_scenarios_match_the_harness_definition():
    assert len(SCENARIOS) == 12
    assert sorted({s["node"] for s in SCENARIOS}) == ["NE", "NW", "SE", "SW"]


def test_runner_returns_track_and_score_keys():
    result = run_scenario(SCENARIOS[5], centre_tracker(), steps=120)
    for key in ("track", "pass", "branch_ok", "reached_end", "max_centre_dev_m",
                "wrong_way", "ring_ccw_ok", "tiers"):
        assert key in result


def test_centre_mode_reproduces_the_gazebo_baseline_shape():
    """Gazebo run 2026-09-23 (baseline.md): 0/12; 10 never start (no pair to
    seed on a bend); 05 and 11 drive the ring clockwise. The offline loop is
    the same renderer, so it must show the same two failure modes."""
    stuck, moved = [], []
    for scenario in SCENARIOS:
        result = run_scenario(scenario, centre_tracker(), steps=150)
        travelled = sum(math.dist(result["track"][i], result["track"][i + 1])
                        for i in range(len(result["track"]) - 1))
        (moved if travelled > 0.05 else stuck).append(scenario["node"] + ":" + scenario["into"])
        assert not result["pass"]
    assert len(stuck) >= 8, f"expected most starts to fail closed, stuck={stuck}"
    assert moved, "at least one scenario moved in the Gazebo baseline"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/core/control/test/test_lane_scenarios.py -q`
Expected: FAIL (`ModuleNotFoundError: lane_scenarios`)

- [ ] **Step 3: 구현**

```python
"""Offline closed loop for the 12 junction scenarios (test helper).

Same three parts as the Gazebo harness, minus Gazebo: lane_sim renders the
STL paint through the declared camera, CORE's law turns an observation into
a command, and junction_score judges the resulting track (direction-aware).
A follower here is anything with `.update(now_s, pose, bgr, ground, **KW)`
returning a LaneObservation or None, like LaneBoundaryTracker.
"""

import importlib.util
import math
from pathlib import Path

import yaml

import lane_sim

ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = ROOT / "map" / "map_v2_fleet" / "lane_graph.yaml"
SCORE_PATH = ROOT.parents[1] / "sim" / "gz_sim" / "scripts" / "junction_score.py"


def _junction_score():
    spec = importlib.util.spec_from_file_location("junction_score", SCORE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


junction_score = _junction_score()
GRAPH = yaml.safe_load(GRAPH_PATH.read_text(encoding="utf-8"))
SCENARIOS = junction_score.scenarios(GRAPH)
WORLD = lane_sim.stl_world()


def run_scenario(scenario, follower, *, steps=200, world=None):
    """Drive one scenario offline; return the track, the score and the tiers."""
    world = WORLD if world is None else world
    pose = tuple(scenario["start"])
    track, tiers = [pose[:2]], []
    end = junction_score.directed_points(GRAPH, scenario["out"])
    end_s = junction_score._arc_length(end)
    end_point = end[int(end_s.searchsorted(junction_score.END_AFTER_M))]
    for step in range(steps):
        observation = follower.update(step * lane_sim.DT, pose, world.render(pose),
                                      lane_sim.GROUND, **lane_sim.KW)
        tiers.append(getattr(follower, "state", "-"))
        linear, angular = lane_sim.core_command(observation)
        mid = pose[2] + angular * lane_sim.DT / 2.0
        pose = (pose[0] + linear * lane_sim.DT * math.cos(mid),
                pose[1] + linear * lane_sim.DT * math.sin(mid),
                pose[2] + angular * lane_sim.DT)
        track.append(pose[:2])
        if math.dist(pose[:2], end_point) < 0.05:
            break
    result = junction_score.score(GRAPH, scenario, track)
    result.update(track=track, tiers=tiers, final_pose=pose)
    return result


def summary(results):
    """One line per scenario for a test failure message."""
    return "\n".join(
        f"{r['scenario']['node']:>2} {r['scenario']['into']:>9} -> {r['scenario']['out']:<9}"
        f" pass={r['pass']} dev={r['max_centre_dev_m']:.3f}"
        f" wrong_way={r['wrong_way']} ccw={r['ring_ccw_ok']}"
        for r in results)
```

`summary`가 쓰는 `r["scenario"]`는 호출 쪽에서 넣는다. 실행기는 넣지 않는다. 시험에서 `result["scenario"] = scenario`로 채운 뒤 `summary`에 넘긴다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/core/control/test/test_lane_scenarios.py -q`
Expected: 3 passed. 오프라인과 Gazebo의 "시작 못 함" 개수가 다르면(예: 오프라인은 8개) 그 차이를 시험 docstring에 적고 이유를 조사한다. 렌더러 차이(벽 바닥면을 도색으로 보는 점)일 수 있다.

- [ ] **Step 5: 커밋**

```bash
git add src/core/control/test/lane_scenarios.py src/core/control/test/test_lane_scenarios.py
git commit -m "test(control): offline closed loop for the 12 junction scenarios"
```

---

### Task 2: 경로 모델 (ROS-free)

**Files:**
- Create: `src/core/control/control/sensing/lane_route.py`
- Test: `src/core/control/test/test_lane_route.py`

A와 B가 함께 쓴다. "지금 어느 방향 구간의 어디쯤이고, 다음 노드까지 몇 m이며, 거기서 나갈 방향은 어디인가"를 답한다.

- [ ] **Step 1: 실패하는 시험 작성**

```python
"""Route model shared by both junction prototypes."""

import math

import numpy as np
import pytest
import yaml

from control.sensing.lane_route import LaneRoute
from lane_scenarios import GRAPH, SCENARIOS


def test_route_of_one_transition_has_two_segments():
    scenario = SCENARIOS[5]
    route = LaneRoute(GRAPH, [scenario["into"], scenario["out"]])
    assert route.segments == [scenario["into"], scenario["out"]]
    assert route.length_m > 0.5


def test_progress_follows_the_pose_along_the_route():
    scenario = SCENARIOS[5]
    route = LaneRoute(GRAPH, [scenario["into"], scenario["out"]])
    start = route.locate(scenario["start"][:2])
    assert start.segment_index == 0
    assert start.lateral_m == pytest.approx(0.0, abs=0.005)
    assert start.distance_to_node_m == pytest.approx(0.35, abs=0.02)


def test_exit_tangent_is_the_heading_of_the_next_segment_at_the_node():
    scenario = SCENARIOS[5]
    route = LaneRoute(GRAPH, [scenario["into"], scenario["out"]])
    points = np.array(GRAPH["segments"][scenario["out"].split(":")[0]]["points"])
    if scenario["out"].endswith(":r"):
        points = points[::-1]
    expected = math.atan2(*(points[3] - points[0])[::-1])
    assert abs(math.atan2(math.sin(route.exit_heading(0) - expected),
                          math.cos(route.exit_heading(0) - expected))) < math.radians(10)


def test_target_point_ahead_returns_a_route_point_at_the_lookahead():
    scenario = SCENARIOS[5]
    route = LaneRoute(GRAPH, [scenario["into"], scenario["out"]])
    point = route.point_ahead(scenario["start"][:2], 0.15)
    assert math.dist(point, scenario["start"][:2]) == pytest.approx(0.15, abs=0.02)


def test_off_route_pose_reports_its_lateral_error():
    scenario = SCENARIOS[5]
    route = LaneRoute(GRAPH, [scenario["into"], scenario["out"]])
    x, y, yaw = scenario["start"]
    shifted = (x - 0.03 * math.sin(yaw), y + 0.03 * math.cos(yaw))
    assert abs(route.locate(shifted).lateral_m) == pytest.approx(0.03, abs=0.005)


def test_route_rejects_a_disconnected_pair():
    with pytest.raises(ValueError, match="not connected"):
        LaneRoute(GRAPH, ["west:f", "east:f"])


def test_route_rejects_a_ring_arc_driven_backwards():
    with pytest.raises(ValueError, match="one-way"):
        LaneRoute(GRAPH, ["ring_n:r", "west:r"])
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/core/control/test/test_lane_route.py -q`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

`lane_route.py`는 다음을 담는다. 구현은 이미 있는 것을 재사용한다.
- `DirectedSegment`: `key`, `points` (N×2), `arc` (누적 길이), `from_node`, `to_node`.
- `LaneRoute(graph, keys)`:
  - 생성 시 검증: 연속한 두 구간이 노드를 공유해야 한다(아니면 `ValueError("... not connected ...")`), 링 구간은 `:r`가 금지다(`ValueError("... one-way ...")`).
  - `segments`, `length_m`.
  - `locate(xy) -> Fix(segment_index, s_m, lateral_m, distance_to_node_m, heading)`: 각 구간 폴리라인에 수직 투영해 가장 가까운 점을 찾는다. 탐색은 직전 `s`에서 ±0.5 m 창으로 제한한다(`junction_score._nearest_on_path`와 같은 이유: 링과 도로가 같은 두 노드를 잇는다).
  - `exit_heading(segment_index) -> float`: 다음 구간의 노드 근처 접선 방향.
  - `point_ahead(xy, lookahead_m) -> (x, y)`: 현재 투영점에서 경로를 따라 `lookahead_m` 앞의 점. 구간 경계를 넘어 이어진다.
  - `heading_at(segment_index, s_m) -> float`.

시험이 요구하는 정확한 이름과 반환값을 지킨다. 구현은 NumPy 벡터 연산으로 쓰고, 파일은 200줄을 넘기지 않는다.

- [ ] **Step 4: 통과 확인 후 커밋**

Run: `python -m pytest src/core/control/test/test_lane_route.py -q` → 7 passed

```bash
git add src/core/control/control/sensing/lane_route.py src/core/control/test/test_lane_route.py
git commit -m "feat(control): directed lane route model over the 260919 graph"
```

---

### Task 3: 시제품 A — 경로 기반 교차 기동

**Files:**
- Create: `src/core/control/control/sensing/route_camera.py`
- Test: `src/core/control/test/test_route_camera.py`

A의 규칙:
- 구간 안에서는 `LaneBoundaryTracker`의 출력을 그대로 쓴다(가운데선, 강등 사다리).
- 노드가 `JUNCTION_ARM_M` 안에 들어오면 무장한다. 위치는 odometry 적분과 경로 투영으로 안다(시작 자세는 주어진다. 기준선 발견 1의 "곡선에서 못 시작함"은 이렇게 푼다).
- 기동: 노드 중심까지 남은 거리를 odometry로 재고, 그 뒤 목표 방향 `route.exit_heading()`에 맞춰 선회한다. 기동 중 출력은 기동이 만든 오차다(tier `MANOEUVRE`, 설계 §4.2의 4단계).
- 기동 종료 조건: 방향 오차가 `REACQUIRE_HEADING_RAD` 안이고 추종기가 새 차로를 잡으면 FOLLOW로 돌아간다. `MANOEUVRE_MAX_TRAVEL_M`이나 `MANOEUVRE_TIMEOUT_S`를 넘으면 출력을 멈춘다(fail-closed).
- 링 진입은 `exit_heading`이 정하므로 방향 규칙은 경로가 보장한다. 역방향은 경로에 없다.

- [ ] **Step 1: 실패하는 시험 작성**

```python
"""Prototype A: route-driven junction manoeuvres over centre-line following."""

import math

import pytest

from control.sensing.route_camera import RouteCameraFollower
from lane_scenarios import GRAPH, SCENARIOS, run_scenario, summary
from lane_sim import CAM_X


def follower(scenario):
    return RouteCameraFollower(GRAPH, [scenario["into"], scenario["out"]],
                               start_pose=scenario["start"], camera_x_offset_m=CAM_X)


@pytest.mark.parametrize("index", range(12))
def test_every_junction_transition_is_driven(index):
    scenario = SCENARIOS[index]
    result = run_scenario(scenario, follower(scenario), steps=260)
    result["scenario"] = scenario
    assert result["reached_end"], summary([result])
    assert result["branch_ok"], summary([result])
    assert not result["wrong_way"], summary([result])
    assert result["ring_ccw_ok"], summary([result])
    assert result["max_centre_dev_m"] <= 0.040, summary([result])


def test_a_manoeuvre_that_never_reacquires_stops():
    """Fail-closed: with the world blank after the node, the manoeuvre ends
    and the follower publishes nothing rather than driving blind."""
    scenario = SCENARIOS[5]
    blank = _world_without_paint_after_the_node(scenario)
    result = run_scenario(scenario, follower(scenario), steps=260, world=blank)
    assert not result["pass"]
    assert result["tiers"][-1] in ("STOP", "MANOEUVRE_ABORT")


def test_the_route_forbids_the_wrong_way_round_the_ring():
    with pytest.raises(ValueError, match="one-way"):
        RouteCameraFollower(GRAPH, ["west:f", "ring_n:r"], start_pose=(0, 0, 0))
```

`_world_without_paint_after_the_node`는 시험 안에서 만든다. `lane_sim.stl_world()`의 래스터를 복사하고, 노드 중심에서 반지름 0.35 m 안의 도색을 0으로 지운다. 좌표→픽셀 변환은 `World.px`를 쓴다.

- [ ] **Step 2: 실패 확인 → Step 3: 구현 → Step 4: 12개 통과**

Run: `python -m pytest src/core/control/test/test_route_camera.py -q`
Expected: 최종 14 passed (12 파라미터 + 2)

구현 중 지켜야 할 것:
- 상수는 이름과 유도 근거를 함께 둔다. 예: `JUNCTION_ARM_M`은 BEV 관측 범위(0.40 m)와 룩어헤드(0.15 m)에서, `REACQUIRE_HEADING_RAD`는 차로 반폭과 룩어헤드에서.
- `MANOEUVRE` 중 신뢰도는 `MEMORY_CONFIDENCE`(0.6)를 넘지 않는다. CORE 속도가 그만큼 준다.
- 12개가 한 번에 통과하지 않으면, 실패한 시나리오의 궤적과 tier 전이를 `scratchpad`에 그림으로 떨구고 원인을 적는다. 시나리오별 특례는 만들지 않는다.

- [ ] **Step 5: 커밋**

```bash
git add src/core/control/control/sensing/route_camera.py src/core/control/test/test_route_camera.py
git commit -m "feat(control): prototype A, route-driven junction manoeuvres"
```

---

### Task 4: 시제품 B — 도색 지도 위치 추정

**Files:**
- Create: `src/core/control/control/sensing/paint_localizer.py`
- Test: `src/core/control/test/test_paint_localizer.py`

입자 필터. 예측은 odometry 증분에 잡음을 더하고, 갱신은 BEV 도색 격자를 STL 도색 거리장에 맞춘 점수로 한다.

- [ ] **Step 1: 실패하는 시험 작성**

```python
"""Prototype B: particle filter over the checked-in paint map."""

import math

import numpy as np
import pytest

from control.sensing.paint_localizer import PaintLocalizer, PaintMap
from lane_sim import CAM_X, GROUND, KW, stl_world

WORLD = stl_world()
START = (-1.26955, 0.24255, -math.pi / 2)


def localizer(pose=START, particles=300):
    return PaintLocalizer(PaintMap.from_bundle(), camera_x_offset_m=CAM_X,
                          particles=particles, seed=7).initialise(pose)


def test_a_still_robot_keeps_its_pose():
    loc = localizer()
    for k in range(5):
        estimate = loc.update(k * 0.2, START, WORLD.render(START), GROUND, **KW)
    assert math.dist(estimate.pose[:2], START[:2]) < 0.01
    assert abs(estimate.pose[2] - START[2]) < math.radians(3)


def test_it_corrects_a_lateral_odometry_error():
    """Odometry says straight ahead; the robot really drifts 3 cm right.
    Matching the paint must pull the estimate back to the true pose."""
    loc = localizer()
    true_pose, odom_pose = START, START
    for k in range(12):
        true_pose = (true_pose[0] + 0.0025, true_pose[1] - 0.016, true_pose[2])
        odom_pose = (odom_pose[0], odom_pose[1] - 0.016, odom_pose[2])
        estimate = loc.update(k * 0.2, odom_pose, WORLD.render(true_pose), GROUND, **KW)
    assert math.dist(estimate.pose[:2], true_pose[:2]) < math.dist(odom_pose[:2], true_pose[:2])
    assert math.dist(estimate.pose[:2], true_pose[:2]) < 0.02


def test_a_frame_with_no_paint_lowers_the_match_score():
    loc = localizer()
    blank = np.full((180, 320), 109, np.uint8)
    estimate = loc.update(0.0, START, blank, GROUND, **KW)
    assert estimate.match < 0.3


def test_no_ground_or_no_pose_is_no_estimate():
    loc = localizer()
    assert loc.update(0.0, None, WORLD.render(START), GROUND, **KW) is None
    assert loc.update(0.0, START, WORLD.render(START), None, **KW) is None


def test_covariance_grows_without_paint_and_shrinks_with_it():
    loc = localizer()
    blank = np.full((180, 320), 109, np.uint8)
    for k in range(5):
        weak = loc.update(k * 0.2, START, blank, GROUND, **KW)
    for k in range(5, 12):
        strong = loc.update(k * 0.2, START, WORLD.render(START), GROUND, **KW)
    assert strong.spread_m < weak.spread_m
```

- [ ] **Step 2-4: 구현과 통과**

`PaintMap.from_bundle()`은 `map_v2_fleet`의 STL에서 도색 거리장을 만든다. `lane_graph.py`의 `LineField`와 같은 방식이되, 횡단보도 막대도 포함한다(카메라는 막대도 본다). 래스터 2 mm.

`PaintLocalizer`:
- `initialise(pose)`: 자세 주변에 입자를 뿌린다. 표준편차는 이름 있는 상수(`INIT_XY_SIGMA_M`, `INIT_YAW_SIGMA_RAD`).
- `update(now_s, odom_pose, bgr, ground, **lane_kwargs) -> Estimate | None`:
  - odometry 증분을 입자에 적용하고 잡음을 더한다(`MOTION_XY_SIGMA_PER_M`, `MOTION_YAW_SIGMA_PER_RAD`).
  - BEV 도색 셀을 각 입자 자세로 지도 좌표에 옮기고, 거리장 값의 평균으로 점수를 낸다. 점수는 `exp(-mean_distance / MATCH_SCALE_M)`.
  - 가중치 정규화, 유효 입자 수가 절반 아래면 재표본.
  - 반환 `Estimate(pose, spread_m, match)`. `spread_m`은 입자 위치 표준편차의 최대 고유값의 제곱근.
  - `ground`나 `odom_pose`가 없으면 `None`을 돌려주고 상태를 지운다.
- 성능: 입자 300개, BEV 셀은 최대 400개를 무작위 표본해서 쓴다(상수 `MATCH_SAMPLE_CELLS`). 한 프레임이 Windows 호스트에서 30 ms를 넘지 않아야 한다. 시험에 시간 검사를 넣는다.

상수는 측정으로 정한다. 시험이 통과하는 최소값을 쓰고, 근거를 docstring에 적는다.

- [ ] **Step 5: 커밋**

```bash
git add src/core/control/control/sensing/paint_localizer.py src/core/control/test/test_paint_localizer.py
git commit -m "feat(control): prototype B, particle filter over the paint map"
```

---

### Task 5: 시제품 B — 계획 경로 추종

**Files:**
- Create: `src/core/control/control/sensing/route_map.py`
- Test: `src/core/control/test/test_route_map.py`

- [ ] **Step 1: 실패하는 시험 작성**

```python
"""Prototype B: pursue the planned route from the localised pose."""

import math

import pytest

from control.sensing.route_map import RouteMapFollower
from lane_scenarios import GRAPH, SCENARIOS, run_scenario, summary
from lane_sim import CAM_X


def follower(scenario):
    return RouteMapFollower(GRAPH, [scenario["into"], scenario["out"]],
                            start_pose=scenario["start"], camera_x_offset_m=CAM_X, seed=7)


@pytest.mark.parametrize("index", range(12))
def test_every_junction_transition_is_driven(index):
    scenario = SCENARIOS[index]
    result = run_scenario(scenario, follower(scenario), steps=260)
    result["scenario"] = scenario
    assert result["reached_end"], summary([result])
    assert result["branch_ok"], summary([result])
    assert not result["wrong_way"], summary([result])
    assert result["ring_ccw_ok"], summary([result])
    assert result["max_centre_dev_m"] <= 0.040, summary([result])


def test_a_lost_localiser_stops_rather_than_guessing():
    """Fail-closed: paint erased after the node, so the match collapses."""
    scenario = SCENARIOS[5]
    blank = _world_without_paint_after_the_node(scenario)
    result = run_scenario(scenario, follower(scenario), steps=260, world=blank)
    assert not result["pass"]
    assert result["tiers"][-1] == "STOP"


def test_camera_lane_disagreement_stops_the_follower():
    """If the localised pose says the lane centre is here but the camera's
    own centre line says otherwise by more than half a half-width, stop."""
    scenario = SCENARIOS[5]
    f = follower(scenario)
    f.force_pose_offset(0.08)     # test hook: bias the estimate laterally
    result = run_scenario(scenario, f, steps=120)
    assert result["tiers"][-1] == "STOP"
```

- [ ] **Step 2-4: 구현과 통과**

`RouteMapFollower`:
- 안에 `PaintLocalizer`, `LaneRoute`, `LaneBoundaryTracker`를 둔다.
- 매 프레임: 위치 추정 → `route.point_ahead(estimate.pose[:2], LOOKAHEAD_M)` → 로봇 좌표로 변환 → 곡률 → `error_for_curvature`.
- 정지 조건(설계 §6):
  - `estimate is None`
  - `estimate.spread_m > MAX_SPREAD_M`
  - `estimate.match < MIN_MATCH`
  - 추종기의 카메라 가운데선과 계획 경로의 횡 오차 차이가 `MAX_DISAGREE_M`(= 반 차로폭의 절반, 0.046 m)을 넘음
- 신뢰도는 `match`와 `spread_m`으로 만든다. 상한은 1.0, 하한은 CORE 최소(0.35) 위.
- `force_pose_offset(m)`은 시험 전용 훅이다. docstring에 그렇게 적는다.

- [ ] **Step 5: 커밋**

```bash
git add src/core/control/control/sensing/route_map.py src/core/control/test/test_route_map.py
git commit -m "feat(control): prototype B, planned-route pursuit from the localised pose"
```

---

### Task 6: 노드와 하네스 배선

**Files:**
- Modify: `src/core/control/control/line_observer_node.py`
- Modify: `src/core/control/config/line_follow.yaml`
- Modify: `src/sim/gz_sim/launch/map_v2_fleet_lane.launch.py`
- Modify: `src/sim/gz_sim/scripts/junction_harness.py`
- Test: `src/core/control/test/test_line_observer_wiring.py`, `src/sim/gz_sim/test/test_map_v2_fleet_launch.py`, `src/sim/gz_sim/test/test_junction_harness_contract.py`

- [ ] **Step 1: 실패하는 시험 추가**

```python
def test_route_modes_need_a_graph_and_a_route():
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    config = yaml.safe_load((ROOT / "config/line_follow.yaml").read_text(encoding="utf-8"))
    params = config["/**/line_observer_node"]["ros__parameters"]
    assert params["lane_graph_path"] == ""
    assert params["route"] == []
    assert params["route_start"] == []
    assert "RouteCameraFollower" in source and "RouteMapFollower" in source
    assert "mode in ('lane', 'edge_left', 'centre', 'route_a', 'route_b')" in source
    assert "route modes need lane_graph_path, route and route_start" in source
```

하네스 계약 시험에는 `--mode route_a`일 때 `route:=` 와 `route_start:=` launch 인자를 넘긴다는 것을 넣는다.

- [ ] **Step 2-4: 구현**

- 파라미터 `lane_graph_path`(문자열), `route`(문자열 배열, 예 `["west:f", "ring_w:f"]`), `route_start`(실수 3개). 모두 read-only.
- `route_a`/`route_b` 모드에서 셋이 갖춰지지 않으면 경고를 한 번 남기고 관측을 발행하지 않는다(fail-closed).
- 그래프 로드 실패도 같은 처리다.
- launch에 `route`와 `route_start` 인자를 더한다. 기본은 빈 값이고, 기본 모드는 그대로 `edge_left`다.
- 하네스는 `--mode route_a|route_b`일 때 시나리오의 `[into, out]`과 `start`를 그 인자로 넘긴다.

- [ ] **Step 5: 통과 확인과 커밋**

Run: `python -m pytest src/core/control/test/ src/sim/gz_sim/test/ -q`

```bash
git add -u && git commit -m "feat(sim): route_a and route_b modes wired through launch and harness"
```

---

### Task 7: Gazebo 비교 실행과 결정

**Files:**
- Create: `docs/validation/lane-junction-spike/<실행 날짜>/comparison.md`

- [ ] **Step 1: 빌드**

```bash
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash -lc 'rsync -a --delete "/mnt/f/Dev/Control/Robot/ROS/Rosy/.worktrees/lane-network-junctions/src/" ~/rosy_mapv2_ws/src/ && cd ~/rosy_mapv2_ws && source /opt/ros/jazzy/setup.bash && colcon build --symlink-install --packages-select control gz_sim core 2>&1 | tail -2'
```

- [ ] **Step 2: A와 B를 각각 3회**

```bash
python3 install/gz_sim/lib/gz_sim/junction_harness.py --mode route_a --graph <graph> --domain 57 --out /rosy_mapv2_ws/evidence/junctions_route_a_<n>
python3 install/gz_sim/lib/gz_sim/junction_harness.py --mode route_b --graph <graph> --domain 58 --out /rosy_mapv2_ws/evidence/junctions_route_b_<n>
```
한 번에 약 20-30분이다. 한 번에 하나씩 돌린다. 호스트가 다른 세션과 CPU를 나눠 쓰면 더 걸린다.

- [ ] **Step 3: 결과 정리**

설계 §7의 지표로 표를 만든다.
- 분기 정확성 36/36
- 최대 중심 이탈 ≤ 40 mm
- 원인 없는 정지 0
- 역방향 0 (`wrong_way=false`, `ring_ccw_ok=true`)
- B는 끝 위치 추정 오차 ≤ 20 mm

여기에 구현 규모(줄 수)와 실물 추가 요구(카메라 지면 보정, 연산량, odometry 의존도)를 적는다.

- [ ] **Step 4: 결정과 문서화**

설계 §7의 결정 규칙을 적용한다. 고른 방식과 근거, 대표 `overlay.mp4` 경로, 다음 단계(전 차선 커버리지 계획)를 적는다. ROS-SIM 한정임을 명시한다.

- [ ] **Step 5: 커밋**

```bash
git add docs/validation/lane-junction-spike
git commit -m "test(sim): junction prototype comparison and decision"
```

---

## 자체 검토

- **설계 대응:** §5 A → Task 3. §6 B → Task 4, 5. §7 비교 → Task 7. §4.2의 4단계(기동) → Task 3의 `MANOEUVRE`와 Task 5의 계획 경로. §8 불변 조건 → Task 6의 fail-closed 배선.
- **기준선 조건 대응:** 발견 1(곡선 시작) → A는 시작 자세와 경로 투영으로, B는 위치 추정 초기화로 푼다. 두 방식 모두 12개 시나리오 시험이 이를 강제한다. 발견 2(역방향) → 경로가 링 방향을 강제하고, 판정기가 `ring_ccw_ok`로 막는다.
- **이름 일관성:** `run_scenario`, `summary`, `LaneRoute.locate/exit_heading/point_ahead`, `RouteCameraFollower`, `PaintLocalizer/PaintMap/Estimate`, `RouteMapFollower`는 Task 1-6에서 같은 이름으로 쓴다.
- **위험:**
  - B의 입자 필터 상수는 측정이 필요하다. 시험이 그것을 강제한다.
  - 오프라인 렌더러와 Gazebo의 차이(벽 바닥면, 조명, 프레임률)가 결과를 바꿀 수 있다. 그래서 Task 7의 Gazebo 실행이 최종 근거다.
  - A의 기동은 odometry에 의존한다. 실물에서는 드리프트가 있다. 비교표의 "실물 추가 요구"에 적는다.
