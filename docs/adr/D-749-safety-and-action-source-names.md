## D-749 동작 규칙·공통 안전·미리보기·후보 제한 source 이름을 구분한다

**Status:** Accepted
**Date:** 2026-10-13

## Context

D-738 S7의 decision 구현은 차선뿐 아니라 제품별 allowed action set과 deterministic rule을 처리한다. lane_rules라는 이름으로 그 책임을 축소하지 않는다. 공통 e-stop/link/battery gate와 Drive 후보 제한은 별도 owner다.

## Decision

1. core_features/decision·safety·vision의 실제 소스를 같은 깊이의 action_rules·safety_gate·preview holder로 옮긴다. decision·safety·vision에는 기존 source facade만 두고 설치는 기존 core_features.* 이름으로 한 번만 한다. preview에는 기존 model/lane evidence 저장도 포함한다.
2. middleware/drive/safety를 motion_limits로 개명한다. 기존 control.control.*와 control.safety 설치 이름은 유지하며 CORE 최종 cmd_vel 권한을 바꾸지 않는다.
3. 기존 source mapping·build/sdist 패턴을 재사용한다. Docker/서명/개발/검사 소비자·manifest actual path를 갱신하고 immutable d427_target 및 구조 예산·역사적 판단은 보존한다.
4. 사용자 local merge-only 범위에서 source identity·단독 설치·독립 Safety 및 lint를 확인하고 ff-only로 착지한다. 원격 pytest·CI·image·장치 수용은 별도 NOT RUN이다.

| Previous ADR | Relationship |
|---|---|
| D-427 | 실제 source path와 설치 identity를 구분 |
| D-429 | allowed action id와 현장 조정·최종 명령을 구분 |
| D-430 | 공통 safety_gate와 후보 motion_limits의 경계·독립 리뷰 유지 |
| D-738 | S7 lane_rules 이름을 실제 출력에 맞는 action_rules로 보완 |
| D-649 | 기존 단일 source 구현 및 namespace mapping 재사용 |

## Consequences

새 dependency·서비스·writer를 만들지 않는다. 세 facade는 설치 이름을 잇는 용도이며 구현 복사본이 아니다. source 이동과 실제 runtime 수용은 서로 다른 증거다.
