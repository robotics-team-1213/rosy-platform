## D-779 Cell Job 원장을 팔 단위로 나눈다: 팔별 상태, Step 의존 관계, 팔·구역 claim

**Status:** Accepted (2026-10-17, 사용자 승인; 원장·claim·grant 필드의 모양만 수용했다. 구현, 원장 버전 3 마이그레이션, API reference 개정, 장치 수용은 아직이다. 기반 방향인 D-778은 Proposed다)

이 ADR은 D-778 §9의 첫 선행 조건, 즉 Cell Job의 원장과 claim을 팔 단위로 나누는 모양을 정한다. 코드 변경, 공개 API 경로, 장치 수용을 뜻하지 않는다. 폴더나 패키지 구조는 바꾸지 않으므로 D-427·D-429·D-430의 소스 배치와 관계없다.

## Context

[D-778](D-778-bimanual-workcell-foundation.md)은 한 팔과 두 팔 작업대가 함께 쓰는 구조를 정했다. 그 구조가 원장에서 요구하는 것은 네 가지다.

- 한 팔의 실패는 그 팔과 구역만 멈춘다. 다른 팔은 한 팔 모드로 이어 간다.
- 협조 Step은 팔마다 Action을 하나씩 낸다.
- 두 팔은 팔레트의 고정 구역과 공유 띠를 나눠 쓴다.
- 단단한 결합 Step이 실패하면 두 팔이 함께 멈춘다.

지금 원장은 팔 하나를 전제한다. 로컬 main 기준의 소스를 읽은 결과다.

| 영역 | 지금 | 근거 |
|---|---|---|
| Job | `fleet_cell_jobs` 행 하나에 `workcell_id`·`instance_id`·`status`·`current_step_index`가 하나씩 있다 | `operations/fleet/fleet/server/cell/cell_job_store.py` |
| 결과 처리 | FAILED·REJECTED·NOT_FOUND는 Job을 HOLD하고 claim을 HELD로, UNKNOWN은 claim을 UNKNOWN으로 바꾼다. 범위는 Job 전체다 | 같은 파일 `_OUTCOMES` |
| Step | `fleet_cell_steps`의 키는 `(mission_id, step_index)`이고, `action_id`·`attempt_id`·`grant_json`·`result_json`이 한 벌이다 | `operations/fleet/fleet/server/work/step_ledger_schema.py` |
| 순서 | 디스패처는 READY Job의 `current_step_index` 한 Step만 낸다 | `operations/fleet/fleet/server/step_dispatcher.py` |
| 인스턴스 | 설정이 작업대 하나를 인스턴스 하나로 매핑하고, Job의 인스턴스와 다르면 거부한다 | 같은 파일 `omx_instances` |
| claim | `fleet_action_claims`의 `resource_key`가 기본 키다. 종류는 robot·workcell·object·pallet이고, savepoint로 모두 잡거나 하나도 잡지 않는다. 해제는 owner 단위다 | `operations/fleet/fleet/server/ledger/task_store.py`, `operations/fleet/fleet/server/dispatch_admission.py` |
| grant | `FleetCellTransferGrant`는 추가 필드를 금지하고, `action_kind`는 `CELL_TRANSFER`만 허용한다 | `contracts/foundation/core_common/protocol/schemas.py` |
| 마이그레이션 | `cell_jobs` 원장 버전은 2다. 더 높은 버전을 보면 옛 Fleet은 원장을 읽지 않고 거부한다 | `cell_job_store.py` `_MIGRATION_VERSION` |

## Decision

Job은 작업대 하나를 계속 가리킨다. 그 아래에 **팔별 상태**와 **팔별 Action**을 두고, Step의 순서는 **의존 관계**로 표현한다. claim에는 `arm`과 `zone` 종류를 더한다. 팔이 하나인 작업대는 팔 행이 하나이고, 의존 관계가 앞 Step 하나인 경우다. 그러면 지금의 동작과 같다.

### 1. 팔별 상태 표

`fleet_cell_job_arms`를 더한다.

| 열 | 뜻 |
|---|---|
| `mission_id`, `arm_role` | 기본 키. `arm_role`은 `cell.yaml`의 `arms[].role`(예: `left`, `right`) |
| `instance_id` | 그 팔의 owner 인스턴스 |
| `status` | `READY`, `RUNNING`, `HOLD`, `OFFLINE` |
| `running_step_index` | 그 팔이 지금 실행 중인 Step. 없으면 NULL |
| `reason`, `updated_at` | HOLD·OFFLINE의 이유와 시각 |

