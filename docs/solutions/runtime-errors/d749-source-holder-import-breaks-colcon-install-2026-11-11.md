---
title: D-749 소스 폴더 이름(safety_gate·action_rules·preview)으로 import하면 소스 트리 pytest는 통과하지만 colcon 설치본에서 CORE가 죽는다
date: 2026-11-11
category: runtime-errors
module: middleware/core/api (core_api_web.api.deps), middleware/core/services (core_features)
problem_type: runtime_error
component: device_runtime
severity: high
symptoms:
  - "colcon build 설치본에서 CORE 기동 직후 죽음: ModuleNotFoundError: No module named 'core_features.safety_gate'"
  - "fleet_trips 등 Gazebo 런타임에서 core_ready: false 로 실패"
  - "소스 트리를 sys.path에 올리는 호스트 pytest는 모두 통과"
root_cause: source_holder_vs_installed_package_mismatch
resolution_type: code_fix
tags: [d-749, d-649, core_features, safety_gate, action_rules, preview, colcon, import-boundary]
---

## 증상

2026-11-11 Pinky Pro Gazebo 주행 파이프라인(`fleet_trips.py`) 실행 시 `core-7`(`rosy_01`)과 `core-13`(`rosy_02`) 프로세스가 기동 직후 `ModuleNotFoundError: No module named 'core_features.safety_gate'`(`core_api_web/api/deps.py:33`)로 종료되어 `core_ready: false`가 발생했다. 호스트 `pytest`는 모두 통과한 상태였다.

## 원인

D-749 / D-649(`middleware/core/services/core_features/_source_layout.py`, `middleware/core/services/setup.py`)에 따라 `core_features` 내부의 세 도메인 폴더는 소스 트리 폴더 이름과 colcon 설치 패키지 이름이 다르다.

- `core_features/action_rules` → 설치 패키지 `core_features.decision`
- `core_features/safety_gate` → 설치 패키지 `core_features.safety`
- `core_features/preview` → 설치 패키지 `core_features.vision`

`middleware/core/services/setup.py`는 `find_packages(exclude=['test', 'core_features.action_rules*', 'core_features.safety_gate*', 'core_features.preview*'])`로 소스 홀더 이름을 설치에서 제외하고 `package_dir` 매핑으로 `core_features.decision`·`core_features.safety`·`core_features.vision`만 설치한다. 반면 소스 체크아웃에서는 `middleware/core/services`가 `sys.path`에 직접 올라가므로 `core_features/safety_gate` 폴더가 파이썬 패키지로 보였고, `292f36fd63`이 `core_api_web/api/deps.py`에 `from core_features.safety_gate.limits import SpeedLimits`를 넣었을 때 호스트 pytest는 이를 걸러내지 못했다.

## 해결

1. `middleware/core/api/core_api_web/api/deps.py`, `middleware/core/gateway/test/test_speed_limit_settings.py`, `test/test_app_ownership_contracts.py`의 `core_features.safety_gate.*` import를 설치 패키지 이름인 `core_features.safety.*`로 고쳤다.
2. `middleware/core/gateway/test/test_v1_import_boundary.py`(`test_deps_still_owns_the_domain_type_surface`)에 `core_features.action_rules`, `core_features.safety_gate`, `core_features.preview`가 `api/deps.py`에 등장하지 않음을 검사하는 단언을 추가했다.

## 다음에 적용할 조건

- `core_features` 하위 모듈을 import할 때는 파일 경로(`action_rules`, `safety_gate`, `preview`)가 아니라 설치 패키지 이름(`core_features.decision`, `core_features.safety`, `core_features.vision`)만 사용한다.
- `setup.py`에서 `package_dir`와 `exclude`로 소스 폴더 이름을 숨기는 패키지(`middleware/core/services`)를 건드릴 때는 호스트 소스 트리 pytest만으로 설치본 import가 증명되지 않으므로 경계 시험 또는 colcon 설치본 기동(`remote_sim.py`)으로 확인한다.

## 검증

- `pytest middleware/core/gateway/test/test_v1_import_boundary.py middleware/core/gateway/test/test_speed_limit_settings.py` 통과.
- `remote_sim.py`로 colcon 빌드 후 Gazebo + 2대 Pinky Pro CORE 기동 및 `fleet_trips.py --pipeline` 통과 확인.
