---
module: middleware/perception/map/map_world_261026
date: 2026-11-12
problem_type: workflow_issue
component: simulation_world_builder
severity: major
tags: ["gazebo", "sdf", "xml", "map_world_261026", "silent-failure"]
applies_when: "스크립트로 Gazebo SDF(.world) 파일을 생성하고 xml.etree.ElementTree로 단위 시험할 때, 또는 Gazebo Sim Server가 Error Code 2 (model with name already exists)로 즉시 종료될 때"
---

# SDF 월드 XML 단위 시험은 `<model name>` 유일성과 로컬 충돌 좌표를 함께 검증해야 한다

## 증상

`map_world_261026.world`를 `gz_multi.launch.py`로 Gazebo Sim Server v8.15.0에서 기동하자 서버가 `[Err] [Server.cc:86] Error Code 2: Msg: A model with name[bay_guide] already exists.` 오류를 내고 즉시 종료되었다. 반면 XML 구조를 검사하는 `middleware/perception/test/test_map_world_261026_scene.py`의 5개 단위 시험은 모두 통과 상태였다.

## 원인

1. `middleware/perception/map/map_world_261026/scripts/build_world.py`가 충전 칸 3개(`BAY_XS = (-0.414, -0.190, 0.032)`)를 순회하며 모두 동일한 `<model name="bay_guide">`로 출력했다. `xml.etree.ElementTree.findall(".//model[@name='bay_guide']")`는 중복 이름을 허용하므로 단위 시험이 이를 통과시켰다.
2. 모델 `<pose>{bx} ...>`에 이미 `bx`가 들어간 상태에서 내부 `<collision>`의 `<pose>`에도 `{bx - BAY_HALF_W}`를 적어 가로 오프셋 `bx`가 이중 적용되고 있었다.

## 해결

1. `build_world.py`에서 각 충전 칸 가이드를 `bay_guide_1`, `bay_guide_2`, `bay_guide_3`으로 고유하게 명명하고, 내부 좌우 레일 충돌체의 로컬 X 좌표를 모델 원점 기준 `±BAY_HALF_W`로 바로잡았다.
2. `integrations/simulation/gazebo/config/worlds.yaml`에 `map_world_261026.world`를 등록했다.
3. `test_map_world_261026_scene.py`에 `assert len(names) == len(set(names))` 단언을 추가해 중복 `<model name>`이 재발하면 단위 시험에서 즉시 실패하도록 고정했다.

## 검증 근거

- `pytest -q middleware/perception/test/test_map_world_261026_scene.py` (5 passed).
- `ai@100.108.76.123`에서 Gazebo Sim v8.15.0(`gz_multi.launch.py`, `world_name:=map_world_261026.world`, `robots:=3`) 기동 및 3대 로봇(`rosy_01`, `rosy_02`, `rosy_03`) 스폰·주행(`tools/sim/bay_departure_sim.py`) 통과 확인.

## 다음에 적용할 조건

- SDF/URDF 생성 스크립트의 XML 단위 시험에는 반드시 형제 `<model>`·`<link>`·`<joint>`의 `name` 속성 유일성 단언과 부모 `<pose>` 대비 자식 로컬 좌표계 검증을 포함한다.
