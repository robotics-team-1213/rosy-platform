## D-748 앞 카메라·천장 관측·신호등 관측의 source holder를 구분한다

**Status:** Accepted
**Date:** 2026-10-13

## Context

D-738 S6의 operations/vision에는 rosy_vision 천장 관측 패키지와 패키지 밖 signal_observer가 함께 있다. 신호등 상태 관측은 천장 카메라 전용 책임이 아니므로 전체를 overhead로 개명하면 책임 설명이 틀린다. 독립 구조 검토는 두 기존 owner의 분리를 권고했다.

## Decision

1. operations/vision/signal_observer를 operations/signal_observation으로 분리한다. lamp-state fact만 내는 기존 구현이며 신호 명령 장치 operations/site_devices/signal과 별도다.
2. 남은 rosy_vision 패키지 holder를 operations/overhead로 개명한다. middleware/perception/vision은 S2 object_observation을 포함해 front_camera로 개명한다.
3. 설치 control.sensing.perception·rosy_vision, 명령·프로토콜·서비스·캘리브레이션·지도 계보와 실행 권한을 유지한다. Docker/서명 archive/source mapping/current 소비자·guide를 함께 갱신하며 immutable d427_target은 보존한다.
4. S1~S10 순서는 유지한다. 사용자 local merge-only 범위에 따라 static 검사·독립 Safety 리뷰와 lint 후 local ff-only로 처리한다. 원격 pytest·배포·장치 수용은 NOT RUN이며 소스 머지가 그 증거를 대신하지 않는다.

| Previous ADR | Relationship |
|---|---|
| D-427 | 실제 path/layout_target 갱신, immutable target·설치 identity 유지 |
| D-429 | lamp 사실과 신호 명령의 owner 경계 유지 |
| D-430 | 안전 source 경로 검토와 trailer 적용 |
| D-738 | S6의 signal holder 분리 보완, 단계 순서 유지 |
| D-747 | object_observation 책임과 기존 import 유지 |

## Consequences

세 holder가 실제 관측 출력과 대응한다. 새 서비스·wheel·동작을 만들지 않는다. 되돌림은 holder와 mapping/배포 소비자를 함께 돌리는 새 커밋이다.

## 개정 (2026-10-14): overhead holder에서 D-377 폴더 이름 규칙과의 관계

2항이 `rosy_vision` 패키지의 source holder를 `operations/overhead`로 옮기고 3항이 설치 이름을 유지하므로, 이 holder의 폴더 이름은 D-377의 "폴더 마지막 이름과 패키지 이름은 `rosy_`만 다르다"를 따르지 않는다. D-377의 패키지 이름(`rosy_vision`)과 console script(`rosy-vision`) 규칙은 그대로 적용된다. D-377 본문은 바꾸지 않는다. 검사는 `test/architecture/test_app_identity.py`의 `identity_problems`가 word `vision`의 폴더 이름만 `overhead`로 받으며, 다른 app이나 participant에는 이 예외가 없다.
