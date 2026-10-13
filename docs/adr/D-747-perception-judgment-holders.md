## D-747 Perception 판단을 출력별 기능 holder에 둔다

**Status:** Accepted
**Date:** 2026-10-13

## Context

D-738 S2는 perception/control의 순수 판단을 실제 출력별로 배치한다. ROS를 import하지 않는다는 사실만으로 파일 저장, 프로세스 제어, 보정 명령 조립을 순수 판단으로 분류할 수 없다. 판단과 그 전용 ROS adapter는 같은 기능 폴더에 둔다(D-738 결정 3).

## Decision

| 현재 control 파일 | 기능 holder | 출력과 권한 |
|---|---|---|
| loc_assist, loc_assist_node, localization_node | localization | 위치 후보·상태·confidence·승인된 pose 주입; CORE 결정 필요 |
| watch, watch_node | graph_health | graph 건강·interrupt; 최종 명령 writer 아님 |
| object_detector, object_detector_node | vision/object_observation | advisory detection evidence |
| ir_overlay, core_law_input, route_context_input, route_followers, line_observer_node | sensors/line_observation | observer 설정 검증·공개 law/route 입력·차선 관측; law writer 아님 |
| capture_trigger, capture_trigger_node | snapshots | 기록 snapshot 요청 판단·서비스 adapter; 기록 저장/삭제와 별도 |

1. 표의 14개 파일은 byte content를 유지하여 이동한다. 기존 control.* import, entry point, monkeypatch identity, 설치 복사 수, ROS wire와 map lineage는 유지한다. 이미 있는 source-path 확장과 setuptools flat-module 합성을 재사용한다.
2. 보정 mixin의 명령·transport, calibration provenance/storage, recording/pilot의 파일·process/eviction, executor, TF와 web 조립은 순수 판단으로 부르지 않는다. 이들은 S3 잔여 조립 범위다. 이미 분리된 sensing/vision/Drive 판단은 다시 옮기지 않는다.
3. 설치 이름 control과 다섯 기존 facade는 유지한다. S3는 이 단계 뒤의 잔여 ROS 조립을 nodes에 배치하며 이 기능 holder를 다시 옮기지 않는다.
4. 현재 source 소비자, source audit, 구조 ceiling 예외와 backlog 경로를 같이 갱신한다. 과거 ADR·기록·immutable d427_target은 보존한다. ceiling 숫자나 안전 규칙을 완화하지 않는다.
5. 독립 Safety 검토와 원격 회귀·standalone sdist/wheel·known_failures NEW 0 이후 local main에 fast-forward한다. push와 배포는 이 결정의 완료 기준이 아니다.

| Previous ADR | Relationship |
|---|---|
| D-427 | part·colcon·설치 identity 및 immutable 원래 target 유지 |
| D-429 | 관측·상태·요청·명령 권한을 분리 |
| D-430 | safety source 이동의 독립 검토와 trailer 유지 |
| D-738 | S2 기능 경계와 adapter 동거 확정; 단계 순서 유지 |
| D-743 | 승격된 Drive는 다시 이동하지 않음 |

## Consequences

소스 편집 위치와 설치 namespace 사이의 지도가 남는다. 한 구현만 설치하고 standalone source archive가 이 지도를 포함해야 한다. 소스 검사와 단위 시험은 ROS transport, ARM64 artifact, 장치 또는 현장 수용을 증명하지 않는다. 되돌림은 mapping과 소비자를 함께 되돌리는 새 커밋이다.