- `OFFLINE`은 그 팔의 owner가 설정에 없거나, 장치 재승인을 기다리는 상태다. 운영자나 시작 점검이 정한다.
- Job의 `status`는 팔 상태와 Step 상태에서 나오는 요약이 된다.
    - 실행 중인 팔이 하나라도 있으면 `RUNNING`이다.
    - 모든 Step이 `GOAL_CONFIRMED`이면 `GOAL_CONFIRMED`다.
    - 실행할 수 있는 팔이 하나도 없으면 `HOLD`다.
    - 그 밖에는 `READY`다.
- `fleet_cell_jobs.instance_id`는 팔이 하나인 Job에서만 의미가 있다. 팔이 둘인 Job에서는 팔 표가 정본이다.

### 2. Step은 의존 관계로 순서를 정한다

- 컴파일러는 Step마다 `depends_on`(먼저 `GOAL_CONFIRMED`되어야 하는 Step 번호 목록)을 적는다. 지지 관계(아래 물체가 먼저), 접근 경로(먼 쪽이 먼저), 같은 구역을 쓰는 Step끼리의 순서가 근거다.
- Step이 실행 가능해지려면 세 가지가 모두 맞아야 한다.
    - `depends_on`이 모두 `GOAL_CONFIRMED`다.
    - 배정된 팔이 `READY`다.
    - 그 Step의 구역 claim을 잡을 수 있다.
- 팔이 하나인 Job은 `depends_on = [i-1]`이다. 그래서 지금의 직렬 순서와 같다.
- `current_step_index`는 남겨 두고, 뜻을 "아직 확인되지 않은 가장 작은 Step 번호"로 바꾼다. 읽기 모델과 Console이 계속 쓸 수 있다.
- `depends_on`은 컴파일 결과의 일부이므로 Job 해시와 두 사람 승인(D-401 §3, D-403 §3)이 그대로 덮는다.

### 3. Step의 Action은 팔마다 하나씩, 별도 표에 둔다

`fleet_cell_step_actions`를 더한다.

| 열 | 뜻 |
|---|---|
| `mission_id`, `step_index`, `arm_role` | 기본 키 |
| `action_kind` | 레지스트리의 종류. 지금은 `CELL_TRANSFER`. 후속 ADR이 `CELL_PUSH`, `CELL_HANDOVER`를 더한다 |
| `action_id` (UNIQUE), `attempt_id`, `request_digest`, `grant_json`, `result_json` | 지금 `fleet_cell_steps`에 있는 Action 열과 같다 |
| `claims_json` | 이 Action이 잡은 `resource_key` 목록 |
| `status` | `WAITING`, `READY`, `RUNNING`, `ACTION_SUCCEEDED`, `HOLD` |
| `reason`, `updated_at` | |

- `fleet_cell_steps`는 Step 단위의 상태(`GOAL_CONFIRMED` 포함), 목표 증거, `step_json`을 계속 가진다.
- Step의 `ACTION_SUCCEEDED`는 그 Step의 모든 팔 Action이 `ACTION_SUCCEEDED`일 때다. 목표 증거와 `GOAL_CONFIRMED`는 지금처럼 Step 단위로 판정한다(D-403 §5).
- `step_json`에는 D-778 §6의 역할, 결합 방식(`coupling`), 쓰는 구역(`zone`)이 들어간다.

### 4. 대체 팔과 한 팔 모드

- 컴파일러는 Step마다 주 배정 팔(`arm`)과, 같은 Step을 할 수 있는 대체 팔(`alternates`)을 적는다. 대체 팔마다 그 팔의 `base_in_cell`로 바꾼 Action 내용을 함께 컴파일한다. 그래서 대체 팔로 바꿔도 Job 해시와 승인 범위 안에 있다.
- 주 배정 팔이 `HOLD`나 `OFFLINE`이면 디스패처는 대체 팔로 Step을 낼 수 있다. 그 사실과 이유를 `fleet_cell_events`에 남긴다. 이것이 D-778 §5의 한 팔 모드다.
- 대체 팔이 없는 Step(단단한 결합 Step, 한 팔만 닿는 자리)은 그 팔이 돌아올 때까지 기다린다. 기다리는 Step에 의존하는 Step도 기다린다.
- 대체 팔로 이미 낸 Step은 원래 팔이 돌아와도 되돌리지 않는다.

### 5. claim에 `arm`과 `zone`을 더한다

