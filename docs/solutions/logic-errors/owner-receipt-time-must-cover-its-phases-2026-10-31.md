---
title: 소유자 receipt의 시각은 그 안의 모든 phase 시각을 덮어야 한다
date: 2026-10-31
category: logic-errors
module: middleware/devices/omx/adapter (ActionRunner receipt, policy_parent.projection) + Fleet physical transfer
modules: [middleware, operations]
problem_type: logic_error
component: owner_fleet_contract
severity: high
symptoms:
  - "실제 시뮬 소유자의 첫 ARM_TRANSFER 응답을 Fleet가 'physical owner receipt clock is future or regressed'로 거절했다"
  - "Fleet 작업이 PHYSICAL_SUBMIT_OUTCOME_UNKNOWN 또는 PHYSICAL_LOOKUP_OUTCOME_UNKNOWN으로 HOLD됐다"
root_cause: inconsistent_timestamps
resolution_type: code_fix
tags: [omx, fleet, arm-transfer, receipt, clock, synthetic-owner]
applies_when:
  - "소유자 receipt·projection의 observed_at을 만들거나 바꿀 때"
  - "합성 소유자만으로 통과한 Fleet–소유자 계약을 실제 소유자에 처음 붙일 때"
---

# 소유자 receipt의 시각은 그 안의 모든 phase 시각을 덮어야 한다

## Problem

D-927 C4에서 Harbor 하네스가 MuJoCo 시뮬 셀 소유자를 실제로 띄우자, 소유자가 SubmitAction에 ACCEPTED를
돌려줬는데도 Fleet가 그 receipt를 거절하고 작업을 HOLD했다. 합성 소유자(`SyntheticOwner`)를 쓴 하네스와
단위 시험은 모두 통과했었다.

## Root cause

receipt의 `observed_at`은 부모 Action 행의 `updated_at`이었고, `phase_summaries[].observed_at`은 각 phase 행의
`updated_at`이었다. 소유자는 계획을 마친 뒤 첫 phase를 기록하므로 phase 시각이 부모보다 늦을 수 있다
(관측: 부모 15:01:55.455, approach phase 15:01:55.647). Fleet `record_receipt`는 모든 phase가
`issued_at <= phase.observed_at <= receipt.observed_at` 안에 있기를 요구하므로 거절이 맞다.
합성 소유자는 receipt와 phase에 같은 `at`을 써서 이 어긋남을 만들 수 없었다.

## Solution

`policy_parent.projection()`이 부모 시각을 부모와 그 phase들 중 가장 늦은 시각으로 정하고(`datetime`으로 비교,
ISO 문자열은 마이크로초 0을 생략해 사전순 비교가 틀린다), `ActionRunner._receipt`는 같은 projection 값을 쓴다.
GetAction 응답과 parent readback은 서로 byte 단위로 같은지 비교하므로 둘이 한 함수를 공유해야 한다.

```python
result['observed_at'] = max([result['observed_at'], *(p['observed_at'] for p in result['phase_summaries'])],
                            key=lambda stamp: datetime.fromisoformat(stamp.replace('Z', '+00:00')))
```

## Verification

- 회귀: `middleware/devices/omx/adapter/test/test_action_receipt_snapshot.py`의
  `test_a_phase_stamped_after_its_parent_row_is_covered_by_the_receipt_time`(부모보다 190 ms 늦은 phase,
  Fleet 파서로 읽어 모든 phase ≤ receipt 확인). receipt·ActionAPI·policy parent·셀 소유자 시험 102 passed.
- 실행: AI PC에서 Harbor `real_fleet_http --arm-only --sim-arm`이 고친 뒤 receipt 거절 없이 네 phase를 진행했다.

## Prevention

Fleet–소유자 계약 시험에 실제 소유자 경로(ActionRunner + phase recorder)를 적어도 하나 둔다. 합성 소유자는
시각·순서·지연을 이상적으로 만들어 이런 어긋남을 숨긴다([producer-consumer fixtures hide contract drift](producer-consumer-fixtures-hide-contract-drift-2026-09-30.md)).
