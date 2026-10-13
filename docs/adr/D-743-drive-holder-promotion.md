## D-743 Drive holder를 한 층 올리고 설치·배포 identity를 유지한다

**Status:** Accepted
**Date:** 2026-10-13

## Context

D-738 S1의 바깥 control 개명만 적용하면 middleware/drive/drive가 된다. 구조 토론에서 책임, 설치·배포, 최소 변경 관점은 안쪽 Drive holder 승격에 합의했다. 현재 바깥 control에는 drive와 안내만 있다. 이 결정은 S1의 정확한 경로와 완료 기준을 보완하며 나머지 단계 순서는 바꾸지 않는다.

## Decision

1. `middleware/control/drive`의 추적 소스를 `middleware/drive`로 올리고 바깥 control 안내를 Drive 안내에 통합한다. CORE `middleware/core/gateway/core/drive` 조립은 그대로다.
2. 기존 `control.*`, `core_features.*`, ROS `navigation` identity와 진입점·자산·CORE 최종 명령 권한을 유지한다. manifest의 immutable `d427_target`은 보존하고 `path`, `layout_target`, safety anchors와 harness의 현재 경로를 갱신한다.
3. source mapping, sdist 파일 목록, Docker source와 내부 fallback 경로, 서명 release prefix·필수 파일, 개발 동기화와 시험 소비자를 한 단계에서 맞춘다. 기존 byte content·설치 단독성·서명 배포 경계 검사를 재사용한다.
4. 전역 basename 유일성 검사로 package namespace나 CORE 조립을 개명하지 않는다. S6은 signal_observer가 천장 전용이 아니므로 실행 전에 카메라와 lamp-state 관측 holder 범위를 확정한다. 이번에 S6 파일을 옮기지 않는다.
5. 독립 Safety 리뷰, 원격 affected 검사와 known_failures의 NEW 0 이후 local main에 fast-forward한다. Accepted는 시험·착지·배포·현장 수용의 완료 표시가 아니다.

| Previous ADR | Relationship |
|---|---|
| D-427 | part, import, colcon와 설치 identity 유지 |
| D-429 | 출력과 실행 권한 경계 유지 |
| D-430 | safety source와 anchors 이동에 독립 리뷰·trailer 적용 |
| D-649 | 단일 Drive 구현과 기존 설치 mapping 유지 |
| D-738 | S1 최종 트리 보완, S1~S10 순서 유지 |

## Consequences

편집 경로가 middleware/drive 아래 한 집으로 줄어든다. 설치 namespace는 별도 지도이므로 유지보수 비용이 남는다. 이미 빌드된 이미지나 source archive는 자동 갱신되지 않는다. 되돌림은 경로·소스 mapping·배포 소비자를 함께 되돌리는 새 커밋이다.