- `fleet_action_claims`의 종류에 `arm`(`<workcell_id>.<arm_role>`)과 `zone`(`<workcell_id>.<zone_id>`)을 더한다. 표 모양은 바꾸지 않는다. `resource_key`가 기본 키이므로, 두 팔이 같은 구역을 동시에 잡을 수 없다.
- Job은 승인 때부터 끝날 때까지 지금처럼 `workcell`과 `pallet` claim을 Job 단위로 가진다(D-403 1b 보강).
- `arm`과 `zone` claim은 Action 단위다. Action을 낼 때 `DISPATCHING`으로 잡고, 잡은 키를 `claims_json`에 적는다. Action이 `ACTION_SUCCEEDED`가 되면 그 키만 놓는다. 이를 위해 owner 단위 해제 외에 키 목록 단위의 해제를 더한다.
- 협조 Step은 모든 팔의 `arm`·`zone` claim을 지금의 savepoint로 모두 잡거나 하나도 잡지 않는다.
- 사이트 정지 래치(`hold_for_site_stop`)는 지금처럼 Cell Job의 `CLAIMED` claim을 `HELD`로 바꾼다. `DISPATCHING`인 팔·구역 claim은 그대로 둔다.

### 6. 결과 처리는 팔 단위가 기본이다 (D-403 1b 보강의 부분 대체)

| 팔 Action 결과 | 그 팔 | 그 팔의 `arm`·`zone` claim | 짝 팔 | Job |
|---|---|---|---|---|
| `SUCCEEDED` | `READY` | 놓는다 | 영향 없음 | 요약 갱신 |
| `FAILED`, `REJECTED`, `NOT_FOUND` | `HOLD` | `HELD` | 결합 방식이 `tight`이면 `HOLD`, 그 claim도 `HELD`. 아니면 영향 없음 | 실행할 팔이 없으면 `HOLD` |
| `UNKNOWN` | `HOLD` | `UNKNOWN` | 위와 같음. `tight`이면 짝의 claim도 `UNKNOWN` | 위와 같음 |

- `HELD`·`UNKNOWN` claim을 유지하고 풀지 않는 규칙은 D-403 1b 보강 그대로다. 바뀌는 것은 범위다. Job 전체가 아니라 그 팔과 그 팔이 잡은 구역이다.
- 팔의 재개는 팔 단위다. 운영자가 그 팔의 상태를 확인하고 재개하면 그 팔의 `HELD` claim을 놓는다. `UNKNOWN` claim은 지금처럼 장치 결과를 읽어 확정한 뒤에만 놓는다.
- Job 전체 재개(`resume`)는 모든 팔을 재개하는 것과 같다.
- 운영자 취소(`CANCELLED_BY_OPERATOR`)는 지금처럼 Job 전체에 적용한다.

### 7. 짝 grant의 필드

`FleetCellTransferGrant`에 선택 필드 세 개를 더한다. 이후 Action 종류가 늘어나도 같은 필드를 쓴다.

- `arm_role`: 이 grant가 가리키는 팔
- `pair_id`: 협조 Step에서 두 grant가 공유하는 식별자
- `partner_instance_id`: 짝 팔의 인스턴스

`pair_id`와 `partner_instance_id`는 둘 다 있거나 둘 다 없어야 한다. 팔이 하나인 grant는 세 필드가 없어도 지금처럼 유효하다. 이 변경은 공개 프로토콜이므로 API reference 버전과 `schemas.py`를 같은 변경에서 고친다(D-18). 버전 번호는 `api_reserve.py`로 선점한다. D-778 §4의 짝 수락 규칙(한쪽이 거부하면 다른 쪽을 취소)은 디스패처가 지킨다.

### 8. 마이그레이션

- `cell_jobs` 원장 버전을 3으로 올린다. 버전 3 원장을 본 옛 Fleet은 지금처럼 읽지 않고 거부한다.
- 한 savepoint 안에서 다음을 한다.
    - 새 두 표를 만든다.
    - 기존 Job마다 팔 행 하나를 만든다. `arm_role`은 그 작업대 `cell.yaml`의 유일한 팔 역할이고, 없으면 `left`다. `instance_id`는 Job의 값이다.
    - 기존 Step의 Action 열을 `fleet_cell_step_actions`로 복사한다.
    - 기존 Step의 `step_json`에 `depends_on = [i-1]`을 채운다. Job 해시는 다시 계산하지 않는다. 마이그레이션된 Job은 이 기본값을 쓴다는 사실을 이벤트로 남긴다.
- `fleet_cell_steps`의 Action 열은 한 release 동안 읽기 호환을 위해 남기고, 그 뒤 지운다.
- `resource_kind`는 표의 CHECK가 아니라 `_RESOURCE_KINDS`가 정한다. 그래서 claim 표는 다시 만들지 않는다.

