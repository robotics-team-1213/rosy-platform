# D-700 Fleet 실제 규칙 선택과 모델 비교 기준

**Status:** Accepted (2026-10-12, source contract)

## Context

D-697의 규칙 기준은 모델 export를 호출 0건으로 바꿔 만들 수 없다. 실제 StuckResolver가 선택한 결과가 필요하다. 모델의 reobserve/human과 BACK_AND_RETRY·YIELD·RESUME 등 CORE 명령은 서로 다른 의미다.

## Decision

기존 resolver step의 실제 반환값을 같은 pass의 Assessment와 roster/config hash에 결속해 Fleet의 기존 DB에 별도 규칙 선택 원장으로 기록한다. selector를 다시 호출하거나 shadow용 복구 명령을 내리지 않는다. NONE·ANSWER·HOLD·HANDOFF를 구분하며 선택이 실제 명령·성공·사람 인수를 뜻하지 않는다. 정상·관측 부족도 별도 상태로 남긴다. 원문 상태·좌표·계정은 선택 receipt에 복사하지 않는다.

규칙 선택 생산은 fleet.stuck.pipeline/loop, 저장은 fleet.observe, credential-free JSON 검증은 contracts.learning이 소유한다. 원장은 기존 SQLite 정책과 30일·100,000행 한도를 사용한다. 전체 poll/명령/모델 호출·재발 coverage는 별도이며 누락을 0건으로 채우지 않는다.

AI-first 또는 AI 사실·제안·대기 입력이 있는 pass는 MIXED로 기록하며 RULE_ONLY 기준으로 승인하지 않는다. roster/config hash는 그 입력 범위를 결속할 뿐 map callbacks·resolver lifecycle 전체의 독립 replay나 진본성을 인증하지 않는다. 독립 평가와 승격은 계속 HOLD다.

같은 사건·관측 revision·필요성 policy의 fresh RULE_ONLY 선택 중 HOLD만 reobserve, HANDOFF만 human으로 비교한다. WAIT를 포함한 모든 물리 ANSWER와 NONE은 임의로 변환하지 않는다. 실제 선택을 저장하는 동안 사람이 인수하면 기존 dispatch·관측 note와 비교 기준이 사람 점유를 보존한다. 설치 factory의 기본 baseline 포트는 현재 pass에서 저장한 선택만 읽고, 명시적 기존 baseline 포트는 유지한다. 모델의 실제 행동 권한을 추가하지 않는다.

이 원장은 기본 resolver의 JSON 검증에도 쓰이므로 기존 ROS-free `rosy-contracts-learning>=0.1.10`을 Fleet 필수 설치 의존성으로 명시한다. 기존 `fleet[learning]` extra 이름은 유지하며 원래의 계약 wheel을 재사용한다. wheel·sdist에서 이 의존성의 설치 위치와 기본 resolver 생성을 확인한다. 별도 학습 런타임·torch·ROS 의존성을 추가하지 않는다.

| 기존 계약 | 관계 |
|---|---|
| D-427 | Fleet은 선택·원장·운영 연결, learning은 고정 산출물 소비와 독립 평가를 담당한다. |
| D-429 | 기존 holder·같은 Fleet 배포·SQLite 경계를 유지하며 새 서비스나 writer를 만들지 않는다. |
| D-430 | 규칙 receipt는 admission이 아니다. CORE 최종 안전 guard·명령과 기존 결과 확인을 유지한다. |

## Verification

실제 resolver pass의 정상·HOLD·HANDOFF·물리 ANSWER·MIXED를 시험하고 실패한 기록·다른 사건·stale/ABSTAIN 자료가 비교 기준으로 쓰이지 않게 한다. 원장 JSON 검증·보존·동일 설치 closure·기존 resolver/model loop 회귀와 독립 검토를 수행한다. source 통과와 실제 모델·서비스 배포·현장 수용을 구분한다.
