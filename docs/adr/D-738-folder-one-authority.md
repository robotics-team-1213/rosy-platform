## D-738 폴더 이름은 권한 하나이고, 같은 역할만 한 폴더에 둔다

**Status:** Accepted
**Date:** 2026-10-13

## Context

편집 집은 현재 경로를 찾는 지도다. 그 지도만으로는 같은 basename이 두 권한을 가리키고, 한 역할의 구현과 노드가 서로 다른 폴더에 나뉘어 있다. D-649는 설치 이름의 반복을 유지하고, 권한이 다른 폴더를 이름 때문에 합치지 않는다. 이번 결정은 그 위에 저장소 폴더 이름의 규칙을 더한다. `control` 한 패키지의 개명이 아니다.

이 수락은 규칙과 착지 순서다. 폴더 이동, import 변경, 장치 수용은 각 단계의 커밋이 따로 한다.

## Decision

1. 저장소에서 여는 디렉터리의 마지막 이름은 권한 하나만 가리킨다. 다른 권한과 같은 basename을 두지 않는다.
2. Python import와 ROS 패키지 이름은 폴더 이름과 별개로 유지한다. 폴더를 옮겨도 `package_dir`와 `FOLDER_TO_PACKAGE`가 설치 이름을 잇는다. `perception` 배포 안의 `control`, `planning`, `safety`, `sensing`, `wander` 다섯 폴더는 설치 이름이라 유지한다.
3. 같은 입력과 같은 출력이고 구현이 둘이거나 알고리즘과 그 노드가 떨어져 있으면 한 기능 폴더에 둔다. ROS를 부르는 파일은 그 폴더의 한 파일이고, 판단은 ROS 없이 시험한다.
4. 출력이 다르면 나눈다. 사실, 명령, 원장, 임대, 후보 검사는 다른 폴더다. 이름만 같다고 합치지 않는다. 보정 세션 임대와 보정 동작, 공통 Safety와 동작 후보 검사, 장치 로컬 허용 동작과 현장 후보, 상황 사실과 Fleet의 막힘 답, 로봇 로컬 실행과 현장 실행, 천장 관측과 앞 카메라와 미리보기 저장, CORE의 `core/drive` 조립과 Drive 알고리즘, Fleet의 traffic·swarm과 Drive behavior는 각각 남긴다.
5. 경로는 실행 PC가 아니다(D-315). 빈 예측 폴더는 만들지 않는다.
6. 한 커밋은 한 단계다. 그 커밋을 로컬 `main`에 fast-forward한 뒤에 다음 단계를 연다. 시험이 실패하면 그 단계는 착지하지 않는다. 각 단계의 커밋이 편집 집 표의 현재 경로를 고친다.

단계 순서는 아래와 같다. 이 ADR을 수락한 시점에는 어느 단계도 이동하지 않았다.

| 단계 | 현재 폴더 | 목표 폴더 | 유지하는 설치 이름 |
|---|---|---|---|
| 1 | `middleware/control` | `middleware/drive` | 기존 Drive import |
| 2 | `middleware/perception/control`의 순수 판단 | 그 출력의 기능 폴더 | ROS 패키지 `control`의 진입점 |
| 3 | 단계 2 뒤에 남는 조립 폴더 | `middleware/perception/nodes` | ROS 패키지 `control` |
| 4 | `middleware/execution`, `operations/execution` | `middleware/robot_execution`, `operations/site_execution` | `rosy.execution.local`, `rosy.execution` |
| 5 | `middleware/ui`, `operations/ui` | `middleware/robot_ui`, `operations/site_ui` | `dashboard`, `emotion`, Console, Rosy Cam |
| 6 | `operations/vision`, `middleware/perception/vision` | `operations/overhead`, `middleware/perception/front_camera` | `rosy_vision`, 기존 인지 import |
| 7 | `core_features/decision`, `core_features/safety`, `core_features/vision`, `drive/safety` | `lane_rules`, `safety_gate`, `preview`, `motion_limits`와 옛 import 패키지 | `core_features.decision`, `core_features.safety`, `core_features.vision`, `control.safety` |
| 8 | `operations/fleet/fleet/server` | 원장, 채널, 셀 어댑터, 콘솔 조립, 피어 디렉터리 | 한 SQLite, 한 프로세스, 패키지 `fleet` |
| 9 | `middleware/perception/tools` | `tools/sim`, `tools/calibration` | 런타임 진입점이 아님 |
| 10 | `fleet.localization.map_pose` 호출자 | `operations/world`의 투영 | 호출 이전 뒤에 별칭을 거둠 |

`src/rosy/execution`, `src/rosy/decision`, `src/rosy/world`처럼 import 트리 안의 디렉터리는 바깥 폴더만 바꾼다.

| Previous ADR | Relationship |
|---|---|
| D-315 | 폴더 경로는 실행 호스트나 writer 권한이 아니다 |
| D-339 | 폴더 이름은 역할이고 ROS 패키지 이름은 유지한다. 다른 쌍은 `FOLDER_TO_PACKAGE`에 등록한다 |
| D-427 | part, import 방향, colcon root, 설치 패키지 identity를 유지한다 |
| D-625 | 의미 구조와 단계별 이전을 유지한다. 이번 규칙은 그 이후의 폴더 이름과 묶음이다 |
| D-649 | 설치 이름의 반복과 단일 구현을 유지한다. 권한이 다른 폴더는 합치지 않는다 |

## Consequences

다음 세션은 현재 경로로 파일을 연다. 목표 폴더는 그 단계가 착지된 뒤에 현재 경로가 된다. 로봇의 import, launch, 서비스 이름은 단계 1부터 10까지 바뀌지 않는다. 단계 7만 구현 폴더와 옛 import 패키지를 같이 둔다. 되돌림은 그 단계의 역방향 커밋이다.