## Alternatives

- **팔마다 Job을 따로 만들기:** 원장은 거의 바뀌지 않는다. 그러나 협조 Step을 두 Job에 나눠 적어야 하고, 두 Job의 claim을 원자적으로 잡을 방법이 없다. Step 의존 관계도 Job을 건너간다. 기각한다.
- **claim의 owner를 `mission_id:arm_role`로 쪼개기:** 표를 바꾸지 않고 팔 단위 해제를 할 수 있다. 그러나 Job 단위 claim과 팔 단위 claim의 owner가 달라져, 사이트 정지와 취소가 두 owner를 모두 찾아야 한다. 키 목록을 Action에 적는 쪽이 범위가 분명하다. 기각한다.
- **claim 표에 `arm_role` 열 더하기:** 범위는 분명하지만 다른 디스패치 경로(task, direct_action)까지 표를 다시 만들어야 한다. 기각한다.
- **Step을 계속 직렬로 두고 팔만 번갈아 쓰기:** 원장은 단순하다. 그러나 두 팔이 동시에 일할 수 없고, 한 팔 모드에서도 앞 Step이 막히면 전부 멈춘다. D-778의 병렬 적재를 할 수 없다. 기각한다.
- **한 팔 모드에서 남은 Step을 다시 컴파일하기:** 대체 팔을 미리 컴파일하지 않아도 된다. 그러나 새 Job 해시와 두 사람 승인이 다시 필요해, 장애 중에 사람이 끼어들어야 한다. 기각한다.

## Consequences

- `cell_job_store.py`, `step_ledger_schema.py`, `step_dispatcher.py`, `dispatch_admission.py`, 읽기 모델, Console Job 화면이 바뀐다. 디스패처는 Job 하나가 아니라 Job 안의 실행 가능한 Step 집합을 본다. 틱당 I/O 상한(`MAX_IO_PER_TICK`)은 팔 Action 단위로 센다.
- `omx_instances` 설정은 작업대 하나를 팔 역할별 인스턴스 목록으로 매핑한다. 팔이 하나인 설정은 지금 모양 그대로 읽힌다.
- 컴파일러는 `depends_on`, `arm`, `alternates`, `zone`, `coupling`을 내야 한다. 혼합 레시피 스키마(D-778 §9)와 함께 바뀐다.
- 팔 단위 재개와 상태를 보여 주는 API는 API reference에 새로 적어야 한다. 이 ADR은 경로를 정하지 않는다.

## Transition / Validation

1. **스키마와 마이그레이션 시험:**
    - 버전 2 원장을 버전 3으로 옮겨도 모든 Job, Step, Action, claim이 남는지 확인한다.
    - 옛 Fleet이 버전 3을 거부하는지 확인한다.
2. **한 팔 동등성 시험:** 팔이 하나인 Job의 시험이 바뀌지 않고 통과하는지 확인한다. 지금의 Cell Job·디스패처 시험 전부가 대상이다.
3. **팔 단위 HOLD 시험:**
    - 두 팔 Job에서 독립 Step의 한 팔 Action을 FAILED·UNKNOWN으로 끝내면, 그 팔과 그 구역만 HOLD되는지 확인한다.
    - 다른 팔이 의존하지 않는 Step을 계속 내는지 확인한다.
    - `tight` Step에서는 두 팔이 함께 HOLD되는지 확인한다.
4. **claim 시험:**
    - 두 팔이 같은 구역을 동시에 잡지 못하는지 확인한다.
    - 협조 Step의 claim 하나가 실패하면 아무것도 남지 않는지 확인한다.
    - `ACTION_SUCCEEDED`가 그 Action의 키만 놓는지 확인한다.
5. **한 팔 모드 시험:** 주 배정 팔이 `OFFLINE`일 때 대체 팔로 Step을 내고 이벤트를 남기는지 확인한다. 대체 팔이 없는 Step과 그 의존 Step은 기다리는지 확인한다.
6. 위 시험은 D-778 G1(SIM 권한과 배치)의 일부다.

열린 질문:

- `OFFLINE`을 누가 어떤 증거로 정하는가(시작 점검, owner identity 조회, 운영자)
- 대체 팔로 낸 Step의 목표 증거가 원래 팔 기준과 다를 때의 허용 오차

**References:** [D-778](D-778-bimanual-workcell-foundation.md), [D-401](D-401-rosy-cell-application.md), [D-403](D-403-fleet-cell-job-route-cell-transfer.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md), [D-435](D-435-work-orchestration-fleet-and-device-authority.md), [D-763](D-763-fleet-work-kinds-composed-steps.md).
