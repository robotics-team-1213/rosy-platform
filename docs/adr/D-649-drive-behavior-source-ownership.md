## D-649 Drive behavior source ownership and compatibility identities

**Status:** Accepted
**Date:** 2026-10-11

## Context

D-630/D-637은 기존 설치 이름을 유지하면서 소스 폴더를 옮겼다. 그러나 `core_features`에는 Base 전용 주행 동작 구현이, Perception에는 기존 이동 제어 ROS 진입 모듈이 남아 있었다. 반복되는 `core`, `control`, `fleet`에는 ROS/Python 설치 이름도 포함되므로, 이름의 반복과 실제 책임 혼재를 구분해야 한다.

## Decision

기존 `core_features.{line_follow,docking,navigation,localization,swarm,road_behaviour,traffic_policy}` 구현을 `middleware/control/drive/behaviors/<기존 이름>`으로 옮긴다. ROS 의존 없는 라이브러리 성격, `core_features` 배포 패키지와 import 이름을 유지한다. 소스 체크아웃에서만 적용되는 명시적 검색 경로와 setuptools 패키지 매핑으로 클래스·모듈·monkeypatch identity를 보존한다. sdist는 선언한 원본 폴더를 함께 담고, 설치 wheel은 각 identity에 구현을 한 벌만 둔다.

`control_node.py`, `goal_node.py`, `wander_node.py`, `safety_node.py`를 `middleware/perception/control`에서 `middleware/control/drive/runtime`으로 옮긴다. 기존 패키지 빌드 매핑으로 `control.*`와 ROS entry point를 유지한다. CORE와 함께 기존 최종 명령 발행기를 활성화하지 않는다.

공통 Command 중재, Safety Guard, 장치 identity·상태·전원·진단·Fleet 연결은 CORE에 둔다. `core/drive`는 CORE가 주행 기능을 생성하고 연결하는 조립 코드다. 보정 세션 lease는 camera/IMU/IR 보정도 보호하므로 CORE에 남긴다. `core_features.recovery.camera_fault`는 운영자가 선택할 동작의 허용 여부를 계산하므로 CORE admission 정책이다. Perception의 localization 노드는 관측·준비 상태와 pose 주입 근거를 제공하므로 Perception에 남긴다. 현재 World 상태 projection과 향후 행동 조건부 예측 계획을 구분하며, 이번 이동에서 예측기를 만들지 않는다.

| Previous ADR | Relationship |
|---|---|
| D-427 | part·import 방향·colcon root·설치 패키지 identity를 유지하고 이동 원본의 소유자를 선언한다 |
| D-429 | Drive는 장치 제어를 맡으며 학습이나 숙고형 Decision 의존을 추가하지 않는다 |
| D-430 | 영향받은 Safety 태그도 파일과 함께 옮기고 독립 검토와 커밋 trailer를 요구한다 |
| D-625–D-630 | 기존 backend·소스 매핑을 유지하며 Base 동작 구현의 책임 분리를 마무리한다 |
| D-637 | Fleet·Decision·Console·Learning의 소스 소유와 설치 범위를 유지한다 |

## Naming and authority

`behaviors`는 Base 동작 상태 기계, 제한된 탈출·복구, 곡률 처리와 관측에서 명령 후보를 만드는 로직을 맡는다. `tracking`, `planning`, `recovery`, `calibration`, `safety/adapter`는 기존 제어 계산을 맡는다. `runtime`은 기존 ROS 진입 어댑터를 맡는다. CORE 조립 코드가 이 기능들을 생성하고 연결하며, CORE Command/Safety와 bridge가 운영 최종 `/cmd_vel` 권한을 단독으로 유지한다. Arm 관절·Action 및 stop/rearm 권한은 OMX에 유지한다.

호환 패키지 폴더는 initializer만 두며 알고리즘 복사본을 두지 않는다. namespace·설치 이름의 반복은 역할을 설명하고 유지한다. `middleware/execution`은 장치 내부 실행, `operations/execution`은 현장 작업 오케스트레이션이다. `operations/apps/fleet`는 앱 gateway이고 `operations/fleet`는 Fleet transaction을 소유한다. 권한이 다른 폴더를 이름 때문에 합치지 않는다.

## Verification and rollback

CORE services/gateway, Perception, 구조 검사를 원격에서 수행하고 중복 시험 파일명은 별도 호출로 나눈다. 소스 검사가 실제 파일을 읽는지, 크기·결합도 검사 범위가 유지되는지 검증한다. 저장소 밖에서 sdist와 wheel을 빌드해 기존 import·단일 구현·리소스·패키지 metadata를 확인한다. 실패는 known-failure 목록과 비교하고 이동 커밋 전에 Safety 독립 검토를 받는다. 소스·폴더 검증과 ROS graph·ARM64 설치·현장 수용·실제 배포를 구분한다. 되돌림은 검토된 일반 역방향 커밋으로 수행하며 영속 데이터·지도/모델 계보·장치 identity를 변경하지 않는다.
