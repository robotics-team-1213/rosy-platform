# D-730 동일 Fleet DB의 운영 수용 epoch와 사건 단일 제출 claim

**Status:** Accepted (2026-10-12, source contract; no operational activation)

## Context

D-727은 서명 검증 계약이다. 실제 모델 후보를 기존 단일 Fleet 소비자로 연결하려면 현재 수용/폐기 상태와 사건의 물리 제출 한계를 같은 DB에서 원자적으로 확인해야 한다. 프로파일 교체·새 관측·재시작이 제출 한계를 초기화하면 안 된다.

## Decision

기존 IncidentCaseStore와 LineStuckAnswerLog의 같은 SQLite DB를 사용한다. 별도 서비스는 만들지 않는다. `automation/operating`은 검증 후보·운영 수용 사건·단일 제출 기록을 소유하고 provider 호출은 기존 execution에 유지한다. 기존 candidate import는 identity alias로 보존하며 부모/ledger/execution의 크기 기준은 유지한다.

ROOT owner가 제공하는 trusted/evidence 포트는 현재 독립 평가 원본·전체 profiles·선택 profile·서명된 보정 승인을 재검증한다. 평가 원본의 HOLD·digest 차이·현재 보정/프로파일/설치/trust 차이는 수용과 claim을 거절한다. 이 저장소는 독립 평가를 계산하지 않는다. 실제 producer와 현재 설치 getter를 구성하기 전 운영 경로는 활성화하지 않는다. 테스트의 accepted evidence 포트와 키는 격리된 source fixture이며 현장 증거가 아니다.

별도 수용/폐기 서명과 현재 epoch CAS로 변경을 기록한다. 폐기는 현재 증거가 HOLD이거나 기간이 지난 경우에도 저장된 원래 binding을 대상으로 적용할 수 있다. claim은 `BEGIN IMMEDIATE` 안에서 현재 epoch·현재 독립 근거·서명·active CaseScope·완료한 검증 후보·profile/model/policy/generation과 owner 최종 guard를 확인한 뒤 사건당 한 번 기록한다. 모델·규칙은 `(subject_id, case_id)` 단일 slot을 공유하고 legacy의 이미 접수된 답·PENDING·UNKNOWN도 새 모델 제출을 막는다.

claim은 제출 시작의 선형화 지점이다. 선행 폐기는 거절하고 후행 폐기는 제출을 재발행하지 않으며 결과를 UNKNOWN으로 유지한다. CORE back ACK는 raw reply 사실로 별도 보존하고 물리 성공으로 승격하지 않는다. 모든 terminal 상태에서 slot을 해제하지 않는다. 모델/관측/비용 예산은 그대로 유지한다. 실제 RobotClient 제출은 기존 loop의 D-724 before_submit 포트가 소유하며 이 원장은 직접 네트워크나 motion을 호출하지 않는다.

## Verification

독립 SOURCE 검토에서 claim 직전 case 만료·HOLD 재검사, 규칙 제출의 별도 terminal 기록, 과거 APPROVE/REVOKE 서명 인증을 추가했다. 규칙 ACK는 모델 수용을 요구하지 않으며 UNKNOWN은 이후 ACK로 지우지 않는다. CORE 정지·E-stop 경로를 claim으로 막아서는 안 된다. 원장의 slot은 제출 경합을 막는 내부 메커니즘이며 현재 실제 resolver 소비 경로는 아직 연결하지 않았다.

실제 SQLite CAS·restart·경합, 현재 원본 HOLD/digest/profile/보정/trust/epoch/기한/guard 거절, 단일 rule/model slot과 legacy 차단, 취소/UNKNOWN 보존, 실제 installed closure를 원격 검증한다. ROOT의 producer/config와 실제 loop/CORE 응답/결과 연결·모델·현장 수용은 별도이며 전체 목표는 ACTIVE다.
